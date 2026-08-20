#!/usr/bin/env python3
"""One bounded Meta queue, publishing, recovery and analytics cycle."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from src.config import Config, ROOT
from src import meta_analytics, meta_platform, platform_learning, youtube_timed_release


STATE_PATH = ROOT / "analytics" / "meta_scheduler_status.json"


def _read_status() -> dict:
    return meta_platform._read(STATE_PATH, {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.story.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--health-only", action="store_true")
    parser.add_argument("--limit", type=int, default=4)
    args = parser.parse_args()
    cfg = Config(args.config)
    started = datetime.now(timezone.utc)
    previous_state = _read_status()
    state = {
        "schema_version": 1, "started_at": started.isoformat().replace("+00:00", "Z"),
        "status": "running", "fail_closed": True,
    }
    meta_platform._write(STATE_PATH, state)
    try:
        health = meta_platform.health_check(cfg)
        state["health"] = health
        if args.health_only:
            state["status"] = "ready" if health.get("status") == "ready" else "setup_required"
        else:
            state["queue"] = meta_platform.reconcile_release_queue(cfg)
            state["youtube_queue"] = youtube_timed_release.summary()
            state["youtube_publish"] = (
                {"status": "dry_run"} if args.dry_run
                else youtube_timed_release.process_due(cfg, limit=args.limit)
            )
            state["publish"] = {"status": "dry_run"} if args.dry_run else meta_platform.process_due(cfg, limit=args.limit)
            previous = previous_state.get("analytics") or {}
            previous_at = meta_platform._parse_time(previous.get("checked_at"))
            refresh_hours = int(cfg.get("meta", "analytics_refresh_hours", default=4))
            should_refresh = health.get("status") == "ready" and (
                previous_at is None or started - previous_at >= timedelta(hours=refresh_hours)
            )
            state["analytics"] = meta_analytics.collect(cfg) if should_refresh and not args.dry_run else previous
            state["learning"] = (
                {"status": "dry_run"} if args.dry_run
                else {"status": "refreshed", "platforms": list(platform_learning.refresh(cfg).get("platforms", {}))}
            )
            publish_status = state["publish"].get("status")
            youtube_status = state["youtube_publish"].get("status")
            if publish_status in {"recovery_required", "credential_or_asset_error"} or youtube_status == "recovery_required":
                state["status"] = "recovery_required"
            elif health.get("status") != "ready":
                state["status"] = "setup_required"
            else:
                state["status"] = "healthy"
    except Exception as exc:
        state.update({"status": "failed_closed", "error_type": type(exc).__name__, "error": str(exc)[:500]})
    state["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    meta_platform._write(STATE_PATH, state)
    print(json.dumps({"status": state["status"], "queue": state.get("queue"), "publish": state.get("publish")}, indent=2))
    return 0 if state["status"] in {"healthy", "ready", "setup_required"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
