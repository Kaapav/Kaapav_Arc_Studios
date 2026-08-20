#!/usr/bin/env python3
"""Render the improved ECHO//30 V2 Episode 1 Short locally.

The original published candidate is never modified. This renderer creates
portrait-safe crops from the eight locked V2 story frames and sends them
through the existing offline narration, caption, sound, and video pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from src.config import Config
from src import thumbnail, tts, video


ROOT = Path(__file__).resolve().parent
EPISODE_ROOT = ROOT / "content" / "echo100" / "v2" / "episode01"
SOURCE_ROOT = EPISODE_ROOT / "story_frames"
PORTRAIT_ROOT = EPISODE_ROOT / "vertical_frames"
CUTE_SOURCE_ROOT = (
    ROOT / "content" / "echo100" / "v2" / "cute_style" / "episode01" / "story_frames"
)

# Horizontal focal points chosen from the locked 16:9 compositions. Each crop
# protects the story subject needed by that scene instead of blindly centering.
FOCAL_X = (0.43, 0.34, 0.48, 0.32, 0.55, 0.48, 0.57, 0.50)


def portrait_crop(source: Path, destination: Path, focal_x: float) -> Path:
    image = Image.open(source).convert("RGB")
    target_ratio = 720 / 1280
    crop_width = round(image.height * target_ratio)
    center_x = round(image.width * focal_x)
    left = max(0, min(image.width - crop_width, center_x - crop_width // 2))
    cropped = image.crop((left, 0, left + crop_width, image.height))
    cropped = cropped.resize((720, 1280), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".part" + destination.suffix)
    cropped.save(temporary, quality=94, subsampling=0)
    temporary.replace(destination)
    return destination


def build_frames(style: str) -> list[Path]:
    if style == "cute":
        frames = [CUTE_SOURCE_ROOT / f"shot_{index:02d}.png" for index in range(1, 9)]
        missing = [str(path) for path in frames if not path.exists()]
        if missing:
            raise FileNotFoundError("Locked cute story frames missing: " + ", ".join(missing))
        return frames

    frames: list[Path] = []
    for index, focal_x in enumerate(FOCAL_X, 1):
        source = SOURCE_ROOT / f"shot_{index:02d}.png"
        if not source.exists():
            raise FileNotFoundError(f"Locked story frame missing: {source}")
        destination = PORTRAIT_ROOT / f"shot_{index:02d}_vertical.jpg"
        frames.append(portrait_crop(source, destination, focal_x))
    return frames


def main(style: str = "cute") -> None:
    frames = build_frames(style)
    output_root = ROOT / "output" / "story" / (
        "echo100-v2-episode01-cute-improved"
        if style == "cute"
        else "echo100-v2-episode01-improved"
    )
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
    })
    cfg.data.setdefault("voice", {})["word_timing_provider"] = "proportional"

    scene_data = [
        (
            "At 2:17 AM, Kavi's dead father's phone vibrated without a battery.",
            "push_in",
        ),
        (
            "The voice note was his own: At 3:57, Tara disappears. Don't trust Byte.",
            "pan_right",
        ),
        (
            "Behind him, Byte woke. Kavi hid the warning.",
            "pull_out",
        ),
        (
            "At the abandoned Neon Arcade, Tara was still broadcasting when the wall cracked.",
            "pan_left",
        ),
        (
            "A red door pushed through solid concrete. It existed on no city plan.",
            "push_in",
        ),
        (
            "Then Tara's radio caught the childhood name only her missing brother Imran knew.",
            "push_in",
        ),
        (
            "Kavi's phone warned: Do not open it alone. He connected Byte to the lock anyway.",
            "pan_right",
        ),
        (
            "The door opened. Mira waited inside. Kavi, she said, you are seventeen years late.",
            "pull_out",
        ),
    ]
    scenes = [
        {
            "text": text,
            "caption": text,
            "image_path": str(frames[index]),
            "effect": effect,
            "allow_stock_video": False,
        }
        for index, (text, effect) in enumerate(scene_data)
    ]
    script = {
        "title": "His Dead Father’s Phone Sent a Warning From Tomorrow | ECHO//30 Ep. 1",
        "description": (
            "A dead phone warns Kavi that Tara will disappear—and tells him not to trust Byte. "
            "Then a door erased from history appears inside the Neon Arcade.\n\n"
            "ECHO//30 is an original KAAPAV ARC Studios mystery series.\n\n"
            "This video uses original AI-assisted visuals and AI-generated narration."
        ),
        "tags": [
            "ECHO30", "animated mystery", "science fiction", "3D animation",
            "animated short", "mystery series", "KAAPAV ARC Studios", "shorts",
        ],
        "narration": " ".join(text for text, _ in scene_data),
        "scenes": scenes,
        "series_id": "echo100",
        "episode_id": f"echo100-v2-s01e001-{style}",
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
        "THE PHONE WARNED HIM",
        script["episode_id"],
        thumbnail_path,
        image_path=str(frames[0]),
        series_label="ECHO//30 • EPISODE 1",
    )
    metadata = {
        "title": script["title"],
        "description": script["description"],
        "tags": script["tags"],
        "status": "local_review_only",
        "uploaded": False,
        "source": f"echo100-v2-{style}-locked-frames",
    }
    (output_root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"READY FOR REVIEW: {video_path}")
    print(f"THUMBNAIL: {thumbnail_path}")
    print(f"WORD TIMINGS: {len(timings)}")
    print("UPLOAD STATUS: NOT UPLOADED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=("cute", "grounded"), default="cute")
    args = parser.parse_args()
    main(args.style)
