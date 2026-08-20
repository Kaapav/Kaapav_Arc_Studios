#!/usr/bin/env python3
"""Render benchmark-ready episodes into a local approval/publish vault."""

from __future__ import annotations

import argparse
import json

from src.config import Config
from src import episodes, runtime
from story_main import run_one


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    cfg = Config("config.story.yaml")
    rendered = 0
    # Hold one lock across the entire buffer so a second scheduler cannot claim
    # the next episode between iterations.
    # Full-series rendering is intentionally allowed to run for multiple days.
    with runtime.RunLock(cfg, stale_after_seconds=72 * 60 * 60):
        for _ in range(max(0, args.count)):
            if not any(
                json.loads(path.read_text(encoding="utf-8")).get("status") == "ready"
                for path in episodes.EPISODES_DIR.glob("ep*.json")
            ):
                break
            result = run_one(cfg, do_upload=False, dry_run=False)
            if result is None:
                break
            rendered += 1
    print(f"VAULT RENDER COMPLETE: {rendered} episode(s) prepared; nothing uploaded")


if __name__ == "__main__":
    main()
