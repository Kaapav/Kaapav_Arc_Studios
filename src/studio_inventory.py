"""Authoritative production inventory and two-week buffer planning."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


STATE_PATH = ROOT / "analytics" / "studio_inventory.json"
QUEUE_PATH = ROOT / "analytics" / "production_queue.json"
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


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


def _manifest_path(content_root: Path, episode: int) -> Path | None:
    candidates = [
        content_root / f"episode{episode}" / "episode.json",
        content_root / f"episode{episode:02d}" / "episode.json",
        content_root / "manual_production" / "episodes" / f"ep{episode:03d}" / "episode.json",
        content_root / "episodes" / f"ep{episode:03d}" / "episode.json",
    ]
    return next((path for path in candidates if path.exists()), None)


def _registry_for(manifest_path: Path) -> Path | None:
    for parent in (manifest_path.parent, *manifest_path.parents):
        candidate = parent / "characters" / "character_registry.json"
        if candidate.exists():
            return candidate
        if parent == ROOT:
            break
    return None


def _output_root(manifest: dict[str, Any]) -> Path:
    return ROOT / "output" / "story" / str(manifest.get("output_slug") or "missing-output-slug")


def _release_state(metadata: dict[str, Any], upload_result: dict[str, Any]) -> str | None:
    status = str(metadata.get("status") or "").lower()
    privacy = str(upload_result.get("privacy") or "").lower()
    publish_at = metadata.get("publish_at") or upload_result.get("publish_at")
    if status == "public" or privacy == "public":
        return "public"
    if status == "scheduled" or publish_at:
        return "scheduled"
    if metadata.get("uploaded") or upload_result.get("id"):
        return "private_uploaded"
    return None


def _remote_release_index() -> dict[tuple[str, int], dict[str, Any]]:
    path = ROOT / "analytics" / "current.csv"
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    result = {}
    for row in rows:
        series_id = str(row.get("series_id") or "")
        try:
            episode = int(row.get("episode") or 0)
        except ValueError:
            episode = 0
        if not series_id or not episode:
            match = re.search(r"(?i)\bECHO//30\s+Ep\.?\s*(\d{1,2})\b", str(row.get("title") or ""))
            if match:
                series_id, episode = "echo30", int(match.group(1))
        if not series_id or not episode:
            continue
        privacy = str(row.get("privacy") or "")
        remote_publish = str(row.get("remote_publish_at") or "")
        if privacy == "public":
            state = "public"
            publish_at = str(row.get("published_at") or "")
        elif privacy == "private" and remote_publish:
            state = "scheduled"
            publish_at = remote_publish
        else:
            continue
        result[(series_id, episode)] = {
            "state": state, "publish_at": publish_at,
            "youtube_id": row.get("video_id"), "youtube_url": row.get("url"),
        }
    return result


def inspect_episode(series: dict[str, Any], episode: int,
                    remote_index: dict[tuple[str, int], dict[str, Any]] | None = None) -> dict[str, Any]:
    root = ROOT / str(series.get("content_root") or "")
    manifest_path = _manifest_path(root, episode)
    base = {
        "sequence": series.get("sequence"), "series_id": series.get("slug"),
        "series_title": series.get("public_title"), "episode": episode,
        "manifest_path": str(manifest_path) if manifest_path else None,
    }
    if manifest_path is None:
        return {**base, "state": "manifest_missing", "blocker": "episode manifest missing"}
    manifest = _read(manifest_path)
    scenes = manifest.get("scenes") or []
    expected_paths = [manifest_path.parent / str(scene.get("image") or "") for scene in scenes]
    present = [path for path in expected_paths if path.exists() and path.stat().st_size >= 5_000]
    registry_path = _registry_for(manifest_path)
    registry = _read(registry_path) if registry_path else {}
    identities_locked = bool(
        registry_path and registry.get("locked") and not registry.get("pending_before_first_appearance")
        and all(entry.get("status") == "locked" for entry in registry.get("locked", []))
    )
    qc_path = manifest_path.parent / "image_qc.json"
    image_qc = _read(qc_path)
    expected_rel = {str(Path(scene.get("image") or "")).replace("\\", "/") for scene in scenes}
    accepted_rel = {str(value).replace("\\", "/") for value in image_qc.get("accepted_frames", [])}
    images_accepted = bool(
        scenes and len(present) == len(expected_paths)
        and image_qc.get("status") == "accepted" and accepted_rel == expected_rel
    )
    output = _output_root(manifest)
    video = output / "video.mp4"
    thumbnail = output / "thumbnail.jpg"
    qc_report = _read(output / "qc_report.json")
    audit = _read(output / "prepublish_audit.json")
    metadata = _read(output / "metadata.json")
    upload_result = _read(output / "upload_result.json")
    release = _release_state(metadata, upload_result)
    remote_release = (remote_index or {}).get((str(series.get("slug") or ""), episode))
    if remote_release:
        state, blocker = remote_release["state"], None
    elif release:
        state, blocker = release, None
    elif audit.get("status") == "passed":
        state, blocker = "strict_audit_passed", None
    elif video.exists() and thumbnail.exists() and qc_report.get("ok"):
        state, blocker = "strict_audit_pending", "fresh strict publish audit required"
    elif video.exists():
        state, blocker = "technical_qc_pending", "technical media QC incomplete"
    elif images_accepted:
        state, blocker = "render_ready", None
    elif len(present) == len(expected_paths) and scenes:
        state, blocker = "image_qc_pending", "visual inspection acceptance missing"
    elif identities_locked:
        state, blocker = "images_pending", f"{len(expected_paths) - len(present)} story frames missing"
    else:
        state, blocker = "identities_pending", "locked character registry incomplete"
    return {
        **base,
        "episode_id": manifest.get("episode_id"),
        "output_slug": manifest.get("output_slug"),
        "state": state,
        "blocker": blocker,
        "character_registry": str(registry_path) if registry_path else None,
        "identities_locked": identities_locked,
        "scene_count": len(scenes),
        "frames_present": len(present),
        "images_accepted": images_accepted,
        "output_root": str(output),
        "video_path": str(video),
        "publish_at": (remote_release or {}).get("publish_at") or metadata.get("publish_at") or upload_result.get("publish_at"),
        "remote_publish_at": (remote_release or {}).get("publish_at"),
        "youtube_id": (remote_release or {}).get("youtube_id") or metadata.get("youtube_id") or upload_result.get("id"),
        "youtube_url": (remote_release or {}).get("youtube_url") or metadata.get("youtube_url") or upload_result.get("url"),
        "audit_id": audit.get("audit_id"),
    }


def _task_id(item: dict[str, Any], action: str) -> str:
    raw = f"{item['series_id']}:{item['episode']}:{action}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def refresh_inventory(cfg) -> dict[str, Any]:
    plan = _read(ROOT / "content" / "studio_master_release_plan.json")
    remote_index = _remote_release_index()
    count = int(plan.get("release_policy", {}).get("provisional_episode_count_per_series") or 30)
    episodes = [
        inspect_episode(series, episode, remote_index)
        for series in sorted(plan.get("series", []), key=lambda item: int(item.get("sequence") or 0))
        for episode in range(1, count + 1)
    ]
    policy_start = int(cfg.get("autopilot", "policy_applies_from_episode", default=11))
    target = int(cfg.get("autopilot", "ready_short_target", default=7))
    active_sequence = next(
        (
            sequence for sequence in sorted({int(item["sequence"]) for item in episodes})
            if any(item["sequence"] == sequence and item["state"] not in {"public", "scheduled"} for item in episodes)
        ),
        1,
    )
    active = [item for item in episodes if int(item["sequence"]) == active_sequence]
    if active_sequence == 1:
        active = [item for item in active if int(item["episode"]) >= policy_start]
    forward = [item for item in active if item["state"] != "public"]
    ready_states = {"scheduled", "private_uploaded", "strict_audit_passed"}
    ready = [item for item in forward if item["state"] in ready_states][:target]
    shortage = max(0, target - len(ready))
    task_map = {
        "identities_pending": "lock_character_turnarounds",
        "images_pending": "generate_story_frames",
        "image_qc_pending": "visual_qc",
        "render_ready": "render",
        "technical_qc_pending": "repair_render",
        "strict_audit_pending": "strict_audit",
        "strict_audit_passed": "schedule",
        "private_uploaded": "schedule",
    }
    tasks = []
    for priority, item in enumerate(forward[: max(target + 3, 10)], 1):
        action = task_map.get(item["state"])
        if action:
            tasks.append({
                "task_id": _task_id(item, action), "priority": priority, "action": action,
                "series_id": item["series_id"], "episode": item["episode"],
                "manifest_path": item["manifest_path"], "state": "queued",
                "blocker": item.get("blocker"),
            })
    payload = {
        "schema_version": 2,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "target_days": int(cfg.get("autopilot", "ready_inventory_days", default=14)),
        "target_ready_shorts": target,
        "active_series_sequence": active_sequence,
        "ready_or_scheduled_count": len(ready),
        "shortage": shortage,
        "fail_closed": True,
        "episodes": episodes,
    }
    _write(STATE_PATH, payload)
    _write(QUEUE_PATH, {
        "schema_version": 1, "updated_at": payload["updated_at"],
        "inventory_shortage": shortage, "tasks": tasks,
    })
    return payload


def next_short_slots(existing_publish_at: list[str], count: int, cfg) -> list[str]:
    interval = int(cfg.get("autopilot", "short_interval_days", default=2))
    start_episode = int(cfg.get("autopilot", "policy_applies_from_episode", default=11))
    parsed = []
    for raw in existing_publish_at:
        try:
            parsed.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(IST))
        except ValueError:
            continue
    if parsed:
        cursor = max(parsed) + timedelta(days=interval)
    else:
        cursor = datetime.now(IST) + timedelta(days=1)
    cursor = cursor.replace(hour=10, minute=0, second=0, microsecond=0)
    time_ist = str(cfg.get("autopilot", "short_time_ist", default="10:00"))
    try:
        parsed_time = datetime.strptime(time_ist, "%H:%M")
        cursor = cursor.replace(hour=parsed_time.hour, minute=parsed_time.minute)
    except ValueError:
        cursor = cursor.replace(hour=10, minute=0)
    minimum = datetime.now(IST) + timedelta(minutes=int(cfg.get("autopilot", "minimum_publish_lead_minutes", default=60)))
    while cursor < minimum:
        cursor += timedelta(days=interval)
    return [
        (cursor + timedelta(days=index * interval)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for index in range(count)
    ]


def next_compilation_slot(after_publish_at: str, cfg, busy_dates: set[str] | None = None) -> str:
    after = datetime.fromisoformat(after_publish_at.replace("Z", "+00:00")).astimezone(IST)
    cursor = (after + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    busy = set()
    for d in busy_dates or []:
        if isinstance(d, datetime):
            busy.add(d.isoformat()[:10])
        else:
            try:
                busy.add(datetime.fromisoformat(str(d).replace("Z", "+00:00")).isoformat()[:10])
            except ValueError:
                continue
    while cursor.weekday() not in {5, 6} or cursor.isoformat()[:10] in busy:
        cursor += timedelta(days=1)
    return cursor.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
