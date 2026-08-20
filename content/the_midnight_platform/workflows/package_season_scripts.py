"""Split the approved season screenplay documents into self-contained episode packages."""

from __future__ import annotations

import json
import re
from pathlib import Path


STORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = STORY_ROOT / "scripts"
EPISODES_ROOT = STORY_ROOT / "episodes"
ARC_FILES = (
    SCRIPTS_ROOT / "ARC_01_THE_EXCHANGE.md",
    SCRIPTS_ROOT / "ARC_02_THE_ERASED_CITY.md",
    SCRIPTS_ROOT / "ARC_03_THE_LAST_STOP.md",
)

SECTION_PATTERN = re.compile(
    r"^## Episode (?P<number>\d{2}) — (?P<title>.+?)\n\n"
    r"(?P<body>.*?)(?=^## Episode |\Z)",
    re.MULTILINE | re.DOTALL,
)
ROW_PATTERN = re.compile(r"^\| (?P<shot>\d{2}) \| (?P<visual>.+?) \| (?P<audio>.+?) \|$", re.MULTILINE)
END_CARD_PATTERN = re.compile(r"End card: \*\*(?P<text>.+?)\*\*")


def clean_markdown(text: str) -> str:
    return text.replace("**", "").strip()


def main() -> None:
    packaged = []
    for arc_number, source_path in enumerate(ARC_FILES, 1):
        source = source_path.read_text(encoding="utf-8")
        for match in SECTION_PATTERN.finditer(source):
            number = int(match.group("number"))
            body = match.group("body").strip()
            rows = list(ROW_PATTERN.finditer(body))
            end_card_match = END_CARD_PATTERN.search(body)
            if len(rows) != 6 or not end_card_match:
                raise RuntimeError(
                    f"Episode {number:02d} must contain six shots and one end card; "
                    f"found shots={len(rows)}, end_card={bool(end_card_match)}"
                )

            episode_root = EPISODES_ROOT / f"ep{number:03d}"
            episode_root.mkdir(parents=True, exist_ok=True)
            screenplay_path = episode_root / "screenplay.md"
            screenplay_path.write_text(
                f"# Episode {number:02d} — {match.group('title').strip()}\n\n{body}\n",
                encoding="utf-8",
            )

            shots = []
            for row in rows:
                shot_number = int(row.group("shot"))
                visual = clean_markdown(row.group("visual"))
                audio = clean_markdown(row.group("audio"))
                shots.append({
                    "id": f"shot{shot_number:02d}",
                    "seconds": 5,
                    "visual_event": visual,
                    "dialogue_audio": audio,
                    "reference_image": f"shot_frames/shot{shot_number:02d}.png",
                    "reference_status": "pending_generation",
                })

            plan = {
                "schema_version": 1,
                "series_id": "the_midnight_platform",
                "episode_id": f"ep{number:03d}",
                "episode_number": number,
                "arc": arc_number,
                "title": match.group("title").strip(),
                "duration_seconds": 31,
                "production_status": "script_locked_reference_images_pending",
                "canonical_character_references": [
                    "../../assets/references/character_world_master.png",
                    "../../assets/references/secondary_character_master_candidate_v2.png",
                ],
                "secondary_master_status": "candidate_requires_consistency_approval",
                "shots": shots,
                "end_card": {
                    "seconds": 1,
                    "text": clean_markdown(end_card_match.group("text")),
                },
                "video_generation_allowed": number == 1,
                "youtube_upload_allowed": False,
            }
            plan_path = episode_root / "storyboard_plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            packaged.append({
                "episode": number,
                "title": plan["title"],
                "screenplay": str(screenplay_path),
                "storyboard_plan": str(plan_path),
            })

    if len(packaged) != 30 or [item["episode"] for item in packaged] != list(range(1, 31)):
        raise RuntimeError(f"Expected exactly Episodes 1-30 in order; got {[item['episode'] for item in packaged]}")
    manifest_path = SCRIPTS_ROOT / "season_package_manifest.json"
    manifest_path.write_text(
        json.dumps({"status": "passed", "episodes": packaged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Packaged {len(packaged)} episodes under {EPISODES_ROOT}")


if __name__ == "__main__":
    main()
