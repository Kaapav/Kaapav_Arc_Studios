#!/usr/bin/env python3
"""Secure local-origin KAAPAV dashboard with a read-only tunnel view."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

from src.config import Config, ROOT
from src.growth_learning import extract_traits
from src import meta_platform, platform_control, youtube_timed_release


INDEX = ROOT / "dashboard" / "index.html"
AUTH_SCRIPT = ROOT / "authorize_youtube_analytics.py"
AUTH_PROCESS: subprocess.Popen | None = None
AUTH_LOCK = threading.Lock()
TUNNEL_ORIGIN_HOST = "kaapav-dashboard-tunnel.internal"
SESSION_COOKIE = "kaapav_dashboard_session"
SESSION_SECONDS = 365 * 24 * 60 * 60
SECRET_PATH = ROOT / "credentials" / "dashboard_session_secret.bin"
BOOTSTRAP_CODES: dict[str, float] = {}
BOOTSTRAP_LOCK = threading.Lock()
CONTROL_LOCK = threading.Lock()
AUTOPILOT_TASK = "KAAPAV ARC Studio Autopilot"
LEGAL_PAGES = {
    "/privacy": ROOT / "dashboard" / "privacy.html",
    "/privacy.html": ROOT / "dashboard" / "privacy.html",
    "/terms": ROOT / "dashboard" / "terms.html",
    "/terms.html": ROOT / "dashboard" / "terms.html",
    "/data-deletion": ROOT / "dashboard" / "data-deletion.html",
    "/data-deletion.html": ROOT / "dashboard" / "data-deletion.html",
}


STAGING_ROOT = Path(r"C:\Users\Kawshik\OneDrive\Documents\Default Project\kaapav-new-series")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def scan_staging() -> dict[str, Any]:
    """Read-only scan of the pre-production slate (outside the live studio tree)."""
    found = []
    if not STAGING_ROOT.is_dir():
        return {"available": False, "series": [], "note": "staging root missing"}
    for folder in sorted(p for p in STAGING_ROOT.iterdir() if p.is_dir()):
        blueprint = read_json(folder / "season_blueprint.json", {})
        if not blueprint:
            continue
        series = blueprint.get("series", {})
        episodes = blueprint.get("episodes") or []
        bible = folder / "SERIES_BIBLE.md"
        bible_size = bible.stat().st_size if bible.is_file() else 0
        found.append({
            "series_id": series.get("series_id") or folder.name,
            "series_title": series.get("series_title") or folder.name,
            "genre": series.get("genre") or "unknown",
            "episodes": len(episodes),
            "characters": len(blueprint.get("characters") or []),
            "bible_bytes": bible_size,
            "bible_ready": bible_size > 0,
            "updated_at": str(folder.stat().st_mtime_ns),
        })
    return {"available": True, "series": found, "note": "pre-production slate, outside the live studio tree"}


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def events(limit: int = 20) -> list[dict[str, Any]]:
    path = ROOT / "analytics" / "autopilot_events.jsonl"
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    return list(reversed(rows[-limit:]))


def active_failure_rows() -> list[dict[str, Any]]:
    data = read_json(ROOT / "analytics" / "autopilot_failures.json", {})
    failures = data.get("failures") or {}
    return [dict(value, key=key) for key, value in failures.items()]


def auth_process_status() -> dict[str, Any]:
    with AUTH_LOCK:
        process = AUTH_PROCESS
        return {
            "running": bool(process and process.poll() is None),
            "exit_code": None if not process or process.poll() is None else process.returncode,
        }


def session_secret() -> bytes:
    """Create a local-only signing key without ever writing it to logs/reports."""
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = SECRET_PATH.read_bytes()
        if len(value) >= 32:
            return value
    except OSError:
        pass
    value = secrets.token_bytes(32)
    try:
        descriptor = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
    except FileExistsError:
        return SECRET_PATH.read_bytes()
    return value


def issue_bootstrap_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    code = "-".join(raw[index:index + 4] for index in range(0, 12, 4))
    now = time.time()
    with BOOTSTRAP_LOCK:
        for old, expiry in list(BOOTSTRAP_CODES.items()):
            if expiry < now:
                BOOTSTRAP_CODES.pop(old, None)
        BOOTSTRAP_CODES[code] = now + 600
    return code


def consume_bootstrap_code(code: str) -> bool:
    with BOOTSTRAP_LOCK:
        expiry = BOOTSTRAP_CODES.pop(code, 0)
    return expiry >= time.time()


def issue_session() -> str:
    expiry = int(time.time()) + SESSION_SECONDS
    nonce = secrets.token_urlsafe(16)
    payload = f"{expiry}.{nonce}"
    signature = hmac.new(session_secret(), payload.encode("ascii"), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload}.{encoded}"


def valid_session(value: str) -> bool:
    try:
        expiry_raw, nonce, signature = value.split(".", 2)
        expiry = int(expiry_raw)
        if expiry < int(time.time()) or not nonce:
            return False
        payload = f"{expiry_raw}.{nonce}"
        expected = base64.urlsafe_b64encode(
            hmac.new(session_secret(), payload.encode("ascii"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        return hmac.compare_digest(signature, expected)
    except (TypeError, ValueError):
        return False


def scheduler_action(enabled: bool) -> dict[str, Any]:
    verb = "Start-ScheduledTask" if enabled else "Stop-ScheduledTask"
    completed = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            f"{verb} -TaskName '{AUTOPILOT_TASK}' -ErrorAction Stop",
        ],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return {
        "action": "started" if enabled else "stopped",
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "error": completed.stderr.strip()[-500:] if completed.returncode else None,
    }


def set_automation_enabled(enabled: bool, source: str) -> dict[str, Any]:
    pause_path = ROOT / "analytics" / "PAUSE_AUTOPILOT"
    certification = read_json(ROOT / "analytics" / "setup_certification.json", {})
    if enabled and (certification.get("status") not in {"certified_paused", "certified_active"} or certification.get("failed_checks")):
        return {
            "ok": False, "enabled": False, "error": "setup_certification_not_clean",
            "failed_checks": certification.get("failed_checks") or [],
        }
    with CONTROL_LOCK:
        pause_path.parent.mkdir(parents=True, exist_ok=True)
        if enabled:
            pause_path.unlink(missing_ok=True)
        else:
            temporary = pause_path.with_suffix(".tmp")
            temporary.write_text(
                f"dashboard_owner_disabled at {datetime.now(timezone.utc).isoformat()}\n",
                encoding="utf-8",
            )
            temporary.replace(pause_path)
        scheduler = scheduler_action(enabled)
        if enabled and not scheduler["ok"]:
            temporary = pause_path.with_suffix(".tmp")
            temporary.write_text(
                f"dashboard_enable_rollback at {datetime.now(timezone.utc).isoformat()}\n",
                encoding="utf-8",
            )
            temporary.replace(pause_path)
        event = {
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event": (
                "automation_enable_failed_closed"
                if enabled and not scheduler["ok"]
                else "automation_enabled" if enabled else "automation_disabled"
            ),
            "source": source, "scheduler": scheduler,
        }
        with (ROOT / "analytics" / "dashboard_control_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    if enabled and not scheduler["ok"]:
        return {
            "ok": False, "enabled": False, "production_gate": "closed",
            "error": "scheduler_start_failed_gate_reclosed", "scheduler": scheduler,
        }
    return {
        "ok": True, "enabled": enabled,
        "production_gate": "open" if enabled else "closed", "scheduler": scheduler,
    }


def set_platform_enabled(platform: str, enabled: bool, source: str) -> dict[str, Any]:
    """Change one release adapter without weakening the global safety gate."""
    if platform not in platform_control.PLATFORMS:
        return {"ok": False, "error": "unsupported_platform", "platform": platform}
    if enabled and platform in {"facebook", "instagram"}:
        status = meta_platform.health_check(Config("config.story.yaml"))
        platform_status = ((status.get("platforms") or {}).get(platform) or {}).get("status")
        if platform_status != "ready":
            return {
                "ok": False, "enabled": False, "platform": platform,
                "error": "meta_connection_not_ready", "detail": status.get("detail"),
            }
    item = platform_control.set_enabled(platform, enabled, source=source)
    event = {
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": "platform_enabled" if enabled else "platform_disabled",
        "platform": platform, "source": source,
    }
    path = ROOT / "analytics" / "dashboard_control_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"ok": True, "platform": platform, **item}


def build_status() -> dict[str, Any]:
    analytics = ROOT / "analytics"
    inventory = read_json(analytics / "studio_inventory.json", {})
    universe = read_json(ROOT / "content" / "studio_universe_audit.json", {})
    supervisor = read_json(analytics / "supervisor_state.json", {})
    autopilot = read_json(analytics / "autopilot_state.json", {})
    scheduler = read_json(analytics / "windows_scheduler_status.json", {})
    certification = read_json(analytics / "setup_certification.json", {})
    learning = read_json(analytics / "growth_learning.json", {})
    yt_analytics = read_json(analytics / "youtube_analytics.json", {})
    auth = read_json(analytics / "analytics_authorization_status.json", {})
    backup = read_json(analytics / "backup_state.json", {})
    queue = read_json(analytics / "production_queue.json", {})
    releases = read_csv(analytics / "current.csv")
    controls = platform_control.summary()
    meta_status = read_json(analytics / "meta_status.json", {})
    meta_scheduler = read_json(analytics / "meta_scheduler_status.json", {})
    meta_analytics = read_json(analytics / "meta_analytics.json", {})
    platform_learning = read_json(analytics / "platform_learning.json", {})
    meta_queue = meta_platform.queue_summary()
    meta_ledger = read_json(analytics / "meta_release_ledger.json", {"releases": []})

    pause = analytics / "PAUSE_AUTOPILOT"
    lock = read_json(analytics / "autopilot.lock", {})
    working = bool(lock and pid_alive(int(lock.get("pid") or 0)) and not pause.exists())
    if pause.exists():
        mode, tone = "PAUSED", "amber"
    elif working:
        mode, tone = "WORKING", "green"
    elif supervisor.get("status") in {"recovery_required", "failed"}:
        mode, tone = "NEEDS RECOVERY", "red"
    elif supervisor.get("status") == "cooldown":
        mode, tone = "AUTO-REPAIRING", "amber"
    else:
        mode, tone = "READY / WAITING", "blue"

    episodes = inventory.get("episodes") or []
    manifest_index: dict[tuple[str, int], dict[str, Any]] = {}
    for item in episodes:
        path = Path(str(item.get("manifest_path") or ""))
        manifest = read_json(path, {}) if path.is_file() else {}
        key = (str(item.get("series_id") or ""), int(item.get("episode") or 0))
        manifest_index[key] = {
            "title": manifest.get("title") or f"Episode {key[1]}",
            "tags": manifest.get("tags") or [],
            "traits": extract_traits(manifest) if manifest else {},
        }
    state_counts = Counter(str(item.get("state") or "unknown") for item in episodes)
    grouped: dict[int, dict[str, Any]] = defaultdict(lambda: {"states": Counter(), "episodes": 0})
    for item in episodes:
        seq = int(item.get("sequence") or 0)
        grouped[seq]["title"] = item.get("series_title") or item.get("series_id")
        grouped[seq]["series_id"] = item.get("series_id")
        grouped[seq]["episodes"] += 1
        grouped[seq]["states"][str(item.get("state") or "unknown")] += 1
    series = []
    completed_states = {"public", "scheduled", "private_uploaded", "strict_audit_passed"}
    for seq, data in sorted(grouped.items()):
        completed = sum(count for state, count in data["states"].items() if state in completed_states)
        series.append({
            "sequence": seq, "title": data.get("title"), "series_id": data.get("series_id"),
            "episodes": data["episodes"], "release_ready": completed,
            "progress_percent": round(100 * completed / max(1, data["episodes"]), 1),
            "states": dict(data["states"]),
        })
    episode_pipeline = []
    for item in episodes:
        key = (str(item.get("series_id") or ""), int(item.get("episode") or 0))
        creative = manifest_index.get(key, {})
        episode_pipeline.append({
            "sequence": item.get("sequence"), "series_id": item.get("series_id"),
            "series_title": item.get("series_title"), "episode": item.get("episode"),
            "episode_title": creative.get("title"), "state": item.get("state"),
            "blocker": item.get("blocker"), "publish_at": item.get("publish_at"),
            "youtube_url": item.get("youtube_url"),
        })

    privacy = Counter(row.get("privacy") or "unknown" for row in releases)
    total_views = sum(int(row.get("views") or 0) for row in releases)
    public_rows = [row for row in releases if row.get("privacy") == "public"]
    tasks = sorted(queue.get("tasks") or [], key=lambda item: int(item.get("priority") or 9999))
    tasks = [dict(item, episode_title=manifest_index.get(
        (str(item.get("series_id") or ""), int(item.get("episode") or 0)), {}
    ).get("title")) for item in tasks]
    next_task = tasks[0] if tasks else None
    if mode == "PAUSED":
        work_summary = "Setup is safe and paused. Queued work will not start until the owner removes the gate."
    elif working:
        work_summary = f"Automation is working now. Run status: {autopilot.get('status', 'running')}."
    elif next_task:
        work_summary = f"Waiting for scheduler. Next: {next_task.get('action')} on {next_task.get('series_id')} Episode {next_task.get('episode')}."
    else:
        work_summary = "No queued production work."

    image_total = int(universe.get("existing_story_image_count") or 0) + int(universe.get("pending_story_image_count") or 0)
    observation_index = {str(item.get("video_id")): item for item in (learning.get("observations") or [])}
    excluded_index = {str(item.get("video_id")): item for item in (learning.get("excluded_owner_test_observations") or [])}
    detailed_index = yt_analytics.get("videos") or {}
    release_rows = []
    episode_performance = []
    for row in releases:
        try:
            episode_number = int(row.get("episode") or 0)
        except ValueError:
            episode_number = 0
        key = (str(row.get("series_id") or ""), episode_number)
        creative = manifest_index.get(key, {})
        release = {field: row.get(field) for field in (
            "video_id", "series_id", "episode", "title", "privacy", "published_at",
            "remote_publish_at", "views", "likes", "comments", "views_per_day",
            "like_rate", "comment_rate", "url"
        )}
        release.update({"episode_title": creative.get("title"), "tags": creative.get("tags") or [],
                        "traits": creative.get("traits") or {}})
        release_rows.append(release)
        video_id = str(row.get("video_id") or "")
        details = detailed_index.get(video_id) or {}
        observation = observation_index.get(video_id)
        excluded = excluded_index.get(video_id)
        episode_performance.append({
            **release,
            "learning_eligibility": "owner_test_excluded" if excluded else (
                "eligible" if str(row.get("privacy")) == "public" else "not_public"
            ),
            "evidence_window_hours": (observation or {}).get("window_hours"),
            "diagnosis": (observation or {}).get("diagnosis") or (
                "owner_test_excluded" if excluded else "waiting_for_evidence"
            ),
            "learning_score": (observation or {}).get("score"),
            "engaged_views": details.get("engagedViews"),
            "average_view_duration": details.get("averageViewDuration"),
            "average_view_percentage": details.get("averageViewPercentage"),
            "shares": details.get("shares"),
            "subscribers_gained": details.get("subscribersGained"),
            "traffic_sources": details.get("traffic_sources") or [],
            "shorts_feed_views": details.get("shorts_feed_views"),
            "shorts_feed_engaged_views": details.get("shorts_feed_engaged_views"),
            "organic_distribution_status": details.get("organic_distribution_status") or "waiting_for_evidence",
            "retention_curve_points": len(details.get("retention_curve") or []),
        })

    tag_accumulator: dict[str, dict[str, float]] = {}
    for item in episode_performance:
        if item.get("learning_eligibility") != "eligible" or item.get("learning_score") is None:
            continue
        for tag in item.get("tags") or []:
            bucket = tag_accumulator.setdefault(str(tag), {"samples": 0, "views": 0, "score": 0.0})
            bucket["samples"] += 1
            bucket["views"] += int(item.get("views") or 0)
            bucket["score"] += float(item.get("learning_score") or 0)
    tag_performance = [{
        "tag": tag, "samples": int(values["samples"]), "views": int(values["views"]),
        "mean_score": round(values["score"] / max(1, values["samples"]), 4),
        "status": "directional" if values["samples"] >= 3 else "insufficient_sample",
    } for tag, values in sorted(tag_accumulator.items(), key=lambda pair: (-pair[1]["samples"], pair[0]))]

    yt_queue = youtube_timed_release.summary()
    platform_health = {
        "youtube": {
            **controls.get("youtube", {}),
            "health": "ready" if auth.get("status") == "ready" else "degraded" if releases else "setup_required",
            "detail": auth.get("detail") or "YouTube Data and Analytics connection",
            "queued": yt_queue.get("queued", 0),
            "next_publish_at": yt_queue.get("next_publish_at"),
            "published": privacy.get("public", 0),
            "failures": len((read_json(analytics / "release_reconciliation.json", {}).get("failures") or [])),
        },
        "facebook": {
            **controls.get("facebook", {}),
            "health": ((meta_status.get("platforms") or {}).get("facebook") or {}).get("status", meta_status.get("status", "not_configured")),
            "detail": ((meta_status.get("platforms") or {}).get("facebook") or {}).get("detail", meta_status.get("detail")),
            **meta_queue.get("facebook", {}),
        },
        "instagram": {
            **controls.get("instagram", {}),
            "health": ((meta_status.get("platforms") or {}).get("instagram") or {}).get("status", meta_status.get("status", "not_configured")),
            "detail": ((meta_status.get("platforms") or {}).get("instagram") or {}).get("detail", meta_status.get("detail")),
            **meta_queue.get("instagram", {}),
        },
    }
    meta_release_rows = list(reversed((meta_ledger.get("releases") or [])[-100:]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "studio": {
            "mode": mode, "tone": tone, "working_now": working,
            "summary": work_summary, "pause_file": pause.exists(),
            "supervisor_status": supervisor.get("status"),
            "autopilot_status": autopilot.get("status"),
            "current_run_id": autopilot.get("run_id"),
            "next_task": next_task,
        },
        "overview": {
            "certification": certification.get("status"),
            "certification_failures": certification.get("failed_checks") or [],
            "series": int(universe.get("series_count") or len(series)),
            "episode_manifests": int(universe.get("episode_manifest_count") or len(episodes)),
            "scene_scripts": int(universe.get("scene_script_count") or 0),
            "images_complete": sum(int(e.get("frames_present") or 0) for e in episodes),
            "images_total": sum(int(e.get("scene_count") or 0) for e in episodes),
            "image_progress_percent": round(100 * sum(int(e.get("frames_present") or 0) for e in episodes) / max(1, sum(int(e.get("scene_count") or 0) for e in episodes)), 1),
            "public_videos": sum(1 for e in episodes if e.get("state") == "public"),
            "scheduled_videos": sum(1 for e in episodes if e.get("state") == "scheduled"),
            "total_views": total_views,
            "ready_buffer": int(inventory.get("ready_or_scheduled_count") or 0),
            "buffer_target": int(inventory.get("target_ready_shorts") or 7),
            "platforms": platform_health,
        },
        "production": {
            "active_series_sequence": inventory.get("active_series_sequence"),
            "shortage": inventory.get("shortage"),
            "state_counts": dict(state_counts), "series": series,
            "episodes": episode_pipeline,
            "queue": tasks[:30], "failures": active_failure_rows(), "events": events(),
        },
        "releases": {
            "counts": dict(privacy), "videos": release_rows,
            "reconciliation": read_json(analytics / "release_reconciliation.json", {}),
            "meta": meta_release_rows,
            "meta_queue": meta_queue,
        },
        "performance": {
            "channel": {
                "title": releases[0].get("channel_title") if releases else "KAAPAV ARC Studios",
                "subscribers": int(releases[0].get("subscribers") or 0) if releases else 0,
                "channel_views": int(releases[0].get("channel_views") or 0) if releases else 0,
            },
            "public_videos": public_rows,
            "learning": {
                "status": "learning" if learning.get("observations") else "waiting_for_organic_evidence",
                "observations": len(learning.get("observations") or []),
                "window_snapshots": len(learning.get("window_snapshots") or []),
                "minimum_views": learning.get("minimum_meaningful_views"),
                "minimum_samples": learning.get("minimum_arm_samples"),
            },
            "youtube_analytics": yt_analytics,
            "analytics_authorization": auth,
            "authorization_process": auth_process_status(),
            "episodes": episode_performance,
            "tag_performance": tag_performance,
            "meta_analytics": meta_analytics,
            "platform_learning": platform_learning,
        },
        "system": {
            "scheduler": scheduler, "supervisor": supervisor,
            "certification": certification, "backup": backup,
            "production_gate": "closed" if pause.exists() else "open",
            "platforms": platform_health,
            "meta_scheduler": meta_scheduler,
            "autopilot_runs": {
                "run_id": autopilot.get("run_id"),
                "status": autopilot.get("status"),
                "started_at": autopilot.get("started_at"),
                "finished_at": autopilot.get("finished_at"),
                "recovery": autopilot.get("recovery"),
            },
            "last_worked": {
                "autopilot_started_at": autopilot.get("started_at"),
                "autopilot_finished_at": autopilot.get("finished_at"),
                "autopilot_run_id": autopilot.get("run_id"),
                "autopilot_status": autopilot.get("status"),
                "scheduler_checked_at": scheduler.get("checked_at"),
                "reconciliation_checked_at": read_json(
                    analytics / "release_reconciliation.json", {}
                ).get("checked_at"),
            },
        },
        "platforms": platform_health,
        "staging": scan_staging(),
    }


def start_authorization(test_only: bool = False) -> dict[str, Any]:
    global AUTH_PROCESS
    with AUTH_LOCK:
        if AUTH_PROCESS and AUTH_PROCESS.poll() is None:
            return {"started": False, "reason": "authorization_already_running"}
        command = [sys.executable, "-u", str(AUTH_SCRIPT)]
        if test_only:
            command.append("--test-only")
        else:
            command.extend(["--open-console", "--wait-minutes", "10"])
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        AUTH_PROCESS = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return {"started": True, "pid": AUTH_PROCESS.pid, "test_only": test_only}


class Handler(BaseHTTPRequestHandler):
    server_version = "KAAPAVDashboard/1.0"

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_public_file(self, path: Path, content_type: str, *, head_only: bool = False) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    def send_meta_media(self, route: str, *, head_only: bool = False) -> None:
        path = meta_platform.resolve_media_grant(route)
        if path is None:
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        partial = False
        range_header = str(self.headers.get("Range") or "")
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        if match:
            partial = True
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = min(size - 1, int(match.group(2)))
            if start < 0 or start >= size or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def is_tunnel_request(self) -> bool:
        return str(self.headers.get("Host") or "").split(":", 1)[0].lower() == TUNNEL_ORIGIN_HOST

    def has_session(self) -> bool:
        if not self.is_tunnel_request():
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(str(self.headers.get("Cookie") or ""))
            morsel = cookie.get(SESSION_COOKIE)
            return bool(morsel and valid_session(morsel.value))
        except Exception:
            return False

    def send_unauthorized(self) -> None:
        body = (
            "<!doctype html><meta charset='utf-8'><title>KAAPAV Access Required</title>"
            "<style>body{margin:0;display:grid;place-items:center;min-height:100vh;background:#070914;"
            "color:#eef2ff;font:16px system-ui}.box{padding:32px;border:1px solid #ffffff1c;border-radius:20px;"
            "background:#151a30cc;max-width:520px}p{color:#aab3ca}</style>"
            "<div class='box'><h1>KAAPAV secure access</h1>"
            "<p>Open this dashboard using the KAAPAV Studio Dashboard shortcut on the authorized PC.</p></div>"
        ).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route.startswith("/media/"):
            self.send_meta_media(route)
            return
        if route in LEGAL_PAGES:
            self.send_public_file(LEGAL_PAGES[route], "text/html; charset=utf-8")
            return
        if route == "/logo.png":
            self.send_public_file(ROOT / "dashboard" / "logo.png", "image/png")
            return
        if route == "/api/bootstrap":
            if self.is_tunnel_request():
                self.send_json({"error": "local_only"}, 403)
            else:
                self.send_json({"code": issue_bootstrap_code(), "expires_in_seconds": 600})
            return
        if route == "/auth/bootstrap":
            code = str((parse_qs(parsed.query).get("code") or [""])[0])
            if not self.is_tunnel_request() or not consume_bootstrap_code(code):
                self.send_unauthorized()
                return
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={issue_session()}; Max-Age={SESSION_SECONDS}; Path=/; HttpOnly; Secure; SameSite=Strict",
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if not self.has_session():
            self.send_unauthorized()
            return
        if route == "/api/status":
            status = build_status()
            status["access"] = {
                "mode": "remote_owner_control" if self.is_tunnel_request() else "local_control",
                "public_hostname": "yt.kaapav.com",
                "automation_control": True,
            }
            self.send_json(status)
            return
        if route == "/api/health":
            self.send_json({"status": "ok"})
            return
        if route in {"/", "/index.html"}:
            try:
                body = INDEX.read_bytes()
            except OSError:
                self.send_error(500, "Dashboard UI missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_HEAD(self) -> None:
        route = urlparse(self.path).path
        if route.startswith("/media/"):
            self.send_meta_media(route, head_only=True)
            return
        if route in LEGAL_PAGES:
            self.send_public_file(LEGAL_PAGES[route], "text/html; charset=utf-8", head_only=True)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if not self.has_session():
            self.send_unauthorized()
            return
        if route == "/api/autopilot-control":
            if self.headers.get("X-KAAPAV-Control") != "confirmed":
                self.send_json({"error": "explicit_confirmation_required"}, 403)
                return
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self.send_json({"error": "invalid_json"}, 400)
                return
            action = str(payload.get("action") or "").lower()
            if action not in {"enable", "disable"}:
                self.send_json({"error": "action_must_be_enable_or_disable"}, 400)
                return
            result = set_automation_enabled(
                action == "enable",
                "remote_dashboard" if self.is_tunnel_request() else "local_dashboard",
            )
            self.send_json(result, 200 if result.get("ok") else 409)
            return
        if route == "/api/platform-control":
            if self.headers.get("X-KAAPAV-Control") != "confirmed":
                self.send_json({"error": "explicit_confirmation_required"}, 403)
                return
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self.send_json({"error": "invalid_json"}, 400)
                return
            platform = str(payload.get("platform") or "").lower()
            action = str(payload.get("action") or "").lower()
            if action not in {"enable", "disable"}:
                self.send_json({"error": "action_must_be_enable_or_disable"}, 400)
                return
            result = set_platform_enabled(
                platform, action == "enable",
                "remote_dashboard" if self.is_tunnel_request() else "local_dashboard",
            )
            self.send_json(result, 200 if result.get("ok") else 409)
            return
        if self.is_tunnel_request():
            self.send_json({"error": "remote_control_not_allowed_for_this_action"}, 403)
            return
        if route == "/api/analytics-authorize":
            self.send_json(start_authorization(False), 202)
            return
        if route == "/api/analytics-test":
            self.send_json(start_authorization(True), 202)
            return
        self.send_error(404)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Dashboard is intentionally restricted to localhost")
    url = f"http://127.0.0.1:{args.port}/"
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) == 98:
            if args.open:
                webbrowser.open(url)
            return 0
        raise
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
