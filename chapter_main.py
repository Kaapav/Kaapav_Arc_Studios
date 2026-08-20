#!/usr/bin/env python3
"""Build a materially re-edited 16:9 ECHO//100 chapter from ten Shorts.

This is not a raw concatenation: it adds original bridge narration, chapter
cards, episode context, widescreen reframing, and a continuous chapter identity.
The result remains local until the adaptive growth controller unlocks it.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# MoviePy 1.0.3 still expects the Pillow alias removed in Pillow 10.
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)

from src.config import Config, ROOT
from src import episodes, tts


WIDTH, HEIGHT = 1280, 720


def _font(size: int, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False))


def _card(path: Path, heading: str, body: str, footer: str) -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), (4, 9, 20))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        red = int(12 + 35 * y / HEIGHT)
        blue = int(30 + 55 * (1 - y / HEIGHT))
        draw.line((0, y, WIDTH, y), fill=(red, 15, blue))
    draw.rounded_rectangle((70, 70, WIDTH - 70, HEIGHT - 70), radius=32,
                           outline=(55, 225, 255), width=4, fill=(5, 12, 28))
    draw.text((110, 110), heading, font=_font(30, True), fill=(55, 225, 255))
    draw.multiline_text((110, 220), _wrap(body, 34), font=_font(52, True),
                        fill=(245, 248, 255), spacing=12)
    draw.text((110, HEIGHT - 135), footer, font=_font(24), fill=(255, 90, 110))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=94)
    return path


def _overlay(path: Path, episode_number: int, title: str, arc: str) -> Path:
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    panel = (0, 0, 437, HEIGHT)
    draw.rectangle(panel, fill=(4, 9, 20, 245))
    draw.rectangle((842, 0, WIDTH, HEIGHT), fill=(4, 9, 20, 245))
    draw.rectangle((425, 0, 437, HEIGHT), fill=(55, 225, 255, 210))
    draw.rectangle((842, 0, 854, HEIGHT), fill=(255, 60, 90, 210))
    draw.text((45, 70), "ECHO//100", font=_font(30, True), fill=(55, 225, 255, 255))
    draw.multiline_text((45, 160), _wrap(title.split("|")[0].strip(), 18),
                        font=_font(39, True), fill=(245, 248, 255, 255), spacing=10)
    draw.text((45, HEIGHT - 105), arc.upper(), font=_font(20), fill=(255, 90, 110, 255))
    draw.text((900, 270), f"EPISODE\n{episode_number}/10", font=_font(38, True),
              fill=(245, 248, 255, 255), spacing=8)
    draw.text((900, 440), "WATCH THE\nFULL CHAPTER", font=_font(22),
              fill=(55, 225, 255, 255), spacing=7)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _episode_payload(number: int) -> dict:
    path = episodes.EPISODES_DIR / f"ep{number:03d}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    video_path = Path(payload.get("job_dir", "")) / "video.mp4"
    if not video_path.exists():
        raise FileNotFoundError(f"Episode {number} video is not ready: {video_path}")
    payload["video_path"] = str(video_path)
    return payload


def _bridge_clip(cfg: Config, work: Path, index: int, heading: str,
                 body: str, narration: str, footer: str):
    image_path = _card(work / f"bridge-{index:02d}.jpg", heading, body, footer)
    audio_path = work / f"bridge-{index:02d}.mp3"
    tts.synthesize(cfg, narration, audio_path)
    audio = AudioFileClip(str(audio_path))
    clip = ImageClip(str(image_path)).set_duration(audio.duration + 0.35).set_audio(audio)
    return clip, audio


def build_chapter(cfg: Config, chapter: int) -> Path:
    if not 1 <= chapter <= 10:
        raise ValueError("chapter must be between 1 and 10")
    start = (chapter - 1) * 10 + 1
    payloads = [_episode_payload(number) for number in range(start, start + 10)]
    arc = payloads[0].get("arc") or "The Red Door"
    output_dir = ROOT / "output" / "chapters" / f"chapter{chapter:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "video.mp4"
    if output_path.exists() and output_path.stat().st_size > 1_000_000:
        print(f"CHAPTER ALREADY READY: {output_path}")
        return output_path

    clips = []
    audio_refs = []
    video_refs = []
    intro_text = (
        f"A dead phone warned Kavi that tomorrow had already happened. "
        f"This is ECHO one hundred, Chapter {chapter}: {arc}."
    )
    intro, intro_audio = _bridge_clip(
        cfg, output_dir, 0, f"ECHO//100 • CHAPTER {chapter}",
        arc, intro_text, "AN ORIGINAL AI-ASSISTED SCI-FI STORY",
    )
    clips.append(intro)
    audio_refs.append(intro_audio)

    for position, payload in enumerate(payloads, 1):
        number = int(payload["episode"])
        if position > 1:
            hook = payload["scenes"][0]["text"]
            narration = f"But the previous answer created a new problem. {hook}"
            bridge, bridge_audio = _bridge_clip(
                cfg, output_dir, position, f"EPISODE {number}",
                payload["title"].split("|")[0].strip(), narration,
                "THE RED DOOR IS STILL OPEN",
            )
            clips.append(bridge)
            audio_refs.append(bridge_audio)

        source = VideoFileClip(payload["video_path"])
        video_refs.append(source)
        foreground = source.resize(height=HEIGHT).set_position((437, 0))
        background = ColorClip((WIDTH, HEIGHT), color=(4, 9, 20)).set_duration(source.duration)
        overlay_path = _overlay(
            output_dir / f"overlay-{number:03d}.png",
            position,
            payload["title"],
            arc,
        )
        overlay = ImageClip(str(overlay_path)).set_duration(source.duration)
        reframed = CompositeVideoClip(
            [background, foreground, overlay], size=(WIDTH, HEIGHT)
        ).set_duration(source.duration).set_audio(source.audio)
        clips.append(reframed)

    finale, finale_audio = _bridge_clip(
        cfg, output_dir, 11, "CHAPTER COMPLETE",
        "The next message is already waiting.",
        "The Red Door changed Kavi forever. The next chapter begins with the missing hour.",
        "SUBSCRIBE FOR ECHO//100 • CHAPTER 2",
    )
    clips.append(finale)
    audio_refs.append(finale_audio)

    final = concatenate_videoclips(clips, method="compose")
    temp = output_path.with_name("video.part.mp4")
    temp.unlink(missing_ok=True)
    try:
        final.write_videofile(
            str(temp), fps=24, codec="libx264", audio_codec="aac",
            preset="veryfast", threads=4, verbose=False, logger=None,
        )
        temp.replace(output_path)
        manifest = {
            "chapter": chapter,
            "episodes": list(range(start, start + 10)),
            "title": f"The Red Door Changed Everything | ECHO//100 Chapter {chapter}",
            "description": (
                f"Ten connected episodes become one complete chapter of ECHO//100: {arc}. "
                "Original AI-assisted animated fiction with original narration, editing, and sound design."
            ),
            "video_path": str(output_path),
            "status": "local_ready",
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        temp.unlink(missing_ok=True)
        final.close()
        for clip in video_refs:
            clip.close()
        for audio in audio_refs:
            audio.close()
    print(f"CHAPTER READY FOR QUALITY REVIEW: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", type=int, default=1)
    args = parser.parse_args()
    build_chapter(Config("config.story.yaml"), args.chapter)


if __name__ == "__main__":
    main()
