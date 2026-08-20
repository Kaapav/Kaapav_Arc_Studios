#!/usr/bin/env python3
"""Rerender an existing local job after cloud clips were attached."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import Config
from src import tts, video


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    args = ap.parse_args()
    job_dir = Path(args.job_dir).resolve()
    script_path = job_dir / "script.json"
    voice_path = job_dir / "voice.mp3"
    if not script_path.exists() or not voice_path.exists():
        raise SystemExit("The job must contain script.json and voice.mp3.")
    cfg = Config(str(ROOT / "config.yaml"))
    script = json.loads(script_path.read_text(encoding="utf-8"))
    timings = tts.synthesize(cfg, script["narration"], voice_path)
    output = job_dir / "video-cloud-motion.mp4"
    video.build_video(cfg, script, voice_path, timings, output)
    print(f"Saved review copy: {output}")
    print("This command never uploads. Review the file before publishing.")


if __name__ == "__main__":
    main()
