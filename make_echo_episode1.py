#!/usr/bin/env python3
"""Render ECHO//100 Episode 1 locally without uploading."""

import datetime as dt
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.config import Config
from src import tts, video


ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets" / "episodes" / "echo100" / "ep01"


def _font(size):
    for candidate in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/Arial.ttf"):
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def build_thumbnail(source: Path, out: Path):
    image = Image.open(source).convert("RGB")
    image = image.resize((720, 1280), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, 720, 310), fill=(0, 0, 0, 160))
    draw.text((42, 48), "THE DEAD", font=_font(70), fill=(255, 255, 255, 255))
    draw.text((42, 128), "PHONE", font=_font(92), fill=(75, 210, 255, 255))
    draw.text((44, 240), "ECHO//100 • EPISODE 1", font=_font(28), fill=(230, 230, 230, 255))
    image.save(out, quality=92)


def main():
    cfg = Config()
    cfg.data.setdefault("video", {})["ken_burns"] = True
    cfg.data["video"]["stock_video"] = False
    cfg.data["video"]["caption_font_size"] = 48
    cfg.data.setdefault("voice", {})["word_timing_provider"] = "proportional"

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    job = cfg.output_dir() / f"echo100-ep01-the-dead-phone-{stamp}"
    job.mkdir(parents=True, exist_ok=True)

    scenes = [
        {
            "text": "At midnight, Ishan's dead phone lit up.",
            "caption": "The dead phone woke up",
            "image_path": str(ASSET_DIR / "scene-01-phone.png"),
        },
        {
            "text": "The message said: Ishan, don't upload tonight.",
            "caption": "Don't upload tonight",
            "image_path": str(ASSET_DIR / "scene-01-phone.png"),
        },
        {
            "text": "He picked it up. One percent battery.",
            "caption": "Only one percent",
            "image_path": str(ASSET_DIR / "scene-02-ishan.png"),
        },
        {
            "text": "Then the phone answered: My name is Echo.",
            "caption": "My name is Echo",
            "image_path": str(ASSET_DIR / "scene-02-ishan.png"),
        },
        {
            "text": "At 12:07, Tara called.",
            "caption": "Tara called at 12:07",
            "image_path": str(ASSET_DIR / "scene-03-call.png"),
        },
        {
            "text": "Your father's account just uploaded a video.",
            "caption": "His account uploaded",
            "image_path": str(ASSET_DIR / "scene-03-call.png"),
        },
        {
            "text": "Tara arrived. The message changed: That is not your father.",
            "caption": "That is not him",
            "image_path": str(ASSET_DIR / "scene-04-tara.png"),
        },
        {
            "text": "Outside, a car stopped. Echo whispered: They found me.",
            "caption": "They found Echo",
            "image_path": str(ASSET_DIR / "scene-05-rooftop.png"),
        },
    ]
    script = {
        "title": "The Dead Phone | ECHO//100 — Episode 1",
        "description": "A new mystery begins. ECHO//100 is an original AI-assisted fiction series from AI Creative Explorer.\n\nThis episode uses AI-generated narration and visuals.",
        "tags": ["echo100", "scifi short", "mystery series", "ai story", "webseries"],
        "narration": " ".join(scene["text"] for scene in scenes),
        "scenes": scenes,
    }
    (job / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    voice_path = job / "voice.mp3"
    timings = tts.synthesize(cfg, script["narration"], voice_path)
    video_path = job / "video.mp4"
    video.build_video(cfg, script, voice_path, timings, video_path)
    thumb_path = job / "thumbnail.jpg"
    build_thumbnail(ASSET_DIR / "scene-01-phone.png", thumb_path)
    (job / "metadata.json").write_text(json.dumps({
        "title": script["title"],
        "description": script["description"],
        "tags": script["tags"],
        "status": "local_review_only",
        "uploaded": False,
    }, indent=2), encoding="utf-8")
    print(f"Episode complete: {video_path}")
    print(f"Thumbnail: {thumb_path}")
    print(f"Word timings: {len(timings)}")
    print("Upload status: NOT UPLOADED")


if __name__ == "__main__":
    main()
