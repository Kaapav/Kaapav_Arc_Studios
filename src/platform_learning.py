"""Evidence-only learning separated by YouTube, Facebook and Instagram."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .config import ROOT
from .growth_learning import MIN_ARM_SAMPLES, MIN_MEANINGFUL_VIEWS, TRAIT_ARMS, _manifest_index, extract_traits
from .meta_platform import _read, _write


STATE_PATH = ROOT / "analytics" / "platform_learning.json"
RECOMMENDATIONS_PATH = ROOT / "analytics" / "platform_recommendations.json"
WINDOWS = (24, 72, 168)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _published_age_hours(value: Any, now: datetime) -> int | None:
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(0, int((now - published).total_seconds() // 3600))
    except (TypeError, ValueError):
        return None


def _meta_score(row: dict[str, Any]) -> tuple[float, dict[str, float]]:
    views = _number(row.get("views"))
    likes = _number(row.get("likes"))
    comments = _number(row.get("comments"))
    shares = _number(row.get("shares"))
    saves = _number(row.get("saves"))
    complete = _number(row.get("complete_views"))
    view_component = min(1.0, math.log1p(views) / math.log(1001))
    engagement = min(1.0, ((likes + comments * 2 + shares * 3 + saves * 2) / max(views, 1)) / 0.12)
    completion = min(1.0, complete / max(views, 1)) if complete else 0.0
    weights = (0.65, 0.35, 0.0) if not complete else (0.50, 0.30, 0.20)
    score = view_component * weights[0] + engagement * weights[1] + completion * weights[2]
    return round(score, 6), {
        "views": views,
        "engagement_rate": round((likes + comments + shares + saves) / max(views, 1), 6),
        "completion_rate": round(complete / max(views, 1), 6) if complete else 0.0,
    }


def _recommend(observations: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    meaningful = [item for item in observations if item.get("meaningful")]
    for dimension, arms in TRAIT_ARMS.items():
        scored: dict[str, list[float]] = {arm: [] for arm in arms}
        for item in meaningful:
            arm = (item.get("traits") or {}).get(dimension)
            if arm in scored:
                scored[arm].append(float(item.get("score") or 0))
        eligible = [(arm, values) for arm, values in scored.items() if len(values) >= MIN_ARM_SAMPLES]
        if eligible:
            arm, values = max(eligible, key=lambda pair: sum(pair[1]) / len(pair[1]))
            result[dimension] = {
                "mode": "platform_evidence_available",
                "preferred": arm,
                "samples": len(values),
                "mean_score": round(sum(values) / len(values), 6),
            }
        else:
            result[dimension] = {
                "mode": "insufficient_platform_evidence",
                "preferred": None,
                "minimum_samples_per_arm": MIN_ARM_SAMPLES,
            }
    return result


def refresh(cfg) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    manifests = _manifest_index()
    youtube = _read(ROOT / "analytics" / "growth_learning.json", {})
    meta = _read(ROOT / "analytics" / "meta_analytics.json", {})
    owner_test_end = int(cfg.get("growth", "exclude_owner_test_episodes_through", default=0))
    learning_start = int(cfg.get("growth", "organic_learning_starts_episode", default=1))
    platforms: dict[str, Any] = {
        "youtube": {
            "status": "evidence_available" if youtube.get("observations") else "waiting",
            "observations": youtube.get("observations") or [],
            "excluded_owner_tests": youtube.get("excluded_owner_test_observations") or [],
        }
    }
    excluded: list[dict[str, Any]] = []
    for platform in ("facebook", "instagram"):
        observations = []
        for row in meta.get("media", []):
            if row.get("platform") != platform:
                continue
            episode = int(row.get("episode") or 0)
            series_id = str(row.get("series_id") or "")
            if series_id == "echo30" and (episode < learning_start or episode <= owner_test_end):
                excluded.append({
                    "platform": platform, "media_id": row.get("media_id"), "series_id": series_id,
                    "episode": episode, "reason": "owner-confirmed test range excluded from organic learning",
                })
                continue
            age_hours = _published_age_hours(row.get("published_at"), now)
            if age_hours is None:
                continue
            window = max((value for value in WINDOWS if age_hours >= value), default=0)
            manifest = manifests.get((series_id, episode))
            if not window or not manifest:
                continue
            score, components = _meta_score(row)
            meaningful = components["views"] >= MIN_MEANINGFUL_VIEWS and window >= 72
            observations.append({
                "platform": platform, "media_id": row.get("media_id"), "series_id": series_id,
                "episode": episode, "window_hours": window, "age_hours": age_hours,
                "score": score, "meaningful": meaningful,
                "diagnosis": (
                    "no_observed_distribution" if components["views"] == 0 and window >= 72
                    else "insufficient_sample" if not meaningful and window >= 72
                    else "collecting" if window < 72 else "evidence_available"
                ),
                "components": components, "traits": extract_traits(manifest),
            })
        platforms[platform] = {
            "status": "evidence_available" if observations else "waiting",
            "observations": observations,
        }
    recommendations = {name: _recommend(data.get("observations") or []) for name, data in platforms.items()}
    payload = {
        "schema_version": 1,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "observation_windows_hours": list(WINDOWS),
        "minimum_meaningful_views": MIN_MEANINGFUL_VIEWS,
        "platforms": platforms,
        "excluded_owner_tests": excluded,
        "truth_boundary": "Platforms are learned independently; unavailable metrics stay unknown and small samples cannot select winners.",
    }
    _write(STATE_PATH, payload)
    _write(RECOMMENDATIONS_PATH, {
        "schema_version": 1, "updated_at": payload["updated_at"],
        "platforms": recommendations,
        "cross_platform_rule": "Adopt a trait globally only after independent meaningful evidence agrees; otherwise keep controlled exploration.",
    })
    return payload
