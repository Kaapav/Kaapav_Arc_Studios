"""Optional retention/engagement metrics from the YouTube Analytics API.

The existing upload OAuth token does not necessarily include Analytics scope.
When it does not, this collector records the limitation and falls back cleanly
to Data API observations; uploads must never be broken by analytics access.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import ROOT


ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
OUTPUT = ROOT / "analytics" / "youtube_analytics.json"
METRICS = (
    "views,engagedViews,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,likes,comments,shares,subscribersGained,subscribersLost"
)


def _write(value: dict[str, Any]) -> dict[str, Any]:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(OUTPUT)
    return value


def _published_date(raw: str) -> str:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except (ValueError, AttributeError):
        return (date.today() - timedelta(days=28)).isoformat()


def _query_video(service, video_id: str, start_date: str, end_date: str) -> dict[str, Any]:
    request = service.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics=METRICS,
        dimensions="video",
        filters=f"video=={video_id}",
        maxResults=1,
    )
    result = request.execute()
    headers = [item.get("name") for item in result.get("columnHeaders", [])]
    values = (result.get("rows") or [[video_id] + [0] * (len(headers) - 1)])[0]
    return {str(name): value for name, value in zip(headers, values)}


def _query_retention(service, video_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Return YouTube's real retention curve; never interpolate missing data."""
    result = service.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics="audienceWatchRatio,relativeRetentionPerformance",
        dimensions="elapsedVideoTimeRatio",
        filters=f"video=={video_id}",
        sort="elapsedVideoTimeRatio",
    ).execute()
    headers = [str(item.get("name")) for item in result.get("columnHeaders", [])]
    return [dict(zip(headers, values)) for values in (result.get("rows") or [])]


def _query_traffic_sources(service, video_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    result = service.reports().query(
        ids="channel==MINE", startDate=start_date, endDate=end_date,
        metrics="views,engagedViews,estimatedMinutesWatched",
        dimensions="insightTrafficSourceType", filters=f"video=={video_id}", sort="-views",
    ).execute()
    headers = [str(item.get("name")) for item in result.get("columnHeaders", [])]
    return [dict(zip(headers, values)) for values in (result.get("rows") or [])]


def collect(cfg, rows: list[dict[str, Any]]) -> dict[str, Any]:
    token_path = ROOT / cfg.yt_token
    base = {
        "schema_version": 1,
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": ANALYTICS_SCOPE,
        "videos": {},
    }
    if not token_path.exists():
        base.update({
            "status": "token_missing", "detail": "Data API metrics remain active",
            "resolution": "Run authorize_youtube_analytics.py once",
        })
        return _write(base)
    credentials = Credentials.from_authorized_user_file(str(token_path))
    if not credentials.has_scopes([ANALYTICS_SCOPE]):
        base.update({
            "status": "analytics_scope_missing",
            "detail": "Retention metrics unavailable; using public views and engagement without inventing reach causes",
            "resolution": "Run authorize_youtube_analytics.py once; Google requires owner consent for this scope",
        })
        return _write(base)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    service = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
    end_date = date.today().isoformat()
    errors = []
    for row in rows:
        if str(row.get("privacy")) != "public":
            continue
        video_id = str(row.get("video_id") or "")
        if not video_id:
            continue
        try:
            start_date = _published_date(str(row.get("published_at") or ""))
            metrics = _query_video(service, video_id, start_date, end_date)
            try:
                metrics["retention_curve"] = _query_retention(
                    service, video_id, start_date, end_date
                )
            except Exception as exc:
                metrics["retention_curve"] = []
                metrics["retention_curve_status"] = type(exc).__name__
            try:
                sources = _query_traffic_sources(service, video_id, start_date, end_date)
                metrics["traffic_sources"] = sources
                shorts = next((item for item in sources if item.get("insightTrafficSourceType") == "SHORTS"), {})
                metrics["shorts_feed_views"] = int(shorts.get("views") or 0)
                metrics["shorts_feed_engaged_views"] = int(shorts.get("engagedViews") or 0)
                metrics["organic_distribution_status"] = (
                    "shorts_feed_observed" if metrics["shorts_feed_views"] else "no_shorts_feed_observed"
                )
            except Exception as exc:
                metrics["traffic_sources"] = []
                metrics["traffic_source_status"] = type(exc).__name__
            base["videos"][video_id] = metrics
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            errors.append({"video_id": video_id, "http_status": status, "type": type(exc).__name__})
    base["status"] = "ok" if not errors else ("partial" if base["videos"] else "unavailable")
    base["errors"] = errors
    return _write(base)
