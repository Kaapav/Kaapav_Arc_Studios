#!/usr/bin/env python3
"""Quota-safe local image-to-video workflow for the KAAPAV ARC story slate.

This tool does not call a paid image API. It prepares exact prompt packs and
folders, accepts generated images, validates an episode, renders the
Short with the existing local audio/video stack, and performs technical QC.
Nothing is uploaded to YouTube by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "content" / "studio_master_release_plan.json"
ALLOWED_EFFECTS = {"push_in", "pull_out", "pan_left", "pan_right"}
DEFAULT_EFFECTS = ("push_in", "pan_right", "push_in", "pan_left",
                   "pull_out", "push_in", "pan_right", "push_in")
GLOBAL_STYLE = (
    "Vertical 9:16 premium cute cinematic 3D feature-animation; original "
    "characters; expressive acting; dramatic volumetric light; coherent "
    "anatomy, props and environment; preserve the locked character sheets; "
    "no readable text, watermark, logo, duplicate characters, extra limbs, "
    "identity drift, costume changes or slideshow collage."
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_plan() -> dict[str, Any]:
    plan = read_json(PLAN_PATH)
    if len(plan.get("series", [])) != 10:
        raise ValueError("Studio plan must contain exactly ten series")
    for item in plan["series"]:
        for key in ("sequence", "slug", "content_root", "public_title", "genre"):
            if not item.get(key):
                raise ValueError(f"Series entry is missing {key}: {item}")
    return plan


def series_by_slug(slug: str) -> dict[str, Any]:
    for item in load_plan()["series"]:
        if item["slug"] == slug:
            return item
    valid = ", ".join(item["slug"] for item in load_plan()["series"])
    raise ValueError(f"Unknown series '{slug}'. Valid slugs: {valid}")


def production_root(series: dict[str, Any]) -> Path:
    return ROOT / series["content_root"] / "manual_production"


def episode_dir(series: dict[str, Any], episode: int) -> Path:
    return production_root(series) / "episodes" / f"ep{episode:03d}"


def episode_template(series: dict[str, Any], episode: int = 1) -> dict[str, Any]:
    slug = series["slug"]
    title = series["public_title"]
    scenes = []
    for index in range(1, 9):
        scenes.append({
            "image": f"story_frames/shot_{index:02d}.png",
            "image_prompt": f"SHOT {index}: Replace with the exact visual story beat.",
            "text": f"Replace with narration for story beat {index}.",
            "effect": DEFAULT_EFFECTS[index - 1],
        })
    return {
        "schema_version": 1,
        "series_id": slug,
        "series_title": title,
        "episode": episode,
        "episode_id": f"{slug}-ep{episode:03d}",
        "output_slug": f"{slug}-episode{episode:03d}",
        "title": f"REPLACE WITH HOOK | {title} Ep. {episode}",
        "description": (
            f"Replace with the unique episode description.\n\n"
            f"{title} — Episode {episode}\n"
            "An original animated series from KAAPAV ARC Studios.\n\n"
            "#AnimatedSeries #Shorts"
        ),
        "tags": [
            title,
            "KAAPAV ARC Studios",
            "animated series",
            "3D animated short",
            series["genre"],
            "original animation",
            "shorts",
        ],
        "thumbnail_text": "REPLACE WITH 2–5 WORD HOOK",
        "thumbnail_scene": 1,
        "global_image_style": GLOBAL_STYLE,
        "scenes": scenes,
    }


def setup_slate() -> None:
    plan = load_plan()
    for item in plan["series"]:
        root = production_root(item)
        for directory in ("characters", "episodes", "inbox"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        config_path = root / "series.json"
        if not config_path.exists():
            write_json(config_path, {
                "schema_version": 1,
                "sequence": item["sequence"],
                "slug": item["slug"],
                "public_title": item["public_title"],
                "genre": item["genre"],
                "episode_count": plan["release_policy"]["provisional_episode_count_per_series"],
                "character_policy": item["character_policy"],
                "youtube_upload_allowed": False,
            })
        template_path = root / "EPISODE_TEMPLATE.json"
        if not template_path.exists():
            write_json(template_path, episode_template(item))
        readme = root / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {item['public_title']} — Manual Production\n\n"
                "1. Lock all character turnarounds in `characters/`.\n"
                f"2. Create an episode: `python studio_manual_pipeline.py new-episode {item['slug']} 1`.\n"
                "3. Edit `episode.json`, including all eight `image_prompt` and narration fields.\n"
                "4. Export prompts: `python studio_manual_pipeline.py prompts PATH_TO_EPISODE_JSON`.\n"
                "5. Generate images manually and import them with the `import-image` command.\n"
                "6. Validate: `python studio_manual_pipeline.py validate PATH_TO_EPISODE_JSON`.\n"
                "7. Render and QC: `python studio_manual_pipeline.py render PATH_TO_EPISODE_JSON`.\n\n"
                "This pipeline never uploads to YouTube.\n",
                encoding="utf-8",
            )
    print("READY: ten folder-wise manual production workspaces")


def new_episode(slug: str, number: int, force: bool = False) -> Path:
    series = series_by_slug(slug)
    if not 1 <= number <= 30:
        raise ValueError("Episode number must be between 1 and 30")
    target = episode_dir(series, number)
    manifest = target / "episode.json"
    if manifest.exists() and not force:
        raise FileExistsError(f"Episode already exists: {manifest}; use --force to replace template")
    (target / "story_frames").mkdir(parents=True, exist_ok=True)
    write_json(manifest, episode_template(series, number))
    export_prompts(manifest)
    print(f"CREATED: {manifest}")
    return manifest


def resolve_manifest(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Episode manifest not found: {path}")
    return path


def _image_info(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        return image.size


def validate_manifest(path: Path, require_prompts: bool = False) -> dict[str, Any]:
    data = read_json(path)
    required = (
        "episode", "episode_id", "output_slug", "title", "description",
        "tags", "thumbnail_text", "thumbnail_scene", "scenes",
    )
    errors: list[str] = []
    warnings: list[str] = []
    for key in required:
        if key not in data:
            errors.append(f"missing top-level field: {key}")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    if not 1 <= int(data["episode"]) <= 30:
        errors.append("episode must be between 1 and 30")
    if not 6 <= len(data["scenes"]) <= 12:
        errors.append("a Short must contain 6–12 scenes")
    if len(data["title"]) > 100:
        errors.append(f"title exceeds 100 characters ({len(data['title'])})")
    if len(data["description"]) > 5000:
        errors.append("description exceeds 5000 characters")
    tag_length = len(",".join(str(tag) for tag in data["tags"]))
    if tag_length > 500:
        errors.append(f"combined tags exceed 500 characters ({tag_length})")
    if not 1 <= int(data["thumbnail_scene"]) <= len(data["scenes"]):
        errors.append("thumbnail_scene is outside the scene range")

    hashes: list[str] = []
    words = 0
    images: list[dict[str, Any]] = []
    for index, scene in enumerate(data["scenes"], 1):
        image_value = scene.get("image")
        text = str(scene.get("text", "")).strip()
        prompt = str(scene.get("image_prompt", "")).strip()
        effect = scene.get("effect", "push_in")
        if not image_value:
            errors.append(f"scene {index}: image path missing")
            continue
        if not text or text.startswith("Replace with"):
            errors.append(f"scene {index}: narration is still a placeholder")
        words += len(text.split())
        prompt_is_placeholder = bool(
            not prompt or re.search(r"\b(replace with|prompt not written|todo|tbd)\b", prompt, re.I)
        )
        if require_prompts and prompt_is_placeholder:
            errors.append(f"scene {index}: image_prompt is still a placeholder")
        elif not prompt:
            warnings.append(f"scene {index}: no image_prompt (legacy manifest accepted)")
        if effect not in ALLOWED_EFFECTS:
            errors.append(f"scene {index}: unsupported effect '{effect}'")
        image_path = (path.parent / image_value).resolve()
        if not image_path.is_file():
            errors.append(f"scene {index}: missing image {image_path}")
            continue
        try:
            width, height = _image_info(image_path)
        except Exception as exc:
            errors.append(f"scene {index}: unreadable image ({exc})")
            continue
        if height <= width:
            errors.append(f"scene {index}: image must be portrait, got {width}x{height}")
        if width < 700 or height < 1100:
            warnings.append(f"scene {index}: low source resolution {width}x{height}")
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        hashes.append(digest)
        images.append({"scene": index, "path": str(image_path), "width": width,
                       "height": height, "sha256": digest})
    if len(hashes) != len(set(hashes)):
        errors.append("duplicate story-frame files detected")
    if words > 175:
        warnings.append(f"narration has {words} words; a 58-second Short may sound rushed")
    if words < 75:
        warnings.append(f"narration has only {words} words; pacing may feel thin")
    return {
        "ok": not errors,
        "manifest": str(path),
        "series_title": data.get("series_title", "ECHO//30"),
        "episode": data["episode"],
        "scene_count": len(data["scenes"]),
        "word_count": words,
        "unique_images": len(set(hashes)),
        "images": images,
        "errors": errors,
        "warnings": warnings,
    }


def print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(2)


def export_prompts(path: Path) -> Path:
    data = read_json(path)
    style = data.get("global_image_style", GLOBAL_STYLE)
    lines = [
        f"# {data.get('series_title', data.get('series_id', 'SERIES'))} — Episode {data.get('episode')}",
        "",
        "## Locked global style",
        "",
        style,
        "",
        "## Manual image files",
        "",
    ]
    for index, scene in enumerate(data.get("scenes", []), 1):
        lines.extend([
            f"### Shot {index:02d} → `{scene.get('image', f'story_frames/shot_{index:02d}.png')}`",
            "",
            scene.get("image_prompt", "PROMPT NOT WRITTEN"),
            "",
            f"Narration: {scene.get('text', '')}",
            "",
        ])
    output = path.parent / "IMAGE_PROMPTS.md"
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"PROMPTS: {output}")
    return output


def import_image(path: Path, shot: int, source: Path, force: bool = False) -> Path:
    data = read_json(path)
    if not 1 <= shot <= len(data.get("scenes", [])):
        raise ValueError(f"Shot must be between 1 and {len(data.get('scenes', []))}")
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    destination = (path.parent / data["scenes"][shot - 1]["image"]).resolve()
    if destination.exists() and not force:
        raise FileExistsError(f"Image already exists: {destination}; use --force to replace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGB").save(destination, format="PNG", optimize=True)
    width, height = _image_info(destination)
    if height <= width:
        destination.unlink(missing_ok=True)
        raise ValueError(f"Rejected landscape image {width}x{height}; vertical 9:16 required")
    print(f"IMPORTED SHOT {shot:02d}: {destination} ({width}x{height})")
    return destination


def render_episode(path: Path) -> Path:
    report = validate_manifest(path)
    print_report(report)
    data = read_json(path)

    from src.config import Config
    from src import provenance, thumbnail, tts, video

    output_root = ROOT / "output" / "story" / data["output_slug"]
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
    scenes = []
    for scene in data["scenes"]:
        source = (path.parent / scene["image"]).resolve()
        scenes.append({
            "text": scene["text"],
            "caption": scene.get("caption", scene["text"]),
            "image_path": str(source),
            "effect": scene.get("effect", "push_in"),
            "allow_stock_video": False,
        })
    script = {
        "title": data["title"],
        "description": data["description"],
        "tags": data["tags"],
        "narration": " ".join(scene["text"] for scene in data["scenes"]),
        "scenes": scenes,
        "series_id": data.get("series_id", "kaapav_arc"),
        "episode_id": data["episode_id"],
    }
    write_json(output_root / "script.json", script)
    voice_path = output_root / "voice.mp3"
    timings = tts.synthesize(cfg, script["narration"], voice_path)
    video_path = output_root / "video.mp4"
    video.build_video(cfg, script, voice_path, timings, video_path)
    thumbnail_path = output_root / "thumbnail.jpg"
    thumb_index = int(data.get("thumbnail_scene", 1)) - 1
    thumbnail.build_thumbnail(
        cfg,
        data["thumbnail_text"],
        data["episode_id"],
        thumbnail_path,
        image_path=scenes[thumb_index]["image_path"],
        series_label=f"{data.get('series_title', data.get('series_id', 'KAAPAV ARC'))} • EPISODE {data['episode']}",
    )
    write_json(output_root / "metadata.json", {
        "title": data["title"],
        "description": data["description"],
        "tags": data["tags"],
        "status": "local_review_only",
        "uploaded": False,
        "source": "studio-local-pipeline-v2",
    })
    provenance.write_rights_manifest(output_root, script, cfg)
    qc = technical_qc(video_path, len(scenes))
    write_json(output_root / "qc_report.json", qc)
    print(f"READY FOR REVIEW: {video_path}")
    print(f"THUMBNAIL: {thumbnail_path}")
    print(f"QC CONTACT: {qc['contact_sheet']}")
    print("UPLOAD STATUS: NOT UPLOADED")
    return video_path


def technical_qc(video_path: Path, scene_count: int) -> dict[str, Any]:
    probe_command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(video_path),
    ]
    probe = json.loads(subprocess.check_output(probe_command, text=True))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-f", "null", os.devnull],
        check=True,
    )
    duration = float(probe["format"]["duration"])
    columns = 4
    rows = math.ceil(scene_count / columns)
    fps = scene_count / duration
    contact = video_path.parent / "qc_contact.jpg"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video_path),
        "-vf", f"fps={fps},scale=360:-1,tile={columns}x{rows}",
        "-frames:v", "1", str(contact),
    ], check=True)
    streams = probe.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    errors = []
    if video_stream.get("width") != 720 or video_stream.get("height") != 1280:
        errors.append("encoded video is not 720x1280")
    if duration > 58.1:
        errors.append(f"encoded duration exceeds 58 seconds: {duration}")
    if not audio_stream:
        errors.append("encoded video has no audio stream")
    return {
        "ok": not errors,
        "full_decode": "passed",
        "duration_seconds": duration,
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "contact_sheet": str(contact),
        "errors": errors,
    }


def status() -> None:
    rows = []
    for series in load_plan()["series"]:
        root = production_root(series)
        manifests = sorted((root / "episodes").glob("ep*/episode.json")) if root.exists() else []
        valid = 0
        for manifest in manifests:
            if validate_manifest(manifest).get("ok"):
                valid += 1
        rows.append({
            "sequence": series["sequence"],
            "slug": series["slug"],
            "title": series["public_title"],
            "workspace": str(root),
            "episode_packages": len(manifests),
            "render_ready": valid,
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Create manual workspaces for all ten series")
    new = sub.add_parser("new-episode", help="Create one episode folder and template")
    new.add_argument("series_slug")
    new.add_argument("episode", type=int)
    new.add_argument("--force", action="store_true")
    prompts = sub.add_parser("prompts", help="Export a manual image prompt pack")
    prompts.add_argument("manifest")
    validate = sub.add_parser("validate", help="Validate scripts and manually created images")
    validate.add_argument("manifest")
    validate.add_argument("--require-prompts", action="store_true")
    importer = sub.add_parser("import-image", help="Import one downloaded image into a shot slot")
    importer.add_argument("manifest")
    importer.add_argument("shot", type=int)
    importer.add_argument("source", type=Path)
    importer.add_argument("--force", action="store_true")
    render = sub.add_parser("render", help="Validate, render and technically QC one episode")
    render.add_argument("manifest")
    sub.add_parser("status", help="Show readiness across all ten story folders")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "setup":
        setup_slate()
    elif args.command == "new-episode":
        new_episode(args.series_slug, args.episode, force=args.force)
    elif args.command == "prompts":
        export_prompts(resolve_manifest(args.manifest))
    elif args.command == "validate":
        print_report(validate_manifest(resolve_manifest(args.manifest), args.require_prompts))
    elif args.command == "import-image":
        import_image(resolve_manifest(args.manifest), args.shot, args.source, args.force)
    elif args.command == "render":
        render_episode(resolve_manifest(args.manifest))
    elif args.command == "status":
        status()
    else:
        raise AssertionError(args.command)


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, FileExistsError, ValueError, json.JSONDecodeError,
            subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
