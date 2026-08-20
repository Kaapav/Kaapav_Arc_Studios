"""Evergreen rolling original-series factory coordinator.

Whenever only the configured reserve of unreleased series remains, the factory
queues a complete successor batch. It produces evidence briefs and machine
tasks for the creative worker, then validates every returned 30-episode package
before image work. It never fills a schedule with an unvalidated template.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .config import ROOT
from .title_policy import POLICY as TITLE_POLICY, validate_episode_title


STATE_PATH = ROOT / "analytics" / "story_factory.json"
QUEUE_PATH = ROOT / "analytics" / "creative_queue.json"
PLAN_PATH = ROOT / "content" / "studio_master_release_plan.json"
GENERIC_PHRASES = (
    "chosen one", "ancient prophecy", "powers suddenly awaken",
    "it was all a dream", "mysterious hooded figure",
)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _released_series(inventory: dict[str, Any], planned_series: int) -> list[int]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in inventory.get("episodes") or []:
        sequence = int(item.get("sequence") or 0)
        if 1 <= sequence <= planned_series:
            grouped.setdefault(sequence, []).append(item)
    return [
        sequence for sequence, items in grouped.items()
        if len(items) == 30 and all(item.get("state") == "public" for item in items)
    ]


def _evidence_brief() -> dict[str, Any]:
    learning = _read(ROOT / "analytics" / "growth_learning.json")
    recommendations = _read(ROOT / "analytics" / "learning_recommendations.json")
    platform_learning = _read(ROOT / "analytics" / "platform_learning.json")
    platform_recommendations = _read(ROOT / "analytics" / "platform_recommendations.json")
    meaningful = [item for item in learning.get("observations", []) if item.get("meaningful")]
    best = sorted(meaningful, key=lambda item: float(item.get("score") or 0), reverse=True)[:10]
    platform_evidence = {}
    for platform, data in (platform_learning.get("platforms") or {}).items():
        observations = data.get("observations") or []
        diagnoses = sorted({str(item.get("diagnosis") or "unknown") for item in observations})
        platform_evidence[platform] = {
            "meaningful_observations": sum(bool(item.get("meaningful")) for item in observations),
            "diagnoses": {
                diagnosis: sum(item.get("diagnosis") == diagnosis for item in observations)
                for diagnosis in diagnoses
            },
            "recommendations": ((platform_recommendations.get("platforms") or {}).get(platform) or {}),
        }
    return {
        "organic_baseline_views": learning.get("organic_baseline_views", 0),
        "meaningful_observations": len(meaningful),
        "winning_traits": recommendations.get("recommendations", {}),
        "best_observations": [
            {
                "series_id": item.get("series_id"), "episode": item.get("episode"),
                "score": item.get("score"), "traits": item.get("traits"),
                "diagnosis": item.get("diagnosis"),
            }
            for item in best
        ],
        "platform_evidence": platform_evidence,
        "cross_platform_rule": platform_recommendations.get(
            "cross_platform_rule",
            "Adopt globally only when independent meaningful evidence agrees; otherwise preserve controlled exploration.",
        ),
        "constraint": "Use evidence as direction, never copy a prior plot, title, character, or visual identity.",
    }


def reconcile(cfg, inventory: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(cfg.get("autopilot", "evergreen_story_factory", default=True))
    plan = _read(PLAN_PATH)
    initial_count = int(cfg.get("autopilot", "initial_series_count", default=10))
    reserve = int(cfg.get("autopilot", "evergreen_refill_remaining_series", default=2))
    batch_size = int(cfg.get("autopilot", "evergreen_series_batch_size", default=10))
    planned_count = len(plan.get("series") or [])
    released = _released_series(inventory, planned_count)
    remaining = max(0, planned_count - len(released))
    queue = _read(QUEUE_PATH) or {"schema_version": 1, "tasks": []}
    tasks = queue.setdefault("tasks", [])
    pending = [task for task in tasks if task.get("action") == "design_original_series" and task.get("state") in {"queued", "in_progress"}]
    previous = _read(STATE_PATH)
    already_triggered_for = int(previous.get("last_refill_planned_count") or 0) == planned_count
    created: list[dict[str, Any]] = []
    if enabled and planned_count >= initial_count and remaining <= reserve and not pending and not already_triggered_for:
        evidence = _evidence_brief()
        batch_id = f"successor-slate-{planned_count + 1:03d}-{planned_count + batch_size:03d}"
        for next_sequence in range(planned_count + 1, planned_count + batch_size + 1):
            task = {
                "task_id": f"create-series-{next_sequence:03d}",
                "batch_id": batch_id,
                "action": "design_original_series",
                "state": "queued",
                "created_at": _now(),
                "series_sequence": next_sequence,
                "episodes_required": 30,
                "deliverables": [
                    "original title and premise", "SERIES_BIBLE.md", "series.json",
                    "thirty causal episode manifests", "character and location specifications",
                    "turnaround generation plan", "anti-slop self-audit",
                ],
                "evidence_brief": evidence,
                "hard_rules": [
                    "original premium cute cinematic 3D language; no named-studio imitation",
                    "be distinct from every earlier series and every title in this successor batch",
                    "every episode changes a relationship or permanent story state",
                    f"episode title policy: {TITLE_POLICY}",
                    "no story images before locked multi-angle character turnarounds",
                    "no generic prophecy, random power upgrade, repeated frame, or filler episode",
                    "thirty connected episodes with a resolved season arc and expansion door",
                ],
            }
            tasks.append(task)
            created.append(task)
        queue["updated_at"] = _now()
        _write(QUEUE_PATH, queue)
    state = {
        "schema_version": 1,
        "updated_at": _now(),
        "enabled": enabled,
        "normal_manual_actions": 0,
        "initial_series_count": initial_count,
        "planned_series_count": planned_count,
        "released_series_count": len(released),
        "remaining_unreleased_series": remaining,
        "refill_threshold": reserve,
        "refill_batch_size": batch_size,
        "rolling_refill": True,
        "last_refill_planned_count": planned_count if created else previous.get("last_refill_planned_count"),
        "next_action": (
            "successor_batch_queued" if created else
            "creative_tasks_in_progress" if pending else
            "continue_current_slate"
        ),
        "active_task_id": (created[0] if created else pending[0] if pending else {}).get("task_id"),
        "created_task_ids": [task["task_id"] for task in created],
    }
    _write(STATE_PATH, state)
    return state


def validate_candidate_series(series_root: Path, existing_titles: list[str] | None = None) -> dict[str, Any]:
    """Strict blueprint gate before turnarounds or story-image generation."""
    series_root = Path(series_root)
    failures: list[str] = []
    bible = series_root / "SERIES_BIBLE.md"
    series_path = series_root / "series.json"
    if not bible.exists() or len(bible.read_text(encoding="utf-8")) < 1500:
        failures.append("series bible is missing or too thin")
    series = _read(series_path)
    title = str(series.get("title") or series.get("public_title") or "").strip()
    if not title:
        failures.append("series title is missing")
    for existing in existing_titles or []:
        if SequenceMatcher(None, title.lower(), existing.lower()).ratio() >= 0.82:
            failures.append(f"series title is too similar to existing title: {existing}")
    episode_paths = sorted(series_root.glob("episodes/ep*/episode.json"))
    if not episode_paths:
        episode_paths = sorted(series_root.glob("episode*/episode.json"))
    if len(episode_paths) != 30:
        failures.append(f"expected 30 episode manifests, found {len(episode_paths)}")
    titles: set[str] = set()
    changes: set[str] = set()
    for index, path in enumerate(episode_paths, 1):
        episode = _read(path)
        episode_title = str(episode.get("title") or "").strip()
        change = str(episode.get("permanent_story_change") or "").strip()
        scenes = episode.get("scenes") or []
        combined = f"{episode_title} {episode.get('description', '')} {change}".lower()
        if int(episode.get("episode") or 0) != index:
            failures.append(f"episode numbering mismatch at {path}")
        if not episode_title or episode_title.lower() in titles:
            failures.append(f"missing or repeated episode title at episode {index}")
        for issue in validate_episode_title(episode_title):
            failures.append(f"episode {index} title: {issue}")
        titles.add(episode_title.lower())
        if len(change) < 20 or change.lower() in changes:
            failures.append(f"missing or repeated permanent story change at episode {index}")
        changes.add(change.lower())
        if not 6 <= len(scenes) <= 10:
            failures.append(f"episode {index} must have 6-10 distinct scenes")
        intentions = {
            re.sub(r"\s+", " ", str(scene.get("image_prompt") or "")).strip().lower()
            for scene in scenes
        }
        if "" in intentions or len(intentions) != len(scenes):
            failures.append(f"episode {index} has missing or repeated visual intentions")
        if any(not str(scene.get("text") or "").strip() for scene in scenes):
            failures.append(f"episode {index} has empty narration")
        if any(phrase in combined for phrase in GENERIC_PHRASES):
            failures.append(f"episode {index} contains a blocked generic device")
    return {
        "schema_version": 1,
        "checked_at": _now(),
        "series_root": str(series_root),
        "title": title,
        "episode_count": len(episode_paths),
        "status": "passed" if not failures else "blocked",
        "failures": failures,
    }
