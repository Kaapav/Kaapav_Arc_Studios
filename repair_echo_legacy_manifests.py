#!/usr/bin/env python3
"""Upgrade rendered ECHO Episodes 2–9 from legacy manifests to full prompt packs."""

from __future__ import annotations

import json
from pathlib import Path

from studio_manual_pipeline import export_prompts


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "content" / "echo100" / "v2" / "cute_style"
LOCKS = {
    "Kavi": "South Asian boy, red hoodie, round glasses, blue repair backpack",
    "Tara": "South Asian girl, mustard rain jacket, dark braid, large red headphones, portable cassette recorder",
    "Byte": "small white floating repair robot, cyan face display, orange antenna, scuffed left panel",
    "Mira": "blue holographic teenage girl, teal transit coat, cracked silver station-badge symbol",
    "Null": "black-purple human silhouette made from layered memories, soft red eyes, frightening but not monstrous",
    "Rhea": "South Asian transit engineer, silver-streaked dark hair, navy work coat, brass ECHO key",
    "Arvind": "South Asian engineer, worn maroon station sweater, rectangular glasses, grease-stained hands",
    "Imran": "South Asian man, faded mustard radio jacket, red headphone cable around wrist",
}
SHOTS = ("dramatic close-up", "medium two-shot", "wide establishing shot", "over-the-shoulder shot", "low-angle action shot", "intimate reaction close-up", "dynamic tracking composition", "cliffhanger reveal")


def fix_text(value: str) -> str:
    if not any(marker in value for marker in ("â", "ð", "Ã")):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def main() -> None:
    for number in range(2, 10):
        path = BASE / f"episode{number:02d}" / "episode.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = 1
        data["series_id"] = "echo30"
        data["series_title"] = "ECHO//30"
        data["episode"] = number
        data["episode_id"] = f"echo30-ep{number:03d}"
        data["manual_review_required"] = True
        data["description"] = fix_text(data["description"])
        data["global_image_style"] = (
            "Vertical 9:16 premium cute stylized 3D feature-animation using immutable ECHO character references; "
            "rain-dark Navapur, tactile materials, cyan memory light, red exchange light, purple denied-memory light, "
            "restrained expressive acting; no readable text, watermark, logo, collage, duplicate people, extra limbs, identity drift or costume drift."
        )
        for index, scene in enumerate(data["scenes"], 1):
            scene["text"] = fix_text(scene["text"])
            names = [name for name in LOCKS if name.casefold() in scene["text"].casefold()]
            lock_clause = "; ".join(f"{name}: {LOCKS[name]}" for name in names) or "No principal character visible; preserve established location and prop continuity"
            scene["image_prompt"] = (
                f"SHOT {index}, {SHOTS[index - 1]}. Depict this exact causal moment: {scene['text']} "
                f"Locked identities on screen: {lock_clause}. Compose one coherent cinematic action and reaction with consistent screen direction, "
                "face, wardrobe, anatomy, prop scale and lighting continuity. No readable generated text, watermark, logo, split screen, collage, duplicate person, extra limb or redesign."
            )
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        export_prompts(path)
        print(f"UPGRADED {path}")


if __name__ == "__main__":
    main()
