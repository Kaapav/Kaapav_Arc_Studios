#!/usr/bin/env python3
"""Legacy ten-episode ECHO//30 compilation builder (Episodes 1-10 only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
SERIES_ROOT = ROOT / "content" / "echo100" / "v2" / "cute_style"
MANIFEST = SERIES_ROOT / "release_manifest.json"
FONT_BOLD = Path(r"C:\Windows\Fonts\arialbd.ttf")
FONT_REGULAR = Path(r"C:\Windows\Fonts\arial.ttf")
AMBIENT = ROOT / "assets" / "audio" / "echo100" / "echo100-ambient-bed.wav"
WIDTH = 1920
HEIGHT = 1080
FPS = 24


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def duration(path: Path) -> float:
    value = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True)
    return float(value.strip())


def cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    ratio = max(target_w / image.width, target_h / image.height)
    resized = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def fit_font(text: str, max_width: int, start_size: int, min_size: int = 38) -> ImageFont.FreeTypeFont:
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(str(FONT_BOLD), size)
        box = font.getbbox(text)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(str(FONT_BOLD), min_size)


def draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.FreeTypeFont,
                  fill: tuple[int, int, int], stroke: int = 0) -> None:
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    x = (WIDTH - (box[2] - box[0])) // 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke,
              stroke_fill=(0, 0, 0))


def make_card(background_path: Path, destination: Path, eyebrow: str, headline: str,
              subline: str) -> None:
    with Image.open(background_path) as source:
        canvas = cover(source.convert("RGB"), (WIDTH, HEIGHT))
    canvas = canvas.filter(ImageFilter.GaussianBlur(9))
    canvas = ImageEnhance.Brightness(canvas).enhance(0.28)
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (4, 9, 18, 90))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH, 16), fill=(36, 214, 255, 255))
    eyebrow_font = ImageFont.truetype(str(FONT_BOLD), 48)
    headline_font = fit_font(headline, 1640, 120, 58)
    subline_font = ImageFont.truetype(str(FONT_REGULAR), 44)
    draw_centered(draw, eyebrow, 250, eyebrow_font, (54, 220, 255), 2)
    draw_centered(draw, headline, 395, headline_font, (255, 210, 42), 3)
    draw_centered(draw, subline, 585, subline_font, (242, 246, 255), 2)
    brand = ImageFont.truetype(str(FONT_BOLD), 36)
    draw.text((56, 974), "KAAPAV ARC Studios", font=brand, fill=(255, 255, 255),
              stroke_width=2, stroke_fill=(0, 0, 0))
    canvas.convert("RGB").save(destination, quality=95)


def make_thumbnail(background_path: Path, destination: Path, start: int, end: int) -> None:
    with Image.open(background_path) as source:
        canvas = cover(source.convert("RGB"), (1280, 720))
    canvas = ImageEnhance.Brightness(canvas).enhance(0.36)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1280, 720), outline=(43, 220, 255), width=12)
    brand = ImageFont.truetype(str(FONT_BOLD), 32)
    draw.text((32, 24), "KAAPAV ARC Studios", font=brand, fill="white",
              stroke_width=2, stroke_fill="black")
    headline = ImageFont.truetype(str(FONT_BOLD), 72)
    draw.text((72, 240), f"{end - start + 1} EPISODES.", font=headline,
              fill=(255, 210, 42), stroke_width=4, stroke_fill="black")
    draw.text((72, 330), "ONE DOOR.", font=headline,
              fill=(255, 210, 42), stroke_width=4, stroke_fill="black")
    label = ImageFont.truetype(str(FONT_BOLD), 36)
    draw.rounded_rectangle((68, 505, 610, 580), radius=15, fill=(7, 18, 32))
    draw.text((92, 522), f"ECHO//30 • EPISODES {start}–{end}", font=label,
              fill=(54, 220, 255))
    canvas.save(destination, quality=96)


def encode_card(image: Path, output: Path, seconds: float) -> None:
    command = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(image)]
    if AMBIENT.exists():
        command += ["-stream_loop", "-1", "-i", str(AMBIENT)]
        audio_map = ["-map", "0:v", "-map", "1:a"]
        audio_filter = ["-af", "volume=0.08,afade=t=in:st=0:d=0.25,afade=t=out:st={}:d=0.35".format(max(0.0, seconds - 0.35))]
    else:
        command += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        audio_map = ["-map", "0:v", "-map", "1:a"]
        audio_filter = []
    command += [
        *audio_map, "-t", str(seconds), "-r", str(FPS),
        "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p", *audio_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-level", "4.1", "-g", "48",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-shortest", str(output),
    ]
    run(command)


def encode_episode(source: Path, output: Path) -> None:
    filter_graph = (
        f"[0:v]split=2[background][foreground];"
        f"[background]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},boxblur=30:1,eq=brightness=-0.34:saturation=0.72[stage];"
        f"[foreground]scale=-2:{HEIGHT}[portrait];"
        f"[stage][portrait]overlay=(W-w)/2:0,format=yuv420p[video]"
    )
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-filter_complex", filter_graph,
        "-map", "[video]", "-map", "0:a:0",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-level", "4.1", "-g", "48",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        str(output),
    ])


def timestamp(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def original_story_frame(number: int, fallback: Path) -> Path:
    episode_root = SERIES_ROOT / f"episode{number}"
    episode_manifest = episode_root / "episode.json"
    if episode_manifest.is_file():
        payload = read_json(episode_manifest)
        index = int(payload.get("thumbnail_scene", 1)) - 1
        scenes = payload.get("scenes", [])
        if 0 <= index < len(scenes):
            candidate = (episode_manifest.parent / scenes[index]["image"]).resolve()
            if candidate.is_file():
                return candidate
    candidate = episode_root / "story_frames" / "shot_01.png"
    return candidate if candidate.is_file() else fallback


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_episode(number: int) -> tuple[dict, Path, Path, Path, Path]:
    manifest_path = SERIES_ROOT / f"episode{number}" / "episode.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Episode {number} manifest is missing")
    manifest = read_json(manifest_path)
    output = ROOT / "output" / "story" / str(manifest.get("output_slug") or "")
    video = output / "video.mp4"
    thumbnail = output / "thumbnail.jpg"
    audit_path = output / "prepublish_audit.json"
    metadata_path = output / "metadata.json"
    if not all(path.exists() for path in (video, thumbnail, audit_path, metadata_path)):
        raise FileNotFoundError(f"Episode {number} is not fully rendered and audited")
    audit = read_json(audit_path)
    metadata = read_json(metadata_path)
    if audit.get("status") != "passed" or not audit.get("fail_closed"):
        raise ValueError(f"Episode {number} does not have a passing strict audit")
    expected_hash = ((audit.get("inputs") or {}).get("video") or {}).get("sha256")
    if not expected_hash or file_sha256(video) != expected_hash:
        raise ValueError(f"Episode {number} video changed after its strict audit")
    if metadata.get("status") not in {"scheduled", "public"}:
        raise ValueError(f"Episode {number} must be future-scheduled or public before compilation")
    item = {
        "episode": number,
        "title": metadata.get("title") or manifest.get("title"),
        "publish_at": metadata.get("publish_at"),
    }
    return item, video, thumbnail, original_story_frame(number, thumbnail), audit_path


def _legacy_build(start: int, end: int, reuse_episode_encodes: bool = False) -> Path:
    if end - start + 1 != 5:
        raise ValueError("Compilation blocks must contain exactly five consecutive episodes")
    episodes = [source_episode(number) for number in range(start, end + 1)]

    output = ROOT / "output" / "story" / f"echo30-compilation-episodes{start:02d}-{end:02d}"
    work = output / "work"
    work.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []

    intro_image = work / "intro.jpg"
    make_card(episodes[-1][3], intro_image, "ECHO//30 — CHAPTER ONE",
              "THE FIRST DOOR", f"COMPLETE EPISODES {start}–{end}")
    intro_clip = work / "segment_000_intro.mp4"
    encode_card(intro_image, intro_clip, 6.0)
    segments.append(intro_clip)
    timeline = 6.0
    chapters: list[tuple[float, str]] = [(0.0, "The First Door — Introduction")]

    for offset, (item, video, thumbnail, story_frame, audit_path) in enumerate(episodes, 1):
        number = int(item["episode"])
        card_image = work / f"card_{number:02d}.jpg"
        hook = item["title"].split(" | ")[0]
        make_card(story_frame, card_image, f"ECHO//30 • EPISODE {number}", hook,
                  "THE FIRST DOOR")
        card_clip = work / f"segment_{offset:03d}a_card.mp4"
        encode_card(card_image, card_clip, 2.0)
        segments.append(card_clip)
        chapters.append((timeline, f"Episode {number}: {hook}"))
        timeline += duration(card_clip)

        episode_clip = work / f"segment_{offset:03d}b_episode.mp4"
        if not reuse_episode_encodes or not episode_clip.is_file():
            encode_episode(video, episode_clip)
        segments.append(episode_clip)
        timeline += duration(episode_clip)

    outro_image = work / "outro.jpg"
    make_card(episodes[-1][3], outro_image, "ECHO//30 CONTINUES",
              "THE LOOP IS GETTING SHORTER", "EPISODE 11 OPENS THE NEXT DOOR")
    outro_clip = work / "segment_999_outro.mp4"
    encode_card(outro_image, outro_clip, 6.0)
    segments.append(outro_clip)

    concat_list = work / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{segment.as_posix()}'\n" for segment in segments),
        encoding="utf-8",
    )
    final_video = output / "video.mp4"
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart",
        str(final_video),
    ])

    make_thumbnail(episodes[-1][3], output / "thumbnail.jpg", start, end)
    description_chapters = "\n".join(f"{timestamp(at)} {label}" for at, label in chapters)
    metadata = {
        "title": f"10 Episodes. One Door. | ECHO//30 Chapter 1 (Episodes {start}–{end})",
        "description": (
            "A dead phone speaks from tomorrow. A missing sister is erased from every record. "
            "A Red Door trades human lives—and a future Kavi orders it sealed.\n\n"
            f"Watch the complete first chapter of ECHO//30, Episodes {start}–{end}, as one cinematic story.\n\n"
            f"CHAPTERS\n{description_chapters}\n\n"
            "ECHO//30 is an original sci-fi mystery animated series from KAAPAV ARC Studios.\n\n"
            "Subscribe: https://www.youtube.com/@kaapavarcstudios?sub_confirmation=1\n\n"
            "#ECHO30 #AnimatedSeries #SciFiAnimation"
        ),
        "tags": [
            "ECHO30", "KAAPAV ARC Studios", "animated series", "full animated story",
            "3D animation", "sci fi mystery", "time loop story", "animated movie",
            "cinematic animation", "original animation",
        ],
        "status": "local_review_only",
        "uploaded": False,
        "source": f"echo30-episodes-{start:02d}-{end:02d}-compilation-v1",
    }
    write_json(output / "metadata.json", metadata)

    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(final_video),
    ], text=True))
    run(["ffmpeg", "-v", "error", "-i", str(final_video), "-f", "null", os.devnull])
    final_duration = float(probe["format"]["duration"])
    contact = output / "qc_contact.jpg"
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(final_video),
        "-vf", f"fps={12 / final_duration},scale=480:-1,tile=4x3",
        "-frames:v", "1", str(contact),
    ])
    video_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    errors = []
    if (video_stream.get("width"), video_stream.get("height")) != (WIDTH, HEIGHT):
        errors.append("final compilation is not 1920x1080")
    if final_duration < 420:
        errors.append("final compilation is unexpectedly shorter than seven minutes")
    qc = {
        "ok": not errors,
        "full_decode": "passed",
        "duration_seconds": final_duration,
        "episode_range": [start, end],
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "contact_sheet": str(contact),
        "errors": errors,
    }
    write_json(output / "qc_report.json", qc)
    if errors:
        raise RuntimeError("Compilation QC failed: " + "; ".join(errors))
    print(f"READY FOR REVIEW: {final_video}")
    print(f"THUMBNAIL: {output / 'thumbnail.jpg'}")
    print(f"DURATION: {final_duration:.2f}s")
    print("UPLOAD STATUS: NOT UPLOADED")
    return final_video


def build(start: int, end: int, reuse_episode_encodes: bool = False) -> Path:
    """Build the current five-episode weekend compilation and audit it locally."""
    if end - start + 1 != 5:
        raise ValueError("Compilation blocks must contain exactly five consecutive episodes")
    episodes = [source_episode(number) for number in range(start, end + 1)]
    output = ROOT / "output" / "story" / f"echo30-compilation-episodes{start:02d}-{end:02d}"
    work = output / "work"
    work.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []

    intro_image = work / "intro.jpg"
    make_card(
        episodes[-1][3], intro_image, "ECHO//30 — COMPLETE ARC",
        "FIVE EPISODES. ONE STORY.", f"EPISODES {start}–{end}",
    )
    intro_clip = work / "segment_000_intro.mp4"
    encode_card(intro_image, intro_clip, 6.0)
    segments.append(intro_clip)
    timeline = 6.0
    chapters: list[tuple[float, str]] = [(0.0, f"Episodes {start}–{end} — Introduction")]

    for offset, (item, video, thumbnail, story_frame, audit_path) in enumerate(episodes, 1):
        number = int(item["episode"])
        hook = str(item["title"]).split(" | ")[0]
        card_image = work / f"card_{number:02d}.jpg"
        make_card(
            story_frame, card_image, f"ECHO//30 • EPISODE {number}", hook,
            f"COMPLETE ARC {start}–{end}",
        )
        card_clip = work / f"segment_{offset:03d}a_card.mp4"
        encode_card(card_image, card_clip, 2.0)
        segments.append(card_clip)
        chapters.append((timeline, f"Episode {number}: {hook}"))
        timeline += duration(card_clip)
        episode_clip = work / f"segment_{offset:03d}b_episode.mp4"
        if not reuse_episode_encodes or not episode_clip.exists():
            encode_episode(video, episode_clip)
        segments.append(episode_clip)
        timeline += duration(episode_clip)

    outro_image = work / "outro.jpg"
    make_card(
        episodes[-1][3], outro_image, "ECHO//30 CONTINUES",
        "THE NEXT CHOICE CHANGES EVERYTHING", f"EPISODE {end + 1} OPENS THE NEXT DOOR",
    )
    outro_clip = work / "segment_999_outro.mp4"
    encode_card(outro_image, outro_clip, 6.0)
    segments.append(outro_clip)
    concat_list = work / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{segment.as_posix()}'\n" for segment in segments), encoding="utf-8"
    )
    final_video = output / "video.mp4"
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart", str(final_video),
    ])
    thumbnail_path = output / "thumbnail.jpg"
    make_thumbnail(episodes[-1][3], thumbnail_path, start, end)
    description_chapters = "\n".join(f"{timestamp(at)} {label}" for at, label in chapters)
    metadata = {
        "title": f"5 Episodes. One Story. | ECHO//30 Episodes {start}–{end}",
        "description": (
            "A dead phone speaks from tomorrow. A missing sister is erased from every record. "
            "A Red Door trades human lives—and each rescue changes who survives.\n\n"
            f"Watch five connected ECHO//30 episodes, {start}–{end}, as one cinematic story.\n\n"
            f"CHAPTERS\n{description_chapters}\n\n"
            "ECHO//30 is an original sci-fi mystery animated series from KAAPAV ARC Studios.\n\n"
            "Subscribe: https://www.youtube.com/@kaapavarcstudios?sub_confirmation=1\n\n"
            "#ECHO30 #AnimatedSeries #SciFiAnimation"
        ),
        "tags": [
            "ECHO30", "KAAPAV ARC Studios", "animated series", "full animated story",
            "3D animation", "sci fi mystery", "time loop story", "animated movie",
            "cinematic animation", "original animation",
        ],
        "status": "local_review_only",
        "uploaded": False,
        "source": f"echo30-episodes-{start:02d}-{end:02d}-compilation-v2",
        "series_id": "echo30",
        "release_kind": "compilation",
        "episode_count": 5,
        "episode_start": start,
        "episode_end": end,
        "thumbnail_path": str(thumbnail_path),
    }
    write_json(output / "metadata.json", metadata)
    from src.packaging import write_longform_variants
    write_longform_variants(output, metadata)
    write_json(output / "compilation_manifest.json", {
        "schema_version": 1,
        "series_id": "echo30",
        "episode_count": 5,
        "episodes": [
            {
                "episode": int(item["episode"]),
                "video_path": str(video),
                "audit_path": str(audit_path),
                "publish_at": item.get("publish_at"),
            }
            for item, video, thumbnail, story_frame, audit_path in episodes
        ],
    })
    write_json(output / "rights_manifest.json", {
        "schema_version": 1,
        "rights_status": "cleared",
        "unresolved_assets": [],
        "story": {
            "origin": "compilation of five original KAAPAV ARC Studios episodes",
            "third_party_adaptation": False,
        },
        "visuals": {
            "origin": "strictly audited source episodes and locally generated editorial cards",
            "stock_media_used": False,
            "frame_hashes": [],
        },
        "voice": {"origin": "audited source episode narration"},
        "music_and_sfx": {
            "origin": "audited source audio plus deterministic local KAAPAV audio",
            "stock_track_used": False,
        },
        "named_studio_imitation_requested": False,
    })
    from src.release_audit import build_technical_qc, run_publish_audit
    from src.config import Config

    qc = build_technical_qc(final_video, 12)
    stream = qc.get("video_stream") or {}
    if (stream.get("width"), stream.get("height")) != (WIDTH, HEIGHT):
        qc.setdefault("errors", []).append("final compilation is not 1920x1080")
    if float(qc.get("duration_seconds") or 0) < 120:
        qc.setdefault("errors", []).append("final compilation is unexpectedly shorter than two minutes")
    qc["ok"] = not qc.get("errors")
    qc["episode_range"] = [start, end]
    write_json(output / "qc_report.json", qc)
    if not qc["ok"]:
        raise RuntimeError("Compilation QC failed: " + "; ".join(qc["errors"]))
    report = run_publish_audit(Config("config.story.yaml"), final_video, metadata)
    metadata.update({"status": "strict_audit_passed", "audit_id": report["audit_id"]})
    write_json(output / "metadata.json", metadata)
    print(f"READY AND STRICTLY AUDITED: {final_video}")
    print(f"AUDIT: {report['audit_id']}")
    return final_video


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=11)
    parser.add_argument("--end", type=int, default=15)
    parser.add_argument("--reuse-episode-encodes", action="store_true")
    arguments = parser.parse_args()
    build(arguments.start, arguments.end, arguments.reuse_episode_encodes)
