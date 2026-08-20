"""Evidence-only Facebook and Instagram performance collection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT
from .meta_platform import LEDGER_PATH, MetaClient, _read, _write, health_check


CURRENT_PATH = ROOT / "analytics" / "meta_analytics.json"
HISTORY_PATH = ROOT / "analytics" / "meta_analytics_history.json"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary_total(value: Any) -> int:
    try:
        return int(((value or {}).get("summary") or {}).get("total_count") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _insight_value(payload: dict[str, Any]) -> Any:
    rows = payload.get("data") or []
    if not rows:
        return None
    row = rows[0]
    values = row.get("values") or []
    if values:
        return values[-1].get("value")
    return row.get("value") or row.get("total_value", {}).get("value")


def _instagram_row(client: MetaClient, token: str, entry: dict[str, Any]) -> dict[str, Any]:
    media_id = str(entry.get("remote_id") or "")
    basic = client.request("GET", f"/{media_id}", token=token, params={
        "fields": "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count",
    })
    metrics: dict[str, Any] = {}
    unavailable: list[str] = []
    for metric in (
        "views", "reach", "plays", "shares", "saved", "total_interactions",
        "ig_reels_avg_watch_time", "ig_reels_video_view_total_time", "follows",
    ):
        try:
            metrics[metric] = _insight_value(client.request(
                "GET", f"/{media_id}/insights", token=token, params={"metric": metric}, attempts=2,
            ))
        except Exception:
            unavailable.append(metric)
    return {
        "platform": "instagram", "media_id": media_id,
        "series_id": entry.get("series_id"), "episode": entry.get("episode"),
        "release_kind": entry.get("release_kind"), "published_at": basic.get("timestamp") or entry.get("published_at"),
        "url": basic.get("permalink") or entry.get("url"), "caption": basic.get("caption"),
        "views": metrics.get("views") if metrics.get("views") is not None else metrics.get("plays"),
        "reach": metrics.get("reach"), "likes": int(basic.get("like_count") or 0),
        "comments": int(basic.get("comments_count") or 0), "shares": metrics.get("shares"),
        "saves": metrics.get("saved"), "total_interactions": metrics.get("total_interactions"),
        "average_watch_time_ms": metrics.get("ig_reels_avg_watch_time"),
        "total_watch_time_ms": metrics.get("ig_reels_video_view_total_time"),
        "follows": metrics.get("follows"), "unavailable_metrics": unavailable,
    }


def _facebook_row(client: MetaClient, token: str, entry: dict[str, Any]) -> dict[str, Any]:
    video_id = str(entry.get("remote_id") or "")
    try:
        basic = client.request("GET", f"/{video_id}", token=token, params={
            "fields": "id,created_time,permalink_url,title,description,views,comments.limit(0).summary(true),likes.limit(0).summary(true)",
        })
    except Exception:
        basic = client.request("GET", f"/{video_id}", token=token, params={
            "fields": "id,created_time,permalink_url,title,description,comments.limit(0).summary(true),likes.limit(0).summary(true)",
        })
    metrics: dict[str, Any] = {}
    unavailable: list[str] = []
    for metric in ("total_video_views", "total_video_view_time", "total_video_complete_views"):
        try:
            metrics[metric] = _insight_value(client.request(
                "GET", f"/{video_id}/video_insights", token=token, params={"metric": metric}, attempts=2,
            ))
        except Exception:
            unavailable.append(metric)
    return {
        "platform": "facebook", "media_id": video_id,
        "series_id": entry.get("series_id"), "episode": entry.get("episode"),
        "release_kind": entry.get("release_kind"), "published_at": basic.get("created_time") or entry.get("published_at"),
        "url": basic.get("permalink_url") or entry.get("url"), "title": basic.get("title"),
        "views": basic.get("views") if basic.get("views") is not None else metrics.get("total_video_views"),
        "likes": _summary_total(basic.get("likes")), "comments": _summary_total(basic.get("comments")),
        "total_watch_time_ms": metrics.get("total_video_view_time"),
        "complete_views": metrics.get("total_video_complete_views"),
        "unavailable_metrics": unavailable,
    }


def collect(cfg) -> dict[str, Any]:
    checked = _stamp()
    health = health_check(cfg)
    platform_health = health.get("platforms") or {}
    ready_platforms = {
        name for name in ("facebook", "instagram")
        if (platform_health.get(name) or {}).get("status") == "ready"
    }
    if not ready_platforms:
        payload = {
            "schema_version": 1, "status": "unavailable", "checked_at": checked,
            "detail": health.get("detail"), "platforms": {}, "media": [],
        }
        _write(CURRENT_PATH, payload)
        return payload
    client = MetaClient(cfg)
    account = client.discover()
    token = account["page_token"]
    ledger = _read(LEDGER_PATH, {"releases": []})
    rows = []
    failures = []
    for entry in ledger.get("releases") or []:
        if entry.get("platform") not in ready_platforms or entry.get("status") != "published" or not entry.get("remote_id"):
            continue
        try:
            row = _instagram_row(client, token, entry) if entry.get("platform") == "instagram" else _facebook_row(client, token, entry)
            row["snapshot_at"] = checked
            rows.append(row)
        except Exception as exc:
            failures.append({
                "platform": entry.get("platform"), "remote_id": entry.get("remote_id"),
                "error_type": type(exc).__name__, "error": str(exc)[:300],
            })
    platforms = {}
    for name in ("facebook", "instagram"):
        relevant = [row for row in rows if row.get("platform") == name]
        platforms[name] = {
            "status": (
                "not_connected" if name not in ready_platforms
                else "ok" if not any(item.get("platform") == name for item in failures)
                else "partial"
            ),
            "tracked_media": len(relevant),
            "views": sum(int(row.get("views") or 0) for row in relevant),
            "likes": sum(int(row.get("likes") or 0) for row in relevant),
            "comments": sum(int(row.get("comments") or 0) for row in relevant),
            "shares": sum(int(row.get("shares") or 0) for row in relevant),
        }
    payload = {
        "schema_version": 1, "status": "ok" if not failures else "partial",
        "checked_at": checked, "platforms": platforms, "media": rows,
        "failures": failures,
        "truth_boundary": "Only metrics returned by Meta are stored; unavailable metrics remain null.",
    }
    _write(CURRENT_PATH, payload)
    history = _read(HISTORY_PATH, {"schema_version": 1, "snapshots": []})
    snapshots = history.setdefault("snapshots", [])
    snapshots.append({"snapshot_at": checked, "platforms": platforms, "media": rows})
    history["snapshots"] = snapshots[-400:]
    history["updated_at"] = checked
    _write(HISTORY_PATH, history)
    return payload
