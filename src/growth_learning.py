"""Evidence-driven YouTube learning loop for KAAPAV ARC Studios.

This module does not pretend that a handful of views is deep learning.  It
records packaging/story traits, waits for comparable observation windows, and
updates small Bayesian posteriors.  Low-sample and zero-view results remain
explicitly inconclusive while the next batch explores a different trait.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


STATE_PATH = ROOT / "analytics" / "growth_learning.json"
RECOMMENDATIONS_PATH = ROOT / "analytics" / "learning_recommendations.json"
DIRECTIVES_PATH = ROOT / "analytics" / "production_directives.json"
WINDOWS = (24, 72, 168)
MIN_MEANINGFUL_VIEWS = 20
MIN_ARM_SAMPLES = 6

TRAIT_ARMS = {
    "title_framing": ("impossible_event", "personal_stakes", "urgent_warning", "moral_choice"),
    "opening_hook": ("consequence_first", "warning_line", "countdown", "identity_reveal"),
    "thumbnail_focus": ("face_emotion", "object_anomaly", "two_character_conflict", "countdown_symbol"),
    "story_engine": ("relationship_choice", "mystery_reveal", "sacrifice", "survival_pressure"),
}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _episode_number(title: str) -> int | None:
    match = re.search(r"(?i)\b(?:ep\.?|episode)\s*(\d{1,3})\b", title or "")
    return int(match.group(1)) if match else None


def _trait(text: str, rules: list[tuple[str, tuple[str, ...]]], fallback: str) -> str:
    lowered = text.lower()
    for label, needles in rules:
        if any(needle in lowered for needle in needles):
            return label
    return fallback


def extract_traits(manifest: dict[str, Any]) -> dict[str, str]:
    """Classify authored choices without rewriting an approved story."""
    title = str(manifest.get("title") or "")
    first = str(((manifest.get("scenes") or [{}])[0]).get("text") or "")
    change = str(manifest.get("permanent_story_change") or "")
    thumbnail = str(manifest.get("thumbnail_text") or "")
    return {
        "title_framing": _trait(title, [
            ("urgent_warning", ("warn", "before", "left", "last", "countdown")),
            ("personal_stakes", ("his ", "her ", "father", "mother", "brother", "sister")),
            ("moral_choice", ("choose", "saved", "sacrifice", "betray")),
        ], "impossible_event"),
        "opening_hook": _trait(first, [
            ("warning_line", ("warn", "message", "voice said", "ordered")),
            ("countdown", ("minute", "second", "remaining", "left")),
            ("identity_reveal", ("was actually", "future self", "identity", "face")),
        ], "consequence_first"),
        "thumbnail_focus": _trait(thumbnail, [
            ("countdown_symbol", ("minute", "second", "left", "99", "zero")),
            ("object_anomaly", ("phone", "door", "clock", "key", "ocean", "moon")),
            ("two_character_conflict", ("betray", "choose", "versus", "trust", "lied")),
        ], "face_emotion"),
        "story_engine": _trait(change, [
            ("relationship_choice", ("trust", "forgive", "relationship", "ally", "together")),
            ("sacrifice", ("sacrifice", "gives up", "cost", "exchange")),
            ("survival_pressure", ("survive", "trapped", "countdown", "escape")),
        ], "mystery_reveal"),
    }


def _manifest_index() -> dict[tuple[str, int], dict[str, Any]]:
    plan = _load_json(ROOT / "content" / "studio_master_release_plan.json", {})
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for series in plan.get("series", []):
        slug = str(series.get("slug") or "")
        content_root = ROOT / str(series.get("content_root") or "")
        patterns = (
            content_root.glob("episode*/episode.json"),
            content_root.glob("episodes/ep*/episode.json"),
            content_root.glob("manual_production/episodes/ep*/episode.json"),
        )
        for group in patterns:
            for path in group:
                manifest = _load_json(path, {})
                episode = int(manifest.get("episode") or 0)
                if episode:
                    manifest["_path"] = str(path)
                    result[(slug, episode)] = manifest
    return result


def load_current_rows(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or ROOT / "analytics" / "current.csv"
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_history_rows(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or ROOT / "analytics" / "daily_snapshots.csv"
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def build_window_snapshots(cfg, history_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve the closest daily evidence for each 24/72/168-hour window."""
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    owner_test_end = int(cfg.get("growth", "exclude_owner_test_episodes_through", default=0))
    learning_start = int(cfg.get("growth", "organic_learning_starts_episode", default=1))
    for row in history_rows:
        if str(row.get("privacy")) != "public":
            continue
        episode = int(row.get("episode") or 0) or (_episode_number(str(row.get("title") or "")) or 0)
        if not episode:
            continue
        series_id = str(row.get("series_id") or "echo30")
        if series_id == "echo30" and (episode < learning_start or episode <= owner_test_end):
            continue
        try:
            published = datetime.fromisoformat(str(row.get("published_at") or "").replace("Z", "+00:00"))
            captured = datetime.fromisoformat(str(row.get("snapshot_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        age_hours = max(0, int((captured - published).total_seconds() // 3600))
        grouped.setdefault(str(row.get("video_id") or ""), []).append((age_hours, row))
    snapshots = []
    for video_id, captures in grouped.items():
        captures.sort(key=lambda pair: pair[0])
        for window in WINDOWS:
            eligible = [pair for pair in captures if window <= pair[0] <= window + 30]
            if not eligible:
                continue
            age_hours, row = min(eligible, key=lambda pair: pair[0] - window)
            episode = int(row.get("episode") or 0) or (_episode_number(str(row.get("title") or "")) or 0)
            snapshots.append({
                "video_id": video_id,
                "series_id": str(row.get("series_id") or "echo30"),
                "episode": episode,
                "window_hours": window,
                "captured_age_hours": age_hours,
                "views": int(_number(row.get("views"))),
                "likes": int(_number(row.get("likes"))),
                "comments": int(_number(row.get("comments"))),
            })
    return sorted(snapshots, key=lambda item: (item["series_id"], item["episode"], item["window_hours"]))


def _score(row: dict[str, Any], detailed: dict[str, Any]) -> tuple[float, dict[str, float]]:
    views = _number(row.get("views"))
    likes = _number(row.get("likes"))
    comments = _number(row.get("comments"))
    average_percentage = _number(detailed.get("averageViewPercentage"))
    shares = _number(detailed.get("shares"))
    gained = _number(detailed.get("subscribersGained"))
    engaged_views = _number(detailed.get("engagedViews"))
    shorts_feed_views = _number(detailed.get("shorts_feed_views"))
    view_component = min(1.0, math.log1p(views) / math.log(1001))
    engaged_component = min(1.0, engaged_views / max(views, 1))
    retention_component = min(1.0, average_percentage / 100.0) if average_percentage else 0.0
    engagement = min(1.0, ((likes + comments * 2 + shares * 3) / max(views, 1)) / 0.12)
    subscriber_conversion = min(1.0, (gained / max(views, 1)) / 0.02)
    if average_percentage:
        total = (view_component * 0.20 + engaged_component * 0.20 + retention_component * 0.30
                 + engagement * 0.20 + subscriber_conversion * 0.10)
    else:
        total = (view_component * 0.35 + engaged_component * 0.25
                 + engagement * 0.30 + subscriber_conversion * 0.10)
    return round(total, 6), {
        "views": views,
        "average_view_percentage": average_percentage,
        "engagement_rate": round((likes + comments + shares) / max(views, 1), 6),
        "subscriber_conversion": round(gained / max(views, 1), 6),
        "engaged_view_ratio": round(engaged_views / max(views, 1), 6),
        "shorts_feed_views": shorts_feed_views,
    }


def _diagnosis(row: dict[str, Any], detailed: dict[str, Any], window: int) -> str:
    views = int(_number(row.get("views")))
    retention = _number(detailed.get("averageViewPercentage"))
    shorts_feed_views = _number(detailed.get("shorts_feed_views"))
    if window < 72:
        return "collecting"
    if views == 0:
        return "no_observed_distribution"
    if str(row.get("release_kind") or "short") == "short" and shorts_feed_views == 0:
        return "no_shorts_feed_distribution"
    if views < MIN_MEANINGFUL_VIEWS:
        return "insufficient_sample"
    if retention and retention < 65:
        return "retention_failure"
    if retention >= 85 and views < 100:
        return "strong_retention_low_reach"
    if retention >= 75:
        return "healthy_retention"
    return "reach_observed_retention_unavailable" if not retention else "mixed"


def _posterior_template() -> dict[str, dict[str, dict[str, float]]]:
    return {
        dimension: {
            arm: {"alpha": 1.0, "beta": 1.0, "samples": 0, "score_sum": 0.0}
            for arm in arms
        }
        for dimension, arms in TRAIT_ARMS.items()
    }


def refresh_learning(
    cfg,
    rows: list[dict[str, Any]] | None = None,
    detailed_metrics: dict[str, dict[str, Any]] | None = None,
    history_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild learning state from source observations; safe to run repeatedly."""
    rows = rows if rows is not None else load_current_rows()
    detailed_metrics = detailed_metrics or _load_json(ROOT / "analytics" / "youtube_analytics.json", {}).get("videos", {})
    history_rows = history_rows if history_rows is not None else load_history_rows()
    manifests = _manifest_index()
    posteriors = _posterior_template()
    observations: list[dict[str, Any]] = []
    excluded_owner_tests: list[dict[str, Any]] = []
    learning_start = int(cfg.get("growth", "organic_learning_starts_episode", default=1))
    owner_test_end = int(cfg.get("growth", "exclude_owner_test_episodes_through", default=0))
    now = datetime.now(timezone.utc)
    for row in rows:
        if str(row.get("privacy")) != "public":
            continue
        episode = int(row.get("episode") or 0) or _episode_number(str(row.get("title") or ""))
        if not episode:
            continue
        series_id = str(row.get("series_id") or "echo30")
        if series_id == "echo30" and (episode < learning_start or episode <= owner_test_end):
            excluded_owner_tests.append({
                "video_id": row.get("video_id"), "episode": episode,
                "reason": "owner-confirmed test traffic; excluded from organic learning",
                "reported_views": int(_number(row.get("views"))), "organic_views": 0,
            })
            continue
        published_raw = str(row.get("published_at") or "")
        try:
            published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            age_hours = max(0, int((now - published).total_seconds() // 3600))
        except ValueError:
            continue
        window = max((value for value in WINDOWS if age_hours >= value), default=0)
        if not window:
            continue
        # Current release order starts with ECHO.  Later series use a release-ledger
        # series_id, which takes precedence when present.
        manifest = manifests.get((series_id, episode))
        if not manifest:
            continue
        traits = extract_traits(manifest)
        details = detailed_metrics.get(str(row.get("video_id")), {})
        score, components = _score(row, details)
        diagnosis = _diagnosis(row, details, window)
        meaningful = int(_number(row.get("views"))) >= MIN_MEANINGFUL_VIEWS and window >= 72
        success = meaningful and score >= 0.45
        observation = {
            "video_id": row.get("video_id"), "series_id": series_id, "episode": episode,
            "window_hours": window, "age_hours": age_hours, "score": score,
            "diagnosis": diagnosis, "meaningful": meaningful, "traits": traits,
            "components": components,
        }
        observations.append(observation)
        if meaningful:
            for dimension, arm in traits.items():
                posterior = posteriors[dimension][arm]
                posterior["samples"] += 1
                posterior["score_sum"] += score
                posterior["alpha" if success else "beta"] += 1

    for dimension in posteriors.values():
        for posterior in dimension.values():
            samples = int(posterior["samples"])
            posterior["mean_score"] = round(posterior["score_sum"] / samples, 6) if samples else None
            posterior["success_probability"] = round(
                posterior["alpha"] / (posterior["alpha"] + posterior["beta"]), 6
            )

    zero_ready = [o for o in observations if o["window_hours"] >= 72]
    zero_batch = len(zero_ready) >= 3 and all(o["components"]["views"] == 0 for o in zero_ready[-5:])
    channel_id = str(cfg.get("youtube", "expected_channel_id", default="") or "")
    state = {
        "schema_version": 2,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "channel_id": channel_id,
        "method": "small-sample Bayesian trait learning",
        "truth_constraint": "YouTube Data API does not expose Shorts-feed impressions; zero views is no_observed_distribution, not proof of a metadata cause.",
        "observation_windows_hours": list(WINDOWS),
        "minimum_meaningful_views": MIN_MEANINGFUL_VIEWS,
        "minimum_arm_samples": MIN_ARM_SAMPLES,
        "organic_baseline_views": int(cfg.get("growth", "owner_confirmed_organic_baseline_views", default=0)),
        "learning_starts_episode": learning_start,
        "excluded_owner_test_observations": excluded_owner_tests,
        "observations": observations,
        "window_snapshots": build_window_snapshots(cfg, history_rows),
        "posteriors": posteriors,
        "zero_view_batch_triggered": zero_batch,
    }
    _atomic_json(STATE_PATH, state)
    recommendations = build_recommendations(state)
    _atomic_json(RECOMMENDATIONS_PATH, recommendations)
    return state


def _stable_pick(options: tuple[str, ...], key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return options[int.from_bytes(digest[:2], "big") % len(options)]


def build_recommendations(state: dict[str, Any]) -> dict[str, Any]:
    recommendations: dict[str, Any] = {}
    for dimension, arms in (state.get("posteriors") or {}).items():
        eligible = [
            (name, data) for name, data in arms.items()
            if int(data.get("samples") or 0) >= MIN_ARM_SAMPLES
        ]
        if eligible:
            winner, data = max(eligible, key=lambda item: float(item[1].get("success_probability") or 0))
            recommendations[dimension] = {
                "mode": "exploit_with_20_percent_challenger",
                "preferred": winner,
                "evidence_samples": data["samples"],
                "success_probability": data["success_probability"],
            }
        else:
            under_sampled = min(arms, key=lambda name: int(arms[name].get("samples") or 0))
            recommendations[dimension] = {
                "mode": "balanced_exploration",
                "preferred": under_sampled,
                "reason": "No arm has six meaningful observations yet",
            }
    return {
        "schema_version": 1,
        "updated_at": state.get("updated_at"),
        "zero_view_response": (
            "explore_new_subject_and_packaging_pair; preserve published videos; do not claim a winner"
            if state.get("zero_view_batch_triggered") else "continue_controlled_learning"
        ),
        "recommendations": recommendations,
    }


def write_production_directives(start_episode: int = 11, end_episode: int = 30) -> dict[str, Any]:
    """Create deterministic future directives without mutating approved manifests."""
    state = _load_json(STATE_PATH, {"posteriors": _posterior_template()})
    recommendations = build_recommendations(state).get("recommendations", {})
    directives = []
    for episode in range(start_episode, end_episode + 1):
        traits = {}
        for dimension, arms in TRAIT_ARMS.items():
            preferred = (recommendations.get(dimension) or {}).get("preferred")
            # Every fifth episode is an explicit challenger so the learner never
            # locks itself into an early accidental winner.
            if episode % 5 == 0 or not preferred:
                preferred = _stable_pick(arms, f"echo30:{episode}:{dimension}")
            traits[dimension] = preferred
        directives.append({
            "series_id": "echo30", "episode": episode, "traits": traits,
            "rule": "apply before render only; never rewrite a published episode",
        })
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "directives": directives,
    }
    _atomic_json(DIRECTIVES_PATH, payload)
    return payload
