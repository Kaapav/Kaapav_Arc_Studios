"""Generate story frames for episodes stuck at images_pending.

Usage:
  python generate_story_frames.py --episode 18
  python generate_story_frames.py --episode 18 --force
  python generate_story_frames.py --all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.story_frame_gen import generate_episode_frames, generate_image_qc


def _find_episode(series_id: str, episode: int) -> Path | None:
    """Locate episode.json for a given series and episode number."""
    import json
    inventory = ROOT / "analytics" / "studio_inventory.json"
    try:
        data = json.loads(inventory.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for item in data.get("episodes", []):
        if item.get("series_id") == series_id and item.get("episode") == episode:
            path = Path(str(item.get("manifest_path") or ""))
            return path if path.exists() else None
    return None


def _images_pending_episodes() -> list[dict]:
    """Return all episodes in images_pending state."""
    import json
    inventory = ROOT / "analytics" / "studio_inventory.json"
    try:
        data = json.loads(inventory.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data.get("episodes", []) if e.get("state") == "images_pending"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", default="echo30", help="Series ID (default: echo30)")
    parser.add_argument("--episode", type=int, help="Episode number to generate")
    parser.add_argument("--all", action="store_true", help="Generate all images_pending episodes")
    parser.add_argument("--force", action="store_true", help="Regenerate even if frames exist")
    parser.add_argument("--limit", type=int, default=1, help="Max episodes to process in --all mode")
    args = parser.parse_args()

    if args.all:
        pending = _images_pending_episodes()[:args.limit]
        if not pending:
            print("No images_pending episodes found.")
            return 0
        targets = [(e["series_id"], e["episode"], Path(e["manifest_path"])) for e in pending
                   if e.get("manifest_path")]
    elif args.episode:
        path = _find_episode(args.series, args.episode)
        if not path:
            print(f"Episode {args.series} ep{args.episode:03d} not found in inventory.")
            return 1
        targets = [(args.series, args.episode, path)]
    else:
        parser.print_help()
        return 1

    exit_code = 0
    for series_id, ep_num, manifest in targets:
        print(f"--- Generating frames: {series_id} ep{ep_num:03d} ---")
        result = generate_episode_frames(manifest, force=args.force)
        print(f"  Status: {result['status']}")
        print(f"  Completed: {result['frames_generated']}/{result['total_scenes']}")
        if result["failed"]:
            print(f"  Failed: {', '.join(result['failed'])}")
            exit_code = 1
        if result["completed"]:
            qc_path = generate_image_qc(manifest, result["completed"])
            print(f"  QC: {qc_path}")
        print()

    if not exit_code:
        print("All done.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
