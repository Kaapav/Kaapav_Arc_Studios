#!/usr/bin/env python3
"""Refresh YouTube views/likes/comments locally and optionally in Google Sheets."""

import argparse
import traceback

from src.config import Config
from src import growth_learning, performance, youtube_analytics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.story.yaml")
    parser.add_argument("--no-google", action="store_true")
    args = parser.parse_args()
    cfg = Config(args.config)
    try:
        summary, rows = performance.collect(cfg)
        current_path, history_path, history = performance.save_local(
            rows, channel_id=summary["channel_id"]
        )
        detailed = youtube_analytics.collect(cfg, rows)
        learning = growth_learning.refresh_learning(
            cfg, rows, detailed_metrics=detailed.get("videos", {})
        )
        growth_learning.write_production_directives()
        google_url = None
        if not args.no_google:
            try:
                google_url = performance.sync_google_sheet(
                    cfg, rows, history, summary=summary
                )
            except Exception as exc:
                print(f"[tracker] Google Sheets unavailable; local data preserved ({exc})")
        performance.write_status(summary, current_path, history_path, google_url)
        print(
            f"TRACKED {len(rows)} videos | {summary['subscribers']} subscribers | "
            f"{summary['channel_views']} channel views"
        )
        print(f"Current: {current_path}")
        print(f"History: {history_path}")
        print(f"Google Sheet: {google_url or 'not configured'}")
        print(
            f"Learning: {len(learning.get('observations', []))} mature observations | "
            f"retention API={detailed.get('status')}"
        )
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
