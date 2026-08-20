#!/usr/bin/env python3
"""Validate and attach a downloaded motion clip as an ordered scene candidate."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import episodes


def inspect_clip(path: Path) -> dict:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError("clip has no video stream")
    stream = streams[0]
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if duration < 1.0:
        raise RuntimeError(f"clip is too short ({duration:.2f}s)")
    if width < 256 or height < 256:
        raise RuntimeError(f"clip resolution is too small ({width}x{height})")
    return {"duration": round(duration, 3), "width": width, "height": height}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("episode", help="episode JSON path, e.g. content/echo100/episodes/ep002.json")
    parser.add_argument("scene", type=int, help="1-based scene number")
    parser.add_argument("provider", help="meta, kaggle-wan, colab-wan, hf-zerogpu, or other")
    parser.add_argument("clip", help="downloaded MP4 path")
    parser.add_argument("--last", action="store_true", help="append instead of making this the first candidate")
    args = parser.parse_args()

    episode_path = Path(args.episode)
    if not episode_path.is_absolute():
        episode_path = ROOT / episode_path
    clip = Path(args.clip).resolve()
    if not episode_path.exists() or not clip.exists():
        raise SystemExit("Episode JSON or motion clip does not exist")
    episode = json.loads(episode_path.read_text(encoding="utf-8"))
    scene_index = args.scene - 1
    if scene_index < 0 or scene_index >= len(episode.get("scenes", [])):
        raise SystemExit(f"Scene must be between 1 and {len(episode.get('scenes', []))}")

    probe = inspect_clip(clip)
    provider_slug = "".join(char if char.isalnum() or char in "-_" else "-" for char in args.provider.lower())
    target_dir = ROOT / "assets" / "motion" / episode["series_id"] / episode["episode_id"] / provider_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"scene-{args.scene:02d}{clip.suffix.lower() or '.mp4'}"
    temporary = target.with_name(target.name + ".tmp")
    shutil.copy2(clip, temporary)
    temporary.replace(target)

    relative = target.relative_to(ROOT).as_posix()
    candidate = {"provider": provider_slug, "path": relative, **probe}
    scene = episode["scenes"][scene_index]
    current = [item for item in scene.get("video_candidates", []) if not (
        isinstance(item, dict) and item.get("provider") == provider_slug
    )]
    scene["video_candidates"] = current + [candidate] if args.last else [candidate] + current
    series = episodes.load_series()
    episodes.validate_episode(episode_path, episode, series)
    temp_json = episode_path.with_name(episode_path.name + ".tmp")
    temp_json.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_json.replace(episode_path)
    print(f"Attached {provider_slug} -> {episode['episode_id']} scene {args.scene}: {relative}")
    print(f"Validated: {probe['width']}x{probe['height']} | {probe['duration']:.2f}s")


if __name__ == "__main__":
    main()
