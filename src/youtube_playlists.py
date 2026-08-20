"""Idempotent YouTube series-playlist routing with persistent recovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


STATE_PATH = ROOT / "analytics" / "youtube_playlist_state.json"
PLAN_PATH = ROOT / "content" / "studio_master_release_plan.json"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def _write(value: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def _series(series_id: str) -> dict[str, Any] | None:
    plan = _read(PLAN_PATH, {})
    return next((item for item in plan.get("series", []) if str(item.get("slug")) == series_id), None)


def _playlist(service, series: dict[str, Any], known_id: str | None) -> str:
    if known_id:
        found = service.playlists().list(part="id", id=known_id, maxResults=1).execute().get("items", [])
        if found:
            return known_id
    title = f"{series['public_title']} — Complete Animated Series"
    token = None
    while True:
        response = service.playlists().list(
            part="snippet,status", mine=True, maxResults=50, pageToken=token
        ).execute()
        match = next((item for item in response.get("items", []) if item.get("snippet", {}).get("title") == title), None)
        if match:
            return str(match["id"])
        token = response.get("nextPageToken")
        if not token:
            break
    created = service.playlists().insert(part="snippet,status", body={
        "snippet": {
            "title": title,
            "description": (
                f"Watch {series['public_title']} in story order. Original {series.get('genre', 'animated')} "
                "episodes and complete arcs from KAAPAV ARC Studios."
            ),
        },
        "status": {"privacyStatus": "public"},
    }).execute()
    return str(created["id"])


def route_release(service, metadata: dict[str, Any], video_id: str) -> dict[str, Any]:
    series_id = str(metadata.get("series_id") or "").strip()
    series = _series(series_id)
    if not series or not video_id:
        return {"status": "skipped", "reason": "series identity unavailable"}
    state = _read(STATE_PATH, {"schema_version": 1, "series": {}, "pending": []})
    key = f"{series_id}:{video_id}"
    try:
        playlist_id = _playlist(service, series, (state.get("series") or {}).get(series_id))
        exists = service.playlistItems().list(
            part="id", playlistId=playlist_id, videoId=video_id, maxResults=1
        ).execute().get("items", [])
        if not exists:
            service.playlistItems().insert(part="snippet", body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            }).execute()
        state.setdefault("series", {})[series_id] = playlist_id
        state["pending"] = [item for item in state.get("pending", []) if item.get("key") != key]
        result = {"status": "routed", "series_id": series_id, "playlist_id": playlist_id, "video_id": video_id}
    except Exception as exc:
        pending = [item for item in state.get("pending", []) if item.get("key") != key]
        pending.append({"key": key, "series_id": series_id, "video_id": video_id,
                        "metadata": {"series_id": series_id}, "error_type": type(exc).__name__,
                        "error": str(exc)[:300], "updated_at": _stamp()})
        state["pending"] = pending
        result = {"status": "recovery_required", "series_id": series_id, "error_type": type(exc).__name__}
    state["updated_at"] = _stamp()
    _write(state)
    return result


def reconcile(service) -> dict[str, Any]:
    state = _read(STATE_PATH, {"pending": []})
    results = [route_release(service, item.get("metadata") or {}, str(item.get("video_id") or ""))
               for item in list(state.get("pending") or [])]
    return {"retried": len(results), "recovered": sum(item.get("status") == "routed" for item in results)}
