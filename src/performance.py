"""YouTube performance collection with local-first and Google Sheets mirrors."""

from __future__ import annotations

import csv
import datetime as dt
import json
import random
import re
import time
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .config import ROOT
from .upload import _get_service


COLUMNS = [
    "snapshot_date", "snapshot_at", "channel_id", "channel_title",
    "subscribers", "channel_views", "channel_video_count", "video_id",
    "series_id", "episode_id", "episode", "release_kind",
    "title", "published_at", "privacy", "duration_seconds", "views",
    "likes", "comments", "days_live", "views_per_day", "like_rate",
    "comment_rate", "remote_publish_at", "made_for_kids", "url",
]


FALLBACK_MATRIX = [
    [
        "Priority", "Stage", "Primary", "Failure response", "Manual actions",
        "Quality floor", "Recovery state",
    ],
    [
        1, "Identity", "Locked multi-angle character registry",
        "Block scene generation until every required identity is locked", 0,
        "No identity drift", "production_queue.json",
    ],
    [
        2, "Story images", "Approved prompt + locked references",
        "Retry generation; never substitute filler or duplicate frames", 0,
        "Eight distinct causal visual intentions", "production_queue.json",
    ],
    [
        3, "Render", "Local FFmpeg + Piper",
        "Exponential retry from last accepted assets", 0,
        "Captions, narration, sound, motion, full decode", "autopilot_failures.json",
    ],
    [
        4, "Release", "Resumable YouTube upload",
        "Keep private; retry thumbnail or scheduling by existing video ID", 0,
        "No public-now and no missing-thumbnail release", "upload_result.json",
    ],
    [
        5, "Learning", "YouTube Data + optional Analytics API",
        "Use local snapshots; mark reach cause unknown instead of guessing", 0,
        "24h/72h/168h evidence windows", "growth_learning.json",
    ],
]


