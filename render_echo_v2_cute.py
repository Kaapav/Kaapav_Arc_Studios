#!/usr/bin/env python3
"""Render a locked ECHO//30 cute-cinematic episode from its episode manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import Config
from src import growth_learning, provenance, thumbnail, tts, video
from src.release_audit import build_technical_qc


ROOT = Path(__file__).resolve().parent


def load_episode(manifest_path: Path) -> tuple[dict, list[Path]]:
    manifest_path = manifest_path.resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = ("episode", "episode_id", "output_slug", "title", "description", "tags", "scenes")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Episode manifest missing: {', '.join(missing)}")
    if not 1 <= int(data["episode"]) <= 30:
        raise ValueError("ECHO//30 episode number must be between 1 and 30")
    if len(data["scenes"]) != 8:
        raise ValueError("Each ECHO//30 Short must contain exactly eight story scenes")
    image_qc_path = manifest_path.parent / "image_qc.json"
    if not image_qc_path.exists():
        raise RuntimeError("Render blocked: image_qc.json is missing")
    image_qc = json.loads(image_qc_path.read_text(encoding="utf-8"))
    expected = {str(Path(scene["image"])).replace("\\", "/") for scene in data["scenes"]}
    accepted = {str(value).replace("\\", "/") for value in image_qc.get("accepted_frames", [])}
    if image_qc.get("status") != "accepted" or accepted != expected:
        raise RuntimeError("Render blocked: visual QC does not accept every exact story frame")

    frames: list[Path] = []
    for index, scene in enumerate(data["scenes"], 1):
        source = (manifest_path.parent / scene["image"]).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Scene {index} frame missing: {source}")
        frames.append(source)
    return data, frames


def render(manifest_path: Path) -> Path:
    episode, frames = load_episode(manifest_path)
    output_root = ROOT / "output" / "story" / episode["output_slug"]
    output_root.mkdir(parents=True, exist_ok=True)

    cfg = Config("config.story.yaml")
    cfg.data.setdefault("video", {}).update({
        "width": 720,
        "height": 1280,
        "fps": 24,
        "max_seconds": 58,
        "captions": True,
        "caption_font_size": 40,
        "caption_words_per_chunk": 4,
        "caption_vertical_position": 0.78,
        "caption_style": "cinematic",
        "stock_video": False,
        "background_music": True,
        "music_volume": 0.05,
        "sfx_volume": 0.12,
        "ken_burns": True,
        "memory_safe_compositor": True,
        "encoder_threads": 2,
    })
    cfg.data.setdefault("voice", {})["word_timing_provider"] = "proportional"

    scenes = [
        {
            "text": scene["text"],
            "caption": scene.get("caption", scene["text"]),
            "image_path": str(frames[index]),
            "effect": scene.get("effect", "push_in"),
            "allow_stock_video": False,
        }
        for index, scene in enumerate(episode["scenes"])
    ]
    traits = growth_learning.extract_traits(episode)
    script = {
        "title": episode["title"],
        "description": episode["description"],
        "tags": episode["tags"],
        "narration": " ".join(scene["text"] for scene in episode["scenes"]),
        "scenes": scenes,
        "series_id": "echo30",
        "episode_id": episode["episode_id"],
        "performance_traits": traits,
    }
    (output_root / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    voice_path = output_root / "voice.mp3"
    timings = tts.synthesize(cfg, script["narration"], voice_path)
    video_path = output_root / "video.mp4"
    video.build_video(cfg, script, voice_path, timings, video_path)

    thumbnail_path = output_root / "thumbnail.jpg"
    thumbnail.build_thumbnail(
        cfg,
        episode["thumbnail_text"],
        episode["episode_id"],
        thumbnail_path,
        image_path=str(frames[int(episode.get("thumbnail_scene", 1)) - 1]),
        series_label=f"ECHO//30 • EPISODE {episode['episode']}",
    )
    metadata = {
        "title": script["title"],
        "description": script["description"],
        "tags": script["tags"],
        "status": "local_review_only",
        "uploaded": False,
        "source": "echo30-v2-cute-locked-frames",
        "series_id": "echo30",
        "episode_id": episode["episode_id"],
        "episode": episode["episode"],
        "release_kind": "short",
        "performance_traits": traits,
    }
    (output_root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    provenance.write_rights_manifest(output_root, script, cfg)
    qc = build_technical_qc(video_path, len(scenes))
    (output_root / "qc_report.json").write_text(
        json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"READY FOR REVIEW: {video_path}")
    print(f"THUMBNAIL: {thumbnail_path}")
    print(f"WORD TIMINGS: {len(timings)}")
    print("UPLOAD STATUS: NOT UPLOADED")
    return video_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    render(args.manifest)
