#!/usr/bin/env python3
"""Maintain a rolling YouTube-native scheduled buffer for ECHO//100."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from src.config import Config
from src import episodes, quality, review, runtime
from src.upload import _get_service


IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


class MaintenanceLock:
    def __init__(self, cfg: Config):
        self.path = cfg.cache_dir() / "schedule-maintenance.lock"
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            pid = int(existing.get("pid", 0) or 0)
            age = time.time() - self.path.stat().st_mtime
            if runtime.pid_is_running(pid) or age <= 60:
                raise RuntimeError("Scheduled-buffer maintenance is already active")
            self.path.unlink(missing_ok=True)
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(self.fd, json.dumps({"pid": os.getpid(), "started": time.time()}).encode())
        os.close(self.fd)
        self.fd = None
        return self

    def __exit__(self, exc_type, exc, tb):
        self.path.unlink(missing_ok=True)


def _parse_publish_at(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _episode_path(episode_id: str) -> Path:
    return quality.episode_path(episode_id)


def _wait_for_renderer(cfg: Config, max_hours: float = 72.0) -> None:
    lock = cfg.cache_dir() / "pipeline.lock"
    deadline = time.time() + max_hours * 60 * 60
    announced = False
    while lock.exists():
        try:
            lock_data = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:
            lock_data = {}
        lock_pid = int(lock_data.get("pid", 0) or 0)
        if lock_pid and not runtime.pid_is_running(lock_pid):
            print(f"[buffer] Recovering dead renderer lock from PID {lock_pid}")
            lock.unlink(missing_ok=True)
            break
        if not announced:
            print(f"[buffer] Existing renderer active; waiting for {lock}")
            announced = True
        if time.time() >= deadline:
            raise RuntimeError("Timed out waiting for the active renderer")
        time.sleep(30)


def _refresh_scheduled(cfg: Config, items: list[dict]) -> list[dict]:
    scheduled = [x for x in items if x.get("status") == "scheduled" and x.get("youtube_id")]
    if not scheduled:
        return items
    service = _get_service(cfg)
    by_id = {x["youtube_id"]: x for x in scheduled}
    response = service.videos().list(
        part="status", id=",".join(by_id), maxResults=50
    ).execute()
    changed = False
    for video in response.get("items", []):
        item = by_id.get(video.get("id"))
        if not item:
            continue
        status = video.get("status", {})
        if status.get("privacyStatus") == "public":
            item["status"] = "approved"
            ep_path = _episode_path(item["episode_id"])
            episodes.update(
                ep_path,
                "published",
                published_at=dt.datetime.now(IST).isoformat(timespec="seconds"),
                youtube_id=item["youtube_id"],
                youtube_url=item["youtube_url"],
                review_id=item["id"],
                last_error=None,
            )
            changed = True
        elif item.get("publish_at"):
            due = _parse_publish_at(item["publish_at"])
            if due < dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1):
                raise RuntimeError(
                    f"YouTube did not publish {item['episode_id']} by {item['publish_at']}; "
                    "scheduled-buffer maintenance stopped"
                )
    if changed:
        review.save_queue(cfg, items)
    return items


def _next_slots(items: list[dict], count: int, hour: int, minute: int) -> list[str]:
    now = dt.datetime.now(IST)
    future = []
    for item in items:
        value = item.get("publish_at")
        if item.get("status") == "scheduled" and value:
            when = _parse_publish_at(value).astimezone(IST)
            if when > now:
                future.append(when)
    if future:
        day = max(future).date() + dt.timedelta(days=1)
    else:
        day = now.date() + dt.timedelta(days=1)
    slots = []
    for offset in range(count):
        local = dt.datetime.combine(day + dt.timedelta(days=offset), dt.time(hour, minute), IST)
        slots.append(local.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    return slots


def _remaining_episode_count() -> int:
    """Return episodes that still need a future YouTube publication slot."""
    remaining = 0
    for path in episodes.EPISODES_DIR.glob("ep*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") not in {"published", "failed"}:
            remaining += 1
    return remaining


def maintain(cfg: Config, target: int | None, hour: int, minute: int, wait: bool) -> None:
    with MaintenanceLock(cfg):
        if wait:
            _wait_for_renderer(cfg)
        elif (cfg.cache_dir() / "pipeline.lock").exists():
            raise RuntimeError("Renderer is active; rerun with --wait-for-render")

        items = _refresh_scheduled(cfg, review.load_queue(cfg))
        if target is None:
            target = _remaining_episode_count()
            print(f"[vault] Full-series mode: {target} unpublished episode(s) remain")
        now = dt.datetime.now(dt.timezone.utc)
        future_scheduled = [
            item for item in items
            if item.get("status") == "scheduled"
            and item.get("publish_at")
            and _parse_publish_at(item["publish_at"]) > now
        ]
        pending = [
            item for item in items
            if item.get("status") == "pending" and item.get("series_id") == "echo100"
        ]
        missing = max(0, target - len(future_scheduled) - len(pending))
        if missing:
            print(f"[buffer] Rendering {missing} episode(s) to reach target {target}")
            subprocess.run(
                [sys.executable, str(Path(__file__).with_name("render_vault.py")),
                 "--count", str(missing)],
                cwd=Path(__file__).parent,
                check=True,
            )

        items = review.load_queue(cfg)
        pending = sorted(
            [x for x in items if x.get("status") == "pending" and x.get("series_id") == "echo100"],
            key=lambda x: x.get("episode_id", ""),
        )
        capacity = max(0, target - len(future_scheduled))
        selected = pending[:capacity]
        slots = _next_slots(items, len(selected), hour, minute)
        for item, publish_at in zip(selected, slots):
            quality.assert_publishable(item)
            print(review.schedule(cfg, item["id"], publish_at))
            ep_path = _episode_path(item["episode_id"])
            episodes.update(
                ep_path,
                "scheduled",
                publish_at=publish_at,
                youtube_id=next(
                    x for x in review.load_queue(cfg) if x["id"] == item["id"]
                )["youtube_id"],
                youtube_url=next(
                    x for x in review.load_queue(cfg) if x["id"] == item["id"]
                )["youtube_url"],
                review_id=item["id"],
                last_error=None,
            )
        print(
            f"SCHEDULE BUFFER READY: {len(future_scheduled) + len(selected)}/{target} future episode(s)"
        )


def main() -> None:
    raise SystemExit(
        "maintain_schedule.py is retired. The only active scheduler is "
        "studio_autopilot.py under studio_supervisor.py."
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=15)
    parser.add_argument(
        "--all-episodes",
        action="store_true",
        help="render and schedule every unpublished ECHO//100 episode",
    )
    parser.add_argument("--time", default="09:00")
    parser.add_argument("--wait-for-render", action="store_true")
    args = parser.parse_args()
    hour, minute = (int(x) for x in args.time.split(":", 1))
    if not 1 <= args.target <= 100 or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise SystemExit("Invalid target or publish time")
    legacy_bulk = args.all_episodes or args.target > 7
    if legacy_bulk and os.getenv("ALLOW_LEGACY_BULK_SCHEDULE") != "I_UNDERSTAND":
        raise SystemExit(
            "Bulk scheduling is disabled by the adaptive monetization strategy. "
            "Use growth_controller.py."
        )
    target = None if args.all_episodes else args.target
    maintain(Config("config.story.yaml"), target, hour, minute, args.wait_for_render)


if __name__ == "__main__":
    main()
