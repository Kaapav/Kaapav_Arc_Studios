#!/usr/bin/env python3
"""Attach a complete folder of scene-XX.mp4 Meta clips to one episode."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("episode", help="Episode JSON path")
    parser.add_argument("folder", help="Folder containing scene-01.mp4, scene-02.mp4, ...")
    parser.add_argument("--provider", default="meta")
    args = parser.parse_args()

    episode_path = Path(args.episode)
    if not episode_path.is_absolute():
        episode_path = ROOT / episode_path
    folder = Path(args.folder)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not episode_path.exists():
        raise SystemExit(f"Episode JSON missing: {episode_path}")
    if not folder.exists():
        raise SystemExit(f"Clip folder missing: {folder}")

    episode = json.loads(episode_path.read_text(encoding="utf-8"))
    expected = len(episode.get("scenes", []))
    clips = [folder / f"scene-{index:02d}.mp4" for index in range(1, expected + 1)]
    missing = [str(path) for path in clips if not path.exists()]
    if missing:
        raise SystemExit("Missing Meta clips:\n  " + "\n  ".join(missing))

    ingest = ROOT / "tools" / "ingest_motion.py"
    for index, clip in enumerate(clips, start=1):
        subprocess.run(
            [
                sys.executable, str(ingest), str(episode_path), str(index),
                args.provider, str(clip),
            ],
            cwd=ROOT,
            check=True,
        )
    print(f"READY: attached {expected} {args.provider} clips to {episode['episode_id']}")


if __name__ == "__main__":
    main()
