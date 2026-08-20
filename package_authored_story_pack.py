#!/usr/bin/env python3
"""Compile an authored KAAPAV ARC story pack into episode production folders."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from studio_manual_pipeline import export_prompts


ROOT = Path(__file__).resolve().parent
ALLOWED_EFFECTS = {"push_in", "pull_out", "pan_left", "pan_right"}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compile_pack(pack_path: Path) -> dict:
    pack_path = pack_path.resolve()
    pack = read_json(pack_path)
    series = pack.get("series", {})
    episodes = pack.get("episodes", [])
    for key in ("series_id", "series_title", "destination_root", "directory_pattern",
                "global_image_style", "base_tags"):
        if not series.get(key):
            raise ValueError(f"Story pack series is missing {key}")
    if not episodes:
        raise ValueError("Story pack contains no episodes")
    destination_root = (ROOT / series["destination_root"]).resolve()
    built = []
    numbers = []
    for item in episodes:
        number = int(item["episode"])
        numbers.append(number)
        scenes = item.get("scenes", [])
        if not 6 <= len(scenes) <= 12:
            raise ValueError(f"Episode {number} must contain 6–12 authored scenes")
        episode_scenes = []
        for index, scene in enumerate(scenes, 1):
            prompt = str(scene.get("image_prompt", "")).strip()
            narration = str(scene.get("text", "")).strip()
            effect = scene.get("effect", "push_in")
            if not prompt or re.search(r"\b(replace with|todo|tbd)\b", prompt, re.I):
                raise ValueError(f"Episode {number} scene {index} image prompt incomplete")
            if not narration or re.search(r"\b(replace with|todo|tbd)\b", narration, re.I):
                raise ValueError(f"Episode {number} scene {index} narration incomplete")
            if effect not in ALLOWED_EFFECTS:
                raise ValueError(f"Episode {number} scene {index} effect unsupported: {effect}")
            episode_scenes.append({
                "image": f"story_frames/shot_{index:02d}.png",
                "image_prompt": prompt,
                "text": narration,
                "effect": effect,
            })
        directory = destination_root / series["directory_pattern"].format(episode=number)
        (directory / "story_frames").mkdir(parents=True, exist_ok=True)
        title_suffix = f" | {series['series_title']} Ep. {number}"
        hook_title = item["title"]
        youtube_title = hook_title[:100 - len(title_suffix)].rstrip() + title_suffix
        manifest = {
            "schema_version": 1,
            "series_id": series["series_id"],
            "series_title": series["series_title"],
            "episode": number,
            "episode_id": f"{series['series_id']}-ep{number:03d}",
            "output_slug": f"{series['series_id']}-episode{number:03d}",
            "title": youtube_title,
            "description": item["description"],
            "tags": list(dict.fromkeys(series["base_tags"] + item.get("tags", []))),
            "thumbnail_text": item["thumbnail_text"],
            "thumbnail_scene": int(item.get("thumbnail_scene", len(episode_scenes))),
            "global_image_style": series["global_image_style"],
            "arc": item.get("arc"),
            "permanent_story_change": item.get("permanent_story_change"),
            "manual_review_required": True,
            "scenes": episode_scenes,
        }
        manifest_path = directory / "episode.json"
        write_json(manifest_path, manifest)
        export_prompts(manifest_path)
        built.append(str(manifest_path))
    if len(numbers) != len(set(numbers)):
        raise ValueError("Story pack contains duplicate episode numbers")
    report = {
        "schema_version": 1,
        "series_id": series["series_id"],
        "source_pack": str(pack_path),
        "episodes_packaged": len(built),
        "episode_numbers": sorted(numbers),
        "scene_scripts_packaged": sum(len(item["scenes"]) for item in episodes),
        "manifests": built,
        "status": "story_image_video_scripts_packaged_images_pending",
    }
    report_path = destination_root / "authored_pack_report.json"
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", type=Path)
    args = parser.parse_args()
    compile_pack(args.pack if args.pack.is_absolute() else ROOT / args.pack)
