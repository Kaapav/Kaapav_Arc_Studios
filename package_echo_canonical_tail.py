#!/usr/bin/env python3
"""Package canonical ECHO//30 Episodes 16–30 from the locked season cut."""

from __future__ import annotations

import json
from pathlib import Path

from package_authored_story_pack import compile_pack


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "content" / "echo100" / "season_cut_30.json"
PACK = ROOT / "content" / "echo100" / "v2" / "cute_style" / "authored_pack_episodes16_30.json"
LOCKS = {
    "Kavi": "South Asian boy, red hoodie, round glasses, blue repair backpack",
    "Tara": "South Asian girl, mustard rain jacket, dark braid, large red headphones, portable cassette recorder",
    "Byte": "small white floating repair robot, cyan face display, orange antenna, scuffed left panel",
    "Mira": "blue holographic girl, teal transit coat, cracked silver station-badge symbol",
    "Rhea": "South Asian woman transit engineer, silver-streaked dark hair, navy work coat, brass ECHO key",
    "Null": "black-purple human silhouette of layered memories, soft red eyes, frightening but not monstrous",
    "Arvind": "South Asian engineer, worn maroon station sweater, rectangular glasses, grease-stained hands",
    "Imran": "South Asian man, faded mustard radio jacket, red headphone cable around wrist",
    "Future Kavi": "older South Asian version of Kavi, same round glasses and facial identity, weathered red-black engineer coat",
}
EFFECTS = ("push_in", "pan_right", "pull_out", "pan_left", "push_in", "pull_out", "pan_right", "push_in")


def names_in(text: str, focus: str) -> list[str]:
    ordered = [name for name in LOCKS if name in text]
    if focus in LOCKS and focus not in ordered:
        ordered.insert(0, focus)
    if "Future Kavi" in ordered and "Kavi" in ordered:
        ordered.remove("Kavi")
    return ordered[:4]


def prompt(number: int, moment: str, location: str, focus: str) -> str:
    names = names_in(moment, focus)
    lock = "; ".join(f"{name}: {LOCKS[name]}" for name in names)
    return (
        f"SHOT {number}, cinematic story composition in {location}. Visually depict this exact causal beat: {moment} "
        f"Locked identities on screen: {lock}. Distinct readable action and emotional reaction, coherent prop and lighting continuity, "
        "rain-dark Navapur palette with red exchange light, cyan memory light, purple denied-memory light and restrained warm amber human light; "
        "vertical 9:16 premium cute stylized 3D feature-animation, original design, tactile materials, expressive restrained acting; "
        "no readable text, watermark, logo, collage, duplicated person, extra limb, identity drift or costume change."
    )


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    episodes = []
    for item in source["episodes"]:
        n = int(item["number"])
        focus = item["focus_character"]
        location = item["primary_location"]
        moments = [
            item["hook"],
            f"Inside {location}, {focus} pursues an immediate answer before the new danger closes in.",
            item["logline"],
            f"A concrete clue forces {focus} to question the explanation the group has trusted until now.",
            item["discovery"],
            f"Instead of hiding the discovery, {focus} makes a choice that the others can challenge and understand.",
            item["reversal"],
            item["cliffhanger"],
        ]
        scenes = [{"text": moment, "image_prompt": prompt(i, moment, location, focus), "effect": EFFECTS[i - 1]}
                  for i, moment in enumerate(moments, 1)]
        episodes.append({
            "episode": n,
            "title": item["title"],
            "description": f"{item['logline']}\n\nECHO//30 — Episode {n}\nAn original animated series from KAAPAV ARC Studios.\n\n#ECHO30 #AnimatedSeries #Shorts",
            "thumbnail_text": " ".join(item["title"].upper().split()[:5]),
            "thumbnail_scene": 8,
            "arc": item["arc"],
            "permanent_story_change": item["permanent_story_change"],
            "tags": ["ECHO//30", "animated sci fi", "time mystery", "cute 3D animation"],
            "scenes": scenes,
        })
    pack = {
        "schema_version": 1,
        "series": {
            "series_id": "echo30",
            "series_title": "ECHO//30",
            "destination_root": "content/echo100/v2/cute_style",
            "directory_pattern": "episode{episode:02d}",
            "global_image_style": "Vertical 9:16 premium cute stylized 3D animation with locked ECHO character sheets, cinematic rain-dark Navapur lighting and emotionally truthful acting.",
            "base_tags": ["KAAPAV ARC Studios", "animated series", "science fiction mystery", "original animation", "shorts"],
        },
        "episodes": episodes,
    }
    PACK.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compile_pack(PACK)


if __name__ == "__main__":
    main()
