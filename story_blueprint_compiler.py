#!/usr/bin/env python3
"""Compile a consistency-locked series blueprint into production-ready episode packs.

The source blueprint is deliberately compact but fully authored: each episode must
contain eight distinct narration/visual beats.  The compiler expands those beats
with the locked character and world descriptions, writes the series bible and
turnaround prompts, and then delegates final episode packaging to the established
manual production pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from package_authored_story_pack import compile_pack
from src.title_policy import validate_episode_title


ROOT = Path(__file__).resolve().parent
EFFECTS = ("push_in", "pan_right", "push_in", "pan_left", "pull_out", "push_in", "pan_right", "push_in")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def character_lock(character: dict) -> str:
    return f"{character['name']} ({character['lock']})"


def compile_blueprint(source: Path) -> dict:
    source = source.resolve()
    blueprint = load_json(source)
    series = blueprint["series"]
    characters = {item["id"]: item for item in blueprint["characters"]}
    episodes = blueprint["episodes"]
    if len(episodes) != int(series["episode_count"]):
        raise ValueError(f"Expected {series['episode_count']} episodes; found {len(episodes)}")
    if len({item["episode"] for item in episodes}) != len(episodes):
        raise ValueError("Duplicate episode numbers")
    title_failures = [
        f"Episode {item['episode']}: {issue}"
        for item in episodes
        for issue in validate_episode_title(str(item.get("title") or ""))
    ]
    if title_failures:
        raise ValueError("Episode title policy failed: " + "; ".join(title_failures))

    root = (ROOT / series["destination_root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)

    bible_lines = [
        f"# {series['series_title']} — Series Bible",
        "",
        f"**Genre:** {series['genre']}",
        f"**Premise:** {series['premise']}",
        f"**Season engine:** {series['season_engine']}",
        f"**Ending promise:** {series['ending_promise']}",
        "",
        "## Non-negotiable visual identity",
        "",
        series["global_image_style"],
        "",
        "## Locked cast",
        "",
    ]
    for character in characters.values():
        bible_lines.extend([
            f"### {character['name']}",
            "",
            f"- Role: {character['role']}",
            f"- Permanent design lock: {character['lock']}",
            f"- Acting rule: {character['acting']}",
            "",
        ])
    bible_lines.extend(["## Season episode spine", ""])
    for item in episodes:
        bible_lines.append(f"{int(item['episode']):02d}. **{item['title']}** — {item['logline']}")
    (root / "SERIES_BIBLE.md").write_text("\n".join(bible_lines) + "\n", encoding="utf-8")

    turnaround_lines = [
        f"# {series['series_title']} — Character Turnaround Prompts",
        "",
        "Generate and approve these sheets before any story frames. Use one neutral studio background and the same seed/reference for every angle.",
        "",
    ]
    angles = "front, front three-quarter, profile, back three-quarter, back, opposite profile, full-body action pose, close facial-expression row"
    for character in characters.values():
        turnaround_lines.extend([
            f"## {character['name']}",
            "",
            f"Eight-view model sheet showing {angles}. {series['global_image_style']} Exact identity lock: {character['lock']}. Neutral lighting, accurate proportions, clean unobstructed silhouette, no readable text, no redesign, no duplicate figure.",
            "",
        ])
    (root / "CHARACTER_TURNAROUND_PROMPTS.md").write_text("\n".join(turnaround_lines), encoding="utf-8")

    pack_episodes = []
    for item in episodes:
        beats = item["beats"]
        if len(beats) != 8:
            raise ValueError(f"Episode {item['episode']} must have exactly 8 beats; found {len(beats)}")
        scenes = []
        for index, raw_beat in enumerate(beats):
            if isinstance(raw_beat, str):
                beat = {
                    "narration": raw_beat,
                    "visual": raw_beat,
                    "location": item["location"],
                    "cast": item.get("cast", []),
                    "shot": ("dramatic close-up", "medium two-shot", "wide establishing shot", "over-the-shoulder shot",
                             "low-angle action shot", "intimate close-up", "dynamic tracking shot", "cliffhanger reveal")[index],
                }
            else:
                beat = raw_beat
            cast_ids = list(beat.get("cast", item.get("cast", [])))
            searchable = f"{beat.get('narration', '')} {beat.get('visual', '')}".casefold()
            for character_id, character in characters.items():
                if character["name"].casefold() in searchable and character_id not in cast_ids:
                    cast_ids.append(character_id)
            unknown = [cast_id for cast_id in cast_ids if cast_id not in characters]
            if unknown:
                raise ValueError(f"Episode {item['episode']} beat {index + 1}: unknown cast {unknown}")
            locks = "; ".join(character_lock(characters[cast_id]) for cast_id in cast_ids)
            cast_clause = f" Locked on-screen identities: {locks}." if locks else " No principal character visible."
            prompt = (
                f"SHOT {index + 1}, {beat.get('shot', 'cinematic story shot')}. {beat.get('visual', beat['narration'])}."
                f" Location lock: {beat.get('location', item['location'])}.{cast_clause}"
                " Preserve exact wardrobe, face, body proportions, prop scale, screen direction and lighting continuity."
                " No readable text, watermark, logo, extra limbs, duplicate people, identity drift, costume drift, split screen or collage."
            )
            scenes.append({
                "image_prompt": prompt,
                "text": beat["narration"],
                "effect": beat.get("effect", EFFECTS[index]),
            })
        description = (
            f"{item['logline']}\n\n{series['series_title']} — Episode {item['episode']}\n"
            "An original animated story from KAAPAV ARC Studios.\n\n"
            f"#{series['hashtag']} #AnimatedSeries #Shorts"
        )
        pack_episodes.append({
            "episode": item["episode"],
            "title": item["title"],
            "description": description,
            "thumbnail_text": item["thumbnail_text"],
            "thumbnail_scene": item.get("thumbnail_scene", 8),
            "arc": item["arc"],
            "permanent_story_change": item["permanent_story_change"],
            "tags": item.get("tags", []),
            "scenes": scenes,
        })

    pack = {
        "schema_version": 1,
        "series": {
            "series_id": series["series_id"],
            "series_title": series["series_title"],
            "destination_root": series["destination_root"],
            "directory_pattern": "manual_production/episodes/ep{episode:03d}",
            "global_image_style": series["global_image_style"],
            "base_tags": series["base_tags"],
        },
        "episodes": pack_episodes,
    }
    pack_path = root / "authored_season_pack.json"
    write_json(pack_path, pack)
    report = compile_pack(pack_path)
    report["blueprint"] = str(source)
    report["series_bible"] = str(root / "SERIES_BIBLE.md")
    report["turnaround_prompts"] = str(root / "CHARACTER_TURNAROUND_PROMPTS.md")
    report["qc_policy"] = "Images remain intentionally blocked until turnarounds are approved."
    write_json(root / "blueprint_compile_report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("blueprint", type=Path)
    args = parser.parse_args()
    path = args.blueprint if args.blueprint.is_absolute() else ROOT / args.blueprint
    compile_blueprint(path)
