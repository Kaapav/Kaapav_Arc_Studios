"""Fail-closed timed publication for previously published YouTube videos.

YouTube does not accept ``status.publishAt`` for a video that has already been
public. This queue preserves the existing video ID and changes it from private
to public only inside the due-time window, after re-hashing the audited package.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ROOT
from . import platform_control


QUEUE_PATH = ROOT / "analytics" / "youtube_timed_release_queue.json"
LEDGER_PATH = ROOT / "analytics" / "youtube_timed_release_ledger.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def _checkpoint(key: str, **updates: Any) -> dict[str, Any]:
    queue = _read(QUEUE_PATH, {"schema_version": 1, "items": []})
    for item in queue.get("items") or []:
        if item.get("key") == key:
            item.update(updates)
            item["updated_at"] = _stamp()
            queue["updated_at"] = _stamp()
            _write(QUEUE_PATH, queue)
            return item
    raise RuntimeError(f"YouTube timed-release item disappeared: {key}")


def enqueue(item: dict[str, Any]) -> bool:
    """Add an item to the YT timed-release queue. Returns True if added, False if already present."""
    queue = _read(QUEUE_PATH, {"schema_version": 1, "items": []})
    items = queue.get("items") or []
    key = item.get("key")
    episode = item.get("episode")
    if any(i.get("key") == key or i.get("episode") == episode for i in items):
        return False
    items.append(item)
    queue["items"] = items
    queue["updated_at"] = _stamp()
    _write(QUEUE_PATH, queue)
    return True


def summary() -> dict[str, Any]:
    items = _read(QUEUE_PATH, {"items": []}).get("items") or []
    pending = [item for item in items if item.get("status") not in {"published", "held_missed_slot"}]
    return {
        "queued": len(pending),
        "published": sum(item.get("status") == "published" for item in items),
        "failures": sum(item.get("status") in {"retry_wait", "held_missed_slot"} for item in items),
        "next_publish_at": pending[0].get("publish_at") if pending else None,
    }


def process_due(cfg, *, now: datetime | None = None, limit: int = 2) -> dict[str, Any]:
    current = (now or _now()).astimezone(timezone.utc)
    result: dict[str, Any] = {"status": "ready", "published": [], "failed": [], "held": []}
    pause = ROOT / str(cfg.get("autopilot", "emergency_pause_file", default="analytics/PAUSE_AUTOPILOT"))
    if pause.exists():
        result.update({"status": "master_gate_closed", "detail": "Global automation is paused"})
        return result
    if not platform_control.enabled("youtube"):
        result["status"] = "platform_disabled"
        return result

    queue = _read(QUEUE_PATH, {"schema_version": 1, "items": []})
    grace = timedelta(minutes=int(cfg.get("meta", "late_publish_grace_minutes", default=30)))
    processed = 0
    for raw in queue.get("items") or []:
        if processed >= max(0, limit):
            break
        if raw.get("status") in {"published", "held_missed_slot"}:
            continue
        due = _parse(raw.get("publish_at"))
        retry_at = _parse(raw.get("retry_at"))
        if due is None or current < due or (retry_at and current < retry_at):
            continue
        processed += 1
        key = str(raw.get("key") or "")
        if current > due + grace:
            _checkpoint(key, status="held_missed_slot", error="publish window expired; no blind late release")
            result["held"].append(key)
            continue
        try:
            from .release_audit import assert_persisted_release_evidence
            from .upload import _get_service, build_upload_body, verify_upload_target

            video = Path(str(raw["video_path"]))
            metadata_path = Path(str(raw["metadata_path"]))
            audit_path = Path(str(raw["audit_path"]))
            metadata = _read(metadata_path, {})
            assert_persisted_release_evidence(
                video, metadata, audit_path, expected_audit_id=str(raw.get("audit_id") or ""),
            )
            service = _get_service(cfg, verify_channel=False)
            channel = verify_upload_target(cfg, service)
            body, _, _ = build_upload_body(cfg, metadata, privacy_override="private")
            body["id"] = str(raw["youtube_id"])
            body["status"]["privacyStatus"] = "public"
            _checkpoint(key, status="youtube_publishing", attempts=int(raw.get("attempts") or 0) + 1)
            service.videos().update(part="snippet,status", body=body).execute()
            verified = service.videos().list(part="snippet,status", id=str(raw["youtube_id"])).execute().get("items", [])
            if not verified or verified[0].get("status", {}).get("privacyStatus") != "public":
                raise RuntimeError("YouTube did not confirm public privacy state")
            snippet = verified[0].get("snippet") or {}
            expected = body.get("snippet") or {}
            if snippet.get("title") != expected.get("title") or snippet.get("description") != expected.get("description"):
                raise RuntimeError("YouTube remote metadata contract mismatch")
            from .youtube_playlists import route_release
            playlist = route_release(service, metadata, str(raw["youtube_id"]))
            published = _checkpoint(
                key, status="published", published_at=_stamp(), channel_id=channel.get("id"),
                playlist=playlist, error=None,
            )
            ledger = _read(LEDGER_PATH, {"schema_version": 1, "releases": []})
            ledger.setdefault("releases", []).append(dict(published))
            ledger["updated_at"] = _stamp()
            _write(LEDGER_PATH, ledger)
            result["published"].append({"key": key, "youtube_id": raw["youtube_id"]})
        except Exception as exc:
            attempts = max(1, int(raw.get("attempts") or 0) + 1)
            retry = current + timedelta(minutes=min(15, 2 ** min(attempts, 4)))
            status = "retry_wait" if retry <= due + grace else "held_missed_slot"
            _checkpoint(
                key, status=status, attempts=attempts, retry_at=_stamp(retry),
                error_type=type(exc).__name__, error=str(exc)[:500],
            )
            result["failed"].append({"key": key, "error_type": type(exc).__name__, "error": str(exc)[:300]})
    if result["failed"]:
        result["status"] = "recovery_required"
    # Fortress: retry playlist routing for already-published items whose routing
    # failed earlier (idempotent route_release). Never leaves a live video unrouted.
    playlist_retried = 0
    playlist_recovered = 0
    if processed >= 0:
        for raw in queue.get("items") or []:
            pl = raw.get("playlist") or {}
            if raw.get("status") != "published" or pl.get("status") != "recovery_required":
                continue
            playlist_retried += 1
            try:
                from .upload import _get_service
                from .youtube_playlists import route_release
                service = _get_service(cfg, verify_channel=False)
                metadata_path = Path(str(raw.get("metadata_path") or ""))
                metadata = _read(metadata_path, {})
                playlist = route_release(service, metadata, str(raw.get("youtube_id") or ""))
                _checkpoint(
                    str(raw.get("key") or ""), status=raw.get("status"), published_at=raw.get("published_at"),
                    playlist=playlist,
                )
                if playlist.get("status") == "routed":
                    playlist_recovered += 1
            except Exception:
                continue
    result["playlist_retried"] = playlist_retried
    result["playlist_recovered"] = playlist_recovered
    result["checked_at"] = _stamp()
    return result