def _integer(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _duration_seconds(value: str) -> int:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value or "",
    )
    if not match:
        return 0
    parts = {key: _integer(number) for key, number in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _published_days(value: str, now: dt.datetime) -> int:
    try:
        published = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(1, (now - published).days + 1)
    except Exception:
        return 1


def collect(cfg) -> tuple[dict, list[dict]]:
    """Collect the configured channel and every upload using low-cost list calls."""
    service = _get_service(cfg, verify_channel=False)
    expected = str(cfg.get("youtube", "expected_channel_id", default="") or "").strip()
    channel_request = service.channels().list(
        part="snippet,contentDetails,statistics",
        **({"id": expected} if expected else {"mine": True}),
    )
    items = channel_request.execute().get("items", [])
    if not items:
        raise RuntimeError(f"Configured YouTube channel not found: {expected or 'mine'}")
    channel = items[0]
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    page_token = None
    while True:
        response = service.playlistItems().list(
            part="contentDetails",
            playlistId=uploads,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        video_ids.extend(
            item["contentDetails"]["videoId"] for item in response.get("items", [])
        )
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for start in range(0, len(video_ids), 50):
        response = service.videos().list(
            part="snippet,statistics,contentDetails,status",
            id=",".join(video_ids[start:start + 50]),
            maxResults=50,
        ).execute()
        videos.extend(response.get("items", []))

    now = dt.datetime.now(dt.timezone.utc)
    snapshot_at = now.isoformat(timespec="seconds")
    snapshot_date = now.date().isoformat()
    stats = channel.get("statistics", {})
    channel_summary = {
        "snapshot_date": snapshot_date,
        "snapshot_at": snapshot_at,
        "channel_id": channel["id"],
        "channel_title": channel["snippet"]["title"],
        "subscribers": _integer(stats.get("subscriberCount")),
        "channel_views": _integer(stats.get("viewCount")),
        "channel_video_count": _integer(stats.get("videoCount")),
    }
    rows = []
    for item in videos:
        snippet = item.get("snippet", {})
        video_stats = item.get("statistics", {})
        views = _integer(video_stats.get("viewCount"))
        likes = _integer(video_stats.get("likeCount"))
        comments = _integer(video_stats.get("commentCount"))
        days = _published_days(snippet.get("publishedAt", ""), now)
        row = dict(channel_summary)
        row.update({
            "video_id": item["id"],
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt", ""),
            "privacy": item.get("status", {}).get("privacyStatus", "unknown"),
            "remote_publish_at": item.get("status", {}).get("publishAt", ""),
            "made_for_kids": bool(item.get("status", {}).get("madeForKids", False)),
            # Kept out of COLUMNS because descriptions/tags make the Sheet noisy.
            # The strict remote reconciler consumes these fields before CSV save.
            "_remote_description": snippet.get("description", ""),
            "_remote_tags": snippet.get("tags", []),
            "_remote_category_id": snippet.get("categoryId", ""),
            "_remote_default_language": snippet.get("defaultLanguage", ""),
            "duration_seconds": _duration_seconds(item.get("contentDetails", {}).get("duration", "")),
            "views": views,
            "likes": likes,
            "comments": comments,
            "days_live": days,
            "views_per_day": round(views / days, 2),
            "like_rate": round(likes / views, 6) if views else 0,
            "comment_rate": round(comments / views, 6) if views else 0,
            "url": f"https://youtu.be/{item['id']}",
        })
        rows.append(row)
    rows.sort(key=lambda row: row["published_at"], reverse=True)
    return channel_summary, rows


def _write_csv_atomic(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def save_local(rows: list[dict], channel_id: str | None = None) -> tuple[Path, Path, list[dict]]:
    analytics_dir = ROOT / "analytics"
    current_path = analytics_dir / "current.csv"
    history_path = analytics_dir / "daily_snapshots.csv"
    existing = []
    if history_path.exists():
        with history_path.open("r", newline="", encoding="utf-8-sig") as handle:
            existing = list(csv.DictReader(handle))
    if channel_id:
        existing = [row for row in existing if row.get("channel_id") == channel_id]
    combined = {(row["snapshot_date"], row["video_id"]): row for row in existing}
    for row in rows:
        combined[(str(row["snapshot_date"]), str(row["video_id"]))] = row
    history = sorted(
        combined.values(),
        key=lambda row: (str(row["snapshot_date"]), str(row["published_at"]), str(row["video_id"])),
    )
    _write_csv_atomic(current_path, rows)
    _write_csv_atomic(history_path, history)
    return current_path, history_path, history


def _execute_with_backoff(request, attempts: int = 5):
    last_error = None
    for attempt in range(attempts):
        try:
            return request.execute()
        except Exception as exc:
            last_error = exc
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status not in {408, 429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            time.sleep(min(32, (2 ** attempt) + random.random()))
    raise last_error


def _matrix(rows: list[dict]) -> list[list]:
    return [COLUMNS] + [[row.get(column, "") for column in COLUMNS] for row in rows]


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _learning_matrix() -> list[list]:
    state = _json_object(ROOT / "analytics" / "growth_learning.json")
    recommendations = _json_object(ROOT / "analytics" / "learning_recommendations.json").get("recommendations", {})
    rows = [["Dimension", "Arm", "Samples", "Mean score", "Success probability", "Current mode", "Preferred"]]
    for dimension, arms in (state.get("posteriors") or {}).items():
        rec = recommendations.get(dimension) or {}
        for arm, data in arms.items():
            rows.append([
                dimension, arm, data.get("samples", 0), data.get("mean_score", ""),
                data.get("success_probability", ""), rec.get("mode", ""),
                "YES" if rec.get("preferred") == arm else "",
            ])
    rows.append([])
    rows.append(["Series", "Episode", "Video ID", "Window hours", "Captured age", "Views", "Likes", "Comments"])
    for item in state.get("window_snapshots", []):
        rows.append([
            item.get("series_id"), item.get("episode"), item.get("video_id"),
            item.get("window_hours"), item.get("captured_age_hours"), item.get("views"),
            item.get("likes"), item.get("comments"),
        ])
    return rows


def _inventory_matrix() -> list[list]:
    state = _json_object(ROOT / "analytics" / "studio_inventory.json")
    columns = [
        "Series", "Episode", "State", "Identities locked", "Frames present",
        "Scene count", "Images accepted", "Blocker", "Publish at", "Audit ID",
    ]
    values = [columns]
    for item in state.get("episodes", []):
        values.append([
            item.get("series_title"), item.get("episode"), item.get("state"),
            item.get("identities_locked"), item.get("frames_present"), item.get("scene_count"),
            item.get("images_accepted"), item.get("blocker"), item.get("publish_at"), item.get("audit_id"),
        ])
    return values


def _audit_matrix() -> list[list]:
    rows = [["Created", "Audit ID", "Status", "Video", "SHA256", "Failures"]]
    for path in sorted((ROOT / "output" / "story").glob("*/prepublish_audit.json")):
        report = _json_object(path)
        video = (report.get("inputs") or {}).get("video") or {}
        rows.append([
            report.get("created_at"), report.get("audit_id"), report.get("status"),
            video.get("path"), video.get("sha256"), "; ".join(report.get("failures") or []),
        ])
    return rows


def _health_matrix() -> list[list]:
    state = _json_object(ROOT / "analytics" / "autopilot_state.json")
    rows = [["Field", "Value"], ["Run ID", state.get("run_id")], ["Status", state.get("status")],
            ["Started", state.get("started_at")], ["Finished", state.get("finished_at")],
            ["Normal manual actions", state.get("normal_manual_actions")], ["Fail closed", state.get("fail_closed")]]
    for stage, detail in (state.get("stages") or {}).items():
        rows.append([f"Stage: {stage}", json.dumps(detail, ensure_ascii=False)])
    return rows


def _platform_health_matrix() -> list[list]:
    controls = _json_object(ROOT / "analytics" / "platform_controls.json").get("platforms", {})
    meta_status = _json_object(ROOT / "analytics" / "meta_status.json")
    queue = _json_object(ROOT / "analytics" / "meta_release_queue.json").get("items", [])
    ledger = _json_object(ROOT / "analytics" / "meta_release_ledger.json").get("releases", [])
    rows = [["Platform", "Enabled", "Health", "Queued", "Published", "Failed", "Last detail"]]
    for platform in ("youtube", "facebook", "instagram"):
        platform_queue = [item for item in queue if item.get("platform") == platform]
        platform_releases = [item for item in ledger if item.get("platform") == platform]
        if platform == "youtube":
            health = "ready" if bool((controls.get(platform) or {}).get("enabled", True)) else "disabled"
            detail = "YouTube Data and Analytics are tracked by the main automation"
        else:
            health = meta_status.get("status", "not_configured")
            detail = meta_status.get("detail", "")
        rows.append([
            platform,
            bool((controls.get(platform) or {}).get("enabled", platform == "youtube")),
            health,
            sum(item.get("status") in {"queued", "retry"} for item in platform_queue),
            sum(item.get("status") == "published" for item in platform_releases),
            sum(item.get("status") in {"failed", "manual_reconciliation_required"} for item in platform_queue),
            detail,
        ])
    return rows


def _meta_performance_matrix() -> list[list]:
    state = _json_object(ROOT / "analytics" / "meta_analytics.json")
    columns = [
        "Snapshot", "Platform", "Series", "Episode", "Kind", "Media ID",
        "Published", "Views", "Reach", "Likes", "Comments", "Shares", "Saves",
        "Average watch ms", "Total watch ms", "Complete views", "Follows", "URL",
        "Unavailable metrics",
    ]
    rows = [columns]
    for item in state.get("media", []):
        rows.append([
            item.get("snapshot_at"), item.get("platform"), item.get("series_id"),
            item.get("episode"), item.get("release_kind"), item.get("media_id"),
            item.get("published_at"), item.get("views"), item.get("reach"), item.get("likes"),
            item.get("comments"), item.get("shares"), item.get("saves"),
            item.get("average_watch_time_ms"), item.get("total_watch_time_ms"),
            item.get("complete_views"), item.get("follows"), item.get("url"),
            ", ".join(item.get("unavailable_metrics") or []),
        ])
    return rows


def _meta_history_matrix() -> list[list]:
    state = _json_object(ROOT / "analytics" / "meta_analytics_history.json")
    rows = [["Snapshot", "Platform", "Tracked media", "Views", "Likes", "Comments", "Shares"]]
    for snapshot in state.get("snapshots", []):
        for platform, values in (snapshot.get("platforms") or {}).items():
            rows.append([
                snapshot.get("snapshot_at"), platform, values.get("tracked_media"),
                values.get("views"), values.get("likes"), values.get("comments"), values.get("shares"),
            ])
    return rows


def sync_google_sheet(cfg, current_rows: list[dict], history_rows: list[dict],
                      summary: dict | None = None) -> str | None:
    """Mirror local truth to a user-owned Sheet shared with a service account."""
    sheet_id = cfg.google_sheet_id
    account_file = cfg.google_service_account_file
    if not sheet_id or not account_file:
        return None
    account_path = Path(account_file)
    if not account_path.is_absolute():
        account_path = ROOT / account_path
    if not account_path.exists():
        raise FileNotFoundError(f"Google service account file missing: {account_path}")

    credentials = service_account.Credentials.from_service_account_file(
        str(account_path),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    sheets = build("sheets", "v4", credentials=credentials)
    meta = _execute_with_backoff(
        sheets.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties")
    )
    existing = {item["properties"]["title"]: item["properties"]["sheetId"] for item in meta.get("sheets", [])}
    required = [
        "Dashboard", "Videos", "Daily Snapshots", "Learning", "Inventory",
        "Audit Log", "Autopilot Health", "Fallback Matrix", "Platform Health",
        "Meta Performance", "Meta History",
    ]
    missing = [name for name in required if name not in existing]
    if missing:
        _execute_with_backoff(sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": name}}} for name in missing]},
        ))
        meta = _execute_with_backoff(
            sheets.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties")
        )
        existing = {item["properties"]["title"]: item["properties"]["sheetId"] for item in meta.get("sheets", [])}

    growth_path = ROOT / cfg.get("growth", "state_file", default="analytics/growth_state.json")
    try:
        growth = json.loads(growth_path.read_text(encoding="utf-8"))
    except Exception:
        growth = {}
    summary = summary or (current_rows[0] if current_rows else {})
    subscribers = int(summary.get("subscribers", 0) or 0)
    evaluation = growth.get("last_evaluation") or {}
    dashboard = [
        [f"{cfg.get('channel', 'name', default='Channel')} Performance Tracker", ""],
        ["Last refreshed", summary.get("snapshot_at", "")],
        ["Channel", summary.get("channel_title", "")],
        ["Channel ID", summary.get("channel_id", "")],
        ["Subscribers", subscribers],
        ["Subscribers needed for early YPP", max(0, 500 - subscribers)],
        ["Subscribers needed for ad revenue", max(0, 1000 - subscribers)],
        ["Tracked public uploads", "=COUNTIF(Videos!O2:O,\"public\")"],
        ["Public uploads needed for early YPP", "=MAX(0,3-COUNTIF(Videos!O2:O,\"public\"))"],
        ["Channel views", int(summary.get("channel_views", 0) or 0)],
        ["Tracked videos", "=COUNTA(Videos!H2:H)"],
        ["Average views/video", "=IFERROR(AVERAGE(Videos!Q2:Q),0)"],
        ["Total likes", "=SUM(Videos!R2:R)"],
        ["Best video", "=IFERROR(INDEX(Videos!M2:M,MATCH(MAX(Videos!Q2:Q),Videos!Q2:Q,0)),\"\")"],
        ["Best video views", "=IFERROR(MAX(Videos!Q2:Q),0)"],
        ["Growth mode", cfg.get("growth", "mode", default="adaptive_cohorts")],
        ["Growth phase", growth.get("phase", "not started")],
        ["Released through episode", growth.get("released_through", 0)],
        ["Current cohort", f"{growth.get('cohort_start', '')}-{growth.get('cohort_end', '')}"],
        ["Last gate average views", evaluation.get("average_views", "")],
        ["Last gate subscriber gain", evaluation.get("subscriber_gain", "")],
        ["Early YPP route", "500 subscribers + 3 public uploads/90d + either 3,000 long-form watch hours/12m or 3M valid Shorts views/90d"],
        ["Ad revenue route", "1,000 subscribers + either 4,000 long-form watch hours/12m or 10M valid Shorts views/90d"],
        ["Watch-hour rule", "Shorts Feed watch hours do not count toward the 4,000-hour route"],
    ]
    _execute_with_backoff(sheets.spreadsheets().values().batchClear(
        spreadsheetId=sheet_id,
        body={"ranges": [
            "Dashboard!A:Z", "Videos!A:Z", "'Daily Snapshots'!A:Z",
            "Learning!A:Z", "Inventory!A:Z", "'Audit Log'!A:Z",
            "'Autopilot Health'!A:Z",
            "'Fallback Matrix'!A:Z",
            "'Platform Health'!A:Z", "'Meta Performance'!A:Z", "'Meta History'!A:Z",
        ]},
    ))
    _execute_with_backoff(sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sheet_id,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {"range": "Dashboard!A1", "values": dashboard},
                {"range": "Videos!A1", "values": _matrix(current_rows)},
                {"range": "'Daily Snapshots'!A1", "values": _matrix(history_rows)},
                {"range": "Learning!A1", "values": _learning_matrix()},
                {"range": "Inventory!A1", "values": _inventory_matrix()},
                {"range": "'Audit Log'!A1", "values": _audit_matrix()},
                {"range": "'Autopilot Health'!A1", "values": _health_matrix()},
                {"range": "'Fallback Matrix'!A1", "values": FALLBACK_MATRIX},
                {"range": "'Platform Health'!A1", "values": _platform_health_matrix()},
                {"range": "'Meta Performance'!A1", "values": _meta_performance_matrix()},
                {"range": "'Meta History'!A1", "values": _meta_history_matrix()},
            ],
        },
    ))
    format_requests = []
    for name in required:
        sheet_id_value = existing[name]
        format_requests.extend([
            {"updateSheetProperties": {"properties": {"sheetId": sheet_id_value, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {"sheetId": sheet_id_value, "startRowIndex": 0, "endRowIndex": 1}, "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.05, "green": 0.12, "blue": 0.22}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
            {"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id_value, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 20}}},
        ])
    _execute_with_backoff(sheets.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id, body={"requests": format_requests}
    ))
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"


def write_status(summary: dict, current_path: Path, history_path: Path, google_url: str | None) -> Path:
    status_path = ROOT / "analytics" / "last_refresh.json"
    temporary = status_path.with_name(status_path.name + ".tmp")
    payload = dict(summary)
    payload.update({
        "current_csv": str(current_path),
        "history_csv": str(history_path),
        "google_sheet": google_url,
    })
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(status_path)
    return status_path
