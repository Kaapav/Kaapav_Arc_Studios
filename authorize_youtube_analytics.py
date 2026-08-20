#!/usr/bin/env python3
"""Safely upgrade the existing YouTube OAuth grant with Analytics read access.

Google requires one interactive owner consent. The accepted refresh token is
then reused unattended by the studio. The existing working token is never
replaced until the candidate grant is verified against the configured channel.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import Config, ROOT
from src.upload import SCOPES, resolve_client_secret


ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
STATUS_PATH = ROOT / "analytics" / "analytics_authorization_status.json"


def write_status(status: str, **details: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        **details,
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATUS_PATH)
    return payload


def verify_channel(cfg: Config, credentials: Credentials) -> dict[str, str]:
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    items = service.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        raise RuntimeError("Authorized Google account has no accessible YouTube channel")
    channel = items[0]
    expected = str(cfg.get("youtube", "expected_channel_id", default="") or "")
    if channel.get("id") != expected:
        raise RuntimeError(
            f"Wrong channel selected: {channel.get('snippet', {}).get('title', 'unknown')} "
            f"({channel.get('id')}); expected {expected}"
        )
    return {"id": str(channel.get("id")), "title": str(channel.get("snippet", {}).get("title", ""))}


def test_analytics(credentials: Credentials) -> dict[str, Any]:
    service = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
    end_date = date.today()
    result = service.reports().query(
        ids="channel==MINE",
        startDate=(end_date - timedelta(days=28)).isoformat(),
        endDate=end_date.isoformat(),
        metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
    ).execute()
    headers = [str(item.get("name")) for item in result.get("columnHeaders", [])]
    values = (result.get("rows") or [[0] * len(headers)])[0]
    return dict(zip(headers, values))


def classify_error(exc: Exception) -> tuple[str, int | None]:
    http_status = getattr(getattr(exc, "resp", None), "status", None)
    raw = str(exc).lower()
    if "accessnotconfigured" in raw or "service_disabled" in raw or "has not been used" in raw:
        return "api_disabled", http_status
    if http_status in {401, 403}:
        return "permission_denied", http_status
    return "analytics_test_failed", http_status


def console_url(project_id: str) -> str:
    return (
        "https://console.cloud.google.com/apis/library/"
        f"youtubeanalytics.googleapis.com?project={project_id}"
    )


def load_credentials(path: Path) -> Credentials | None:
    if not path.exists():
        return None
    # Preserve the scopes actually recorded in the token; passing the desired
    # scopes here could make a legacy token appear upgraded before consent.
    return Credentials.from_authorized_user_file(str(path))


def authorize(cfg: Config) -> tuple[Credentials, dict[str, str], Path | None]:
    token_path = ROOT / cfg.yt_token
    write_status("awaiting_owner_consent", detail="Google browser consent is open")
    flow = InstalledAppFlow.from_client_secrets_file(str(resolve_client_secret(cfg)), SCOPES)
    options: dict[str, Any] = {
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
    }
    if cfg.youtube_login_hint:
        options["login_hint"] = cfg.youtube_login_hint
    credentials = flow.run_local_server(port=0, timeout_seconds=600, **options)
    if not credentials.has_scopes([ANALYTICS_SCOPE]):
        raise RuntimeError("Google consent completed without the required Analytics scope")
    write_status("validating_channel", detail="Consent received; checking channel identity")
    channel = verify_channel(cfg, credentials)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    candidate = token_path.with_suffix(".analytics-candidate.json")
    candidate.write_text(credentials.to_json(), encoding="utf-8")
    backup = None
    if token_path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = token_path.with_name(f"{token_path.stem}.pre-analytics-{stamp}{token_path.suffix}")
        shutil.copy2(token_path, backup)
    os.replace(candidate, token_path)
    return credentials, channel, backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-only", action="store_true")
    parser.add_argument("--open-console", action="store_true")
    parser.add_argument("--wait-minutes", type=int, default=0)
    args = parser.parse_args()
    cfg = Config("config.story.yaml")
    token_path = ROOT / cfg.yt_token
    project_id = ""
    try:
        secret = json.loads(resolve_client_secret(cfg).read_text(encoding="utf-8"))
        project_id = str((secret.get("installed") or secret.get("web") or {}).get("project_id") or "")
    except Exception:
        pass
    enable_url = console_url(project_id) if project_id else "https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com"

    try:
        credentials = load_credentials(token_path)
        backup = None
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.has_scopes([ANALYTICS_SCOPE]):
            if args.test_only:
                write_status(
                    "analytics_scope_missing", detail="One-time Google owner consent is required",
                    required_scope=ANALYTICS_SCOPE,
                )
                return 2
            credentials, channel, backup = authorize(cfg)
        else:
            channel = verify_channel(cfg, credentials)

        write_status("testing_analytics_api", channel=channel, detail="Checking live Analytics access")
        deadline = time.monotonic() + max(0, args.wait_minutes) * 60
        opened = False
        while True:
            try:
                sample = test_analytics(credentials)
                write_status(
                    "ready", channel=channel, scope=ANALYTICS_SCOPE,
                    detail="YouTube retention analytics is authorized and automatic",
                    test_metrics=sample, token_backup_created=bool(backup),
                )
                print("YouTube Analytics READY. Future retention collection is unattended.")
                return 0
            except Exception as exc:
                status, http_status = classify_error(exc)
                if status != "api_disabled" or time.monotonic() >= deadline:
                    write_status(
                        status, channel=channel, http_status=http_status,
                        detail="Enable YouTube Analytics API in the OAuth client project" if status == "api_disabled" else "Analytics verification failed",
                        enable_url=enable_url if status == "api_disabled" else None,
                    )
                    if status == "api_disabled" and args.open_console and not opened:
                        webbrowser.open(enable_url)
                    return 3
                if args.open_console and not opened:
                    write_status(
                        "waiting_for_api_enable", channel=channel,
                        detail="Enable the API in the opened Google Cloud page; this wizard will retest automatically",
                        enable_url=enable_url,
                    )
                    webbrowser.open(enable_url)
                    opened = True
                time.sleep(10)
    except Exception as exc:
        write_status("failed", error_type=type(exc).__name__, detail=str(exc)[:300])
        print(f"Analytics authorization failed safely: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
