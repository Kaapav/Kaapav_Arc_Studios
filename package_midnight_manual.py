#!/usr/bin/env python3
"""Convert the authored 30-episode Midnight Platform season into manual packs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from studio_manual_pipeline import export_prompts


ROOT = Path(__file__).resolve().parent
SERIES_ROOT = ROOT / "content" / "the_midnight_platform"
SOURCE_EPISODES = SERIES_ROOT / "episodes"
DESTINATION = SERIES_ROOT / "manual_production" / "episodes"
REGISTRY = SERIES_ROOT / "assets" / "references" / "character_registry.json"
SERIES = SERIES_ROOT / "series.json"
EFFECTS = ("pull_out", "push_in", "pan_right", "pan_left", "push_in", "pull_out")
STYLE = (
    "Vertical 9:16 premium cute cinematic 3D feature-animation in THE MIDNIGHT PLATFORM world. "
    "Victorian-Indian supernatural railway design, wet midnight platforms, antique brass clockwork, "
    "navy, cyan and amber lighting, expressive original characters. Preserve every locked turnaround, "
    "age, costume, prop, handedness and relationship. Tick is always a small quadruped clockwork fox. "
    "The Conductor's clock mask and uniform remain exact. No readable generated text; any required words "
    "are added later as editorial typography. No duplicate characters, extra limbs, identity drift, "
    "costume drift, logos or watermark."
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_dialogue(value: str) -> str:
    value = value.replace("â€œ", "“").replace("â€", "”").replace("â€™", "’")
    return re.sub(r"\s+", " ", value).strip()


def thumbnail_hook(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9’']+", clean_dialogue(title).upper())
    if words and words[0] in {"THE", "A", "AN"}:
        words = words[1:]
    return " ".join(words[:5])


def readiness_report() -> dict:
    payload = read_json(REGISTRY)
    characters = []
    for name, item in payload["characters"].items():
        turnaround_value = item.get("turnaround")
        turnaround = (REGISTRY.parent / turnaround_value).resolve() if turnaround_value else None
        status = item.get("status", "unknown")
        characters.append({
            "character": name,
            "scope": item.get("scope"),
            "status": status,
            "turnaround": str(turnaround) if turnaround else None,
            "turnaround_exists": bool(turnaround and turnaround.is_file()),
            "production_ready": status == "candidate_visual_qc_passed" and bool(turnaround and turnaround.is_file()),
        })
    ready = sum(1 for item in characters if item["production_ready"])
    pending = [item["character"] for item in characters if not item["production_ready"]]
    return {
        "schema_version": 1,
        "series_id": "the_midnight_platform",
        "policy": "turnaround required before any shot containing the character is generated",
        "characters_total": len(characters),
        "characters_ready": ready,
        "characters_pending": pending,
        "all_characters_ready": not pending,
        "characters": characters,
    }


def build_episode(number: int, title: str, storyboard: dict) -> Path:
    target = DESTINATION / f"ep{number:03d}"
    (target / "story_frames").mkdir(parents=True, exist_ok=True)
    scenes = []
    for index, shot in enumerate(storyboard["shots"], 1):
        visual = clean_dialogue(shot["visual_event"])
        dialogue = clean_dialogue(shot["dialogue_audio"])
        scenes.append({
            "image": f"story_frames/shot_{index:02d}.png",
            "image_prompt": (
                f"SHOT {index:02d}, {shot['seconds']} seconds. {visual} "
                "Use only the canonical turnaround sheets for every named character in this shot. "
                "Compose one coherent cinematic moment with clear action and reaction; leave clean caption space."
            ),
            "text": dialogue,
            "dialogue_audio": dialogue,
            "planned_seconds": shot["seconds"],
            "effect": EFFECTS[(index - 1) % len(EFFECTS)],
        })
    hook = thumbnail_hook(title)
    title_suffix = f" | MIDNIGHT PLATFORM Ep. {number}"
    youtube_title = title if len(title + title_suffix) <= 100 else title[:100 - len(title_suffix)].rstrip()
    youtube_title += title_suffix
    episode = {
        "schema_version": 1,
        "series_id": "the_midnight_platform",
        "series_title": "THE MIDNIGHT PLATFORM",
        "episode": number,
        "episode_id": f"the-midnight-platform-ep{number:03d}",
        "output_slug": f"the-midnight-platform-episode{number:03d}",
        "title": youtube_title,
        "description": (
            f"{title}. One supernatural railway choice permanently changes Arin, Meera, and the passengers trapped between minutes.\n\n"
            f"THE MIDNIGHT PLATFORM — Episode {number}\n"
            "An original supernatural mystery animated series from KAAPAV ARC Studios.\n\n"
            "Subscribe: https://www.youtube.com/@kaapavarcstudios?sub_confirmation=1\n\n"
            "#MidnightPlatform #AnimatedSeries #Shorts"
        ),
        "tags": [
            "The Midnight Platform", "KAAPAV ARC Studios", "animated series",
            "supernatural mystery", "3D animated short", "ghost train story",
            "fantasy animation", "original animation", "shorts",
        ],
        "thumbnail_text": hook,
        "thumbnail_scene": len(scenes),
        "global_image_style": STYLE,
        "source_screenplay": str((SOURCE_EPISODES / f"ep{number:03d}" / "screenplay.md").resolve()),
        "source_storyboard": str((SOURCE_EPISODES / f"ep{number:03d}" / "storyboard_plan.json").resolve()),
        "voice_mode": "multi_speaker_script_preserved_single_narrator_fallback",
        "manual_review_required": True,
        "scenes": scenes,
    }
    manifest = target / "episode.json"
    write_json(manifest, episode)
    export_prompts(manifest)
    return manifest


def main() -> None:
    season_manifest = read_json(SERIES_ROOT / "scripts" / "season_package_manifest.json")
    source_items = season_manifest.get("episodes", [])
    if len(source_items) != 30:
        raise ValueError("Midnight Platform season must contain exactly 30 authored episodes")
    built = []
    total_shots = 0
    for expected, item in enumerate(source_items, 1):
        if int(item["episode"]) != expected:
            raise ValueError(f"Episode sequence mismatch at {expected}")
        storyboard_path = SOURCE_EPISODES / f"ep{expected:03d}" / "storyboard_plan.json"
        screenplay_path = SOURCE_EPISODES / f"ep{expected:03d}" / "screenplay.md"
        if not storyboard_path.is_file() or not screenplay_path.is_file():
            raise FileNotFoundError(f"Episode {expected} source package incomplete")
        storyboard = read_json(storyboard_path)
        if len(storyboard.get("shots", [])) != 6:
            raise ValueError(f"Episode {expected} must contain six authored shots")
        for shot in storyboard["shots"]:
            if not shot.get("visual_event") or not shot.get("dialogue_audio"):
                raise ValueError(f"Episode {expected} contains an incomplete shot")
        built.append(str(build_episode(expected, item["title"], storyboard)))
        total_shots += len(storyboard["shots"])

    report = readiness_report()
    write_json(SERIES_ROOT / "manual_production" / "character_readiness_report.json", report)
    write_json(SERIES_ROOT / "manual_production" / "season_pack_report.json", {
        "schema_version": 1,
        "series_id": "the_midnight_platform",
        "status": "story_image_video_scripts_packaged",
        "episodes": len(built),
        "shots": total_shots,
        "episode_manifests": built,
        "character_readiness_report": str((SERIES_ROOT / "manual_production" / "character_readiness_report.json").resolve()),
        "video_generation_gate": "manual images and character readiness required",
        "youtube_upload_gate": "render QC and explicit approval required",
    })
    print(json.dumps({
        "episodes_packaged": len(built),
        "shots_packaged": total_shots,
        "characters_ready": report["characters_ready"],
        "characters_pending": report["characters_pending"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
