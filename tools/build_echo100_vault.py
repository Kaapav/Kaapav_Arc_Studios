#!/usr/bin/env python3
"""Build a checkpointed 100-episode ECHO//100 writing vault.

This tool never uploads or renders. It creates a canon season plan first, then
expands episodes into validated, production-ready JSON packages. Existing
episode files are preserved unless --replace-drafts is explicitly supplied.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config
from src import episodes, llm


PLAN_PATH = ROOT / "content" / "echo100" / "season_plan.json"
EPISODE_DIR = ROOT / "content" / "echo100" / "episodes"
REFERENCE_ART = [
    "assets/story/echo100/exec-87ab096a-0780-4743-b93b-55d6b38522eb.png",
    "assets/story/echo100/exec-89230522-4ba4-4bee-8de4-e38689900263.png",
    "assets/story/echo100/exec-8915310f-9232-413e-9a22-dd3bad7f366f.png",
    "assets/story/echo100/exec-cbbccb8c-b9a3-462d-af4c-7abf2be6bbc4.png",
    "assets/story/echo100/exec-f642873b-5a63-4589-ae19-377781fa8bf0.png",
]


ARC_SEEDS = [
    (1, 10, "The Red Door", "Kavi learns the warning is part of a loop and Byte helped build the door."),
    (11, 20, "The Missing Hour", "The city loses one hour every night while Null edits everyone's memories."),
    (21, 30, "The City Without Shadows", "Kavi enters a discarded timeline where shadows remember erased people."),
    (31, 40, "Mira Protocol", "Mira's forbidden archive reveals she has reset Kavi many times."),
    (41, 50, "The Hundred Phones", "Dead phones across the city receive conflicting messages from possible futures."),
    (51, 60, "Byte's Lie", "Byte's sealed memory identifies him as the lock, not merely Kavi's friend."),
    (61, 70, "Null Before Null", "The team discovers the human decision that created the glitch entity."),
    (71, 80, "The First Kavi", "An older original Kavi claims every other Kavi is a copy made by the door."),
    (81, 90, "The Door War", "Surviving timelines collide and each version wants control of the only exit."),
    (91, 100, "The Final Message", "Kavi must choose one true timeline and send the warning that began Episode 1."),
]


def _extract_json(text: str):
    text = re.sub(r"^```(?:json)?", "", text.strip()).strip()
    text = re.sub(r"```$", "", text).strip()
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if not starts:
        raise ValueError("LLM response contains no JSON")
    start = min(starts)
    end = max(text.rfind("]"), text.rfind("}"))
    return json.loads(text[start:end + 1])


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _existing_episode_one() -> dict:
    path = EPISODE_DIR / "ep001.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _plan_prompt(start: int, end: int, arc: str, arc_goal: str, prior: list[dict]) -> str:
    prior_tail = prior[-3:]
    return f"""
Create Episodes {start}-{end} for the original vertical animated mystery series ECHO//100.

LOCKED PREMISE: A South Asian teenager named Kavi receives messages from his future self
through a dead phone. His small floating robot Byte is connected to a red doorway erased
from history. Mira is a blue holographic archive AI. Null is a frightening, family-friendly
black-purple glitch entity hunting the missing timeline.

CURRENT ARC: {arc}
ARC DESTINATION: {arc_goal}
PREVIOUS THREE EPISODES: {json.dumps(prior_tail, ensure_ascii=False)}

Return ONLY a JSON array with exactly {end - start + 1} objects. Each object must contain:
number, title, hook, logline, discovery, reversal, cliffhanger, focus_character,
primary_location, permanent_story_change.

Rules:
- Every episode is one materially distinct 25-55 second story, not a recap or filler.
- Begin with an immediate impossible event; end with a new consequential cliffhanger.
- Cause and effect must flow across episodes; never erase a permanent story change.
- Keep the same four characters and family-friendly suspense.
- No real people, franchises, gore, profanity, statistics, or generic motivational lessons.
- Episode {end} must materially advance the arc destination.
- Titles must be concise, curiosity-led, and unique; do not include episode numbers.
"""


def build_plan(cfg: Config, replace: bool = False) -> list[dict]:
    if PLAN_PATH.exists() and not replace:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        if len(plan.get("episodes", [])) == 100:
            existing = plan["episodes"]
            make_titles_unique(existing)
            validate_plan(existing)
            _atomic_json(
                PLAN_PATH,
                {"schema_version": 1, "series_id": "echo100", "episodes": existing},
            )
            return existing

    first = _existing_episode_one()
    plan = [{
        "number": 1,
        "title": first["title"].split(" | ")[0],
        "hook": first["scenes"][0]["text"],
        "logline": first["description"].split("\n", 1)[0],
        "discovery": "The recording is one hundred years old.",
        "reversal": "Byte says he knows what is behind the red door.",
        "cliffhanger": "Tomorrow's Kavi warns them to run before Null sees them.",
        "focus_character": "Kavi",
        "primary_location": "abandoned neon arcade",
        "permanent_story_change": "The red door is open and Null has seen Kavi.",
        "arc": "The Red Door",
    }]

    for start, end, arc, goal in ARC_SEEDS:
        batch_start = max(2, start)
        if batch_start > end:
            continue
        print(f"[plan] {batch_start:03d}-{end:03d}: {arc}")
        raw = llm.chat(
            cfg,
            _plan_prompt(batch_start, end, arc, goal, plan),
            system="You are the continuity editor and head writer of an original serialized animated mystery. Protect causality, character identity, and cliffhanger quality.",
            temperature=0.78,
            max_tokens=5200,
        )
        batch = _extract_json(raw)
        if isinstance(batch, dict):
            batch = batch.get("episodes", [])
        expected = list(range(batch_start, end + 1))
        numbers = [int(item.get("number", -1)) for item in batch]
        if numbers != expected:
            raise RuntimeError(f"Arc {arc} returned episode numbers {numbers}; expected {expected}")
        for item in batch:
            item["arc"] = arc
        plan.extend(batch)
        _atomic_json(PLAN_PATH, {"schema_version": 1, "series_id": "echo100", "episodes": plan})
        time.sleep(1.0)

    make_titles_unique(plan)
    validate_plan(plan)
    _atomic_json(PLAN_PATH, {"schema_version": 1, "series_id": "echo100", "episodes": plan})
    return plan


def make_titles_unique(plan: list[dict]) -> None:
    """Repair provider title collisions without changing any story beats."""
    seen: set[str] = set()
    for item in plan:
        original = str(item["title"]).strip()
        key = re.sub(r"\W+", " ", original.lower()).strip()
        if key not in seen:
            seen.add(key)
            continue
        arc_suffix = str(item.get("arc", "ECHO")).strip()
        candidate = f"{original}: {arc_suffix}"
        candidate_key = re.sub(r"\W+", " ", candidate.lower()).strip()
        if candidate_key in seen:
            candidate = f"{candidate} {int(item['number']):03d}"
            candidate_key = re.sub(r"\W+", " ", candidate.lower()).strip()
        item["title"] = candidate
        seen.add(candidate_key)


def validate_plan(plan: list[dict]) -> None:
    if [int(item["number"]) for item in plan] != list(range(1, 101)):
        raise RuntimeError("Season plan must contain episodes 1-100 in order")
    titles = [re.sub(r"\W+", " ", item["title"].lower()).strip() for item in plan]
    duplicates = sorted({title for title in titles if titles.count(title) > 1})
    if duplicates:
        raise RuntimeError(f"Duplicate season titles: {duplicates}")
    required = {"title", "hook", "logline", "discovery", "reversal", "cliffhanger",
                "focus_character", "primary_location", "permanent_story_change", "arc"}
    for item in plan:
        missing = required - set(item)
        if missing:
            raise RuntimeError(f"Episode {item.get('number')} plan missing {sorted(missing)}")


def _episode_prompt(item: dict, previous: dict | None) -> str:
    return f"""
Expand this locked ECHO//100 beat sheet into one 8-scene vertical animated Short.

EPISODE PLAN: {json.dumps(item, ensure_ascii=False)}
PREVIOUS EPISODE ENDING: {json.dumps(previous, ensure_ascii=False) if previous else 'Episode 1 canon'}

Return ONLY one JSON object containing title, description, tags, and scenes.
Each of exactly 8 scenes must contain:
- text: 7-18 words of punchy spoken narration
- caption: 2-6 words
- image_prompt: a concrete textless vertical cinematic shot featuring named characters
- effect: one of push_in, pull_out, pan_left, pan_right, glitch

Rules:
- Total narration 85-120 words.
- Narration must stay in third person, matching Episode 1: call the protagonist Kavi.
  Do not use I, me, my, mine, we, us, our, or ours anywhere in narration or dialogue.
- Scene 1 is an immediate visual mystery. No greeting, recap, or 'previously'.
- Each scene changes action, information, or danger; scenes cannot paraphrase each other.
- Scene 6 reveals the reversal. Scene 8 lands the exact consequential cliffhanger.
- Preserve Kavi's red hoodie/glasses/backpack, Byte's white floating body/cyan face/orange
  antenna, Mira's blue holographic teal coat, and Null's black-purple glitch/red eyes.
- Original family-friendly science-fiction suspense. No gore, profanity, real people,
  franchises, logos, generated text inside imagery, or engagement bait.
- Description: two story sentences, then 'Episode N of ECHO//100: ARC.' and an AI-assisted
  original-fiction disclosure.
- Tags: exactly echo100, animated short, 3d animation, mystery series, science fiction, shorts.
"""


def _arc_number(arc: str) -> int | None:
    for number, (_, _, name, _) in enumerate(ARC_SEEDS, 1):
        if name == arc:
            return number
    return None


def _asset_for(scene: dict, index: int, arc: str) -> tuple[str, str]:
    arc_number = _arc_number(arc)
    if arc_number is not None:
        candidate = (
            f"assets/story/echo100/arc{arc_number:02d}/"
            f"arc{arc_number:02d}-shot-{(index % 4) + 1:02d}.jpg"
        )
        if (ROOT / candidate).exists():
            return candidate, "arc_art"
    blob = f"{scene.get('text', '')} {scene.get('image_prompt', '')}".lower()
    if "future kavi" in blob or "older kavi" in blob:
        return REFERENCE_ART[3], "reference_fallback"
    if "null" in blob or "glitch" in blob or "pixel" in blob:
        return REFERENCE_ART[2], "reference_fallback"
    if "mira" in blob or "door" in blob or "archive" in blob:
        return REFERENCE_ART[1], "reference_fallback"
    if "phone" in blob or "byte" in blob:
        return REFERENCE_ART[0], "reference_fallback"
    return REFERENCE_ART[index % len(REFERENCE_ART)], "reference_fallback"


def expand_episode(cfg: Config, item: dict, previous: dict | None) -> dict:
    raw = llm.chat(
        cfg,
        _episode_prompt(item, previous),
        system="You write high-retention original micro-episodes for a recurring animated mystery. Every line must alter the story.",
        temperature=0.76,
        max_tokens=2600,
    )
    data = _extract_json(raw)
    scenes = data.get("scenes", [])
    if len(scenes) != 8:
        raise RuntimeError(f"Episode {item['number']} returned {len(scenes)} scenes")
    for index, scene in enumerate(scenes):
        scene["caption"] = " ".join(str(scene["caption"]).split()[:6])
        scene["effect"] = scene.get("effect") if scene.get("effect") in {
            "push_in", "pull_out", "pan_left", "pan_right", "glitch"
        } else ("push_in" if index % 2 == 0 else "pan_right")
        scene["image_path"], scene["visual_status"] = _asset_for(
            scene, index, item["arc"]
        )
        scene["allow_stock_video"] = False
    number = int(item["number"])
    visual_ready = all(scene.get("visual_status") == "arc_art" for scene in scenes)
    return {
        "schema_version": 1,
        "series_id": "echo100",
        "episode_id": f"echo100-s01e{number:03d}",
        "season": 1,
        "episode": number,
        "status": "ready" if visual_ready else "draft",
        "canon_version": 1,
        "arc": item["arc"],
        "title": f"{data.get('title') or item['title']} | ECHO//100 Episode {number}",
        "description": data.get("description", item["logline"]),
        "tags": ["echo100", "animated short", "3d animation", "mystery series", "science fiction", "shorts"],
        "quality_profile": "episode1-benchmark-v1",
        "pov_profile": "third-person-v1",
        "scenes": scenes,
    }


def rebind_arc_art() -> tuple[int, int]:
    """Attach newly generated arc art and release fully covered drafts."""
    changed = 0
    released = 0
    for path in sorted(EPISODE_DIR.glob("ep*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("episode", 0)) == 1 or not data.get("arc"):
            continue
        before = json.dumps(data, sort_keys=True, ensure_ascii=False)
        if "AI-assisted" not in str(data.get("description", "")):
            data["description"] = (
                str(data.get("description", "")).rstrip()
                + "\n\nThis is original AI-assisted animated fiction."
            )
        data["quality_profile"] = "episode1-benchmark-v1"
        all_ready = True
        for index, scene in enumerate(data.get("scenes", [])):
            asset, visual_status = _asset_for(scene, index, data["arc"])
            scene["image_path"] = asset
            scene["visual_status"] = visual_status
            all_ready = all_ready and visual_status == "arc_art"
        if all_ready and data.get("status") == "draft":
            data["status"] = "ready"
            released += 1
        if json.dumps(data, sort_keys=True, ensure_ascii=False) != before:
            _atomic_json(path, data)
            episodes.validate_episode(path, data, episodes.load_series())
            changed += 1
    return changed, released


def build_episodes(cfg: Config, plan: list[dict], limit: int | None,
                   replace_drafts: bool = False) -> int:
    created = 0
    previous = plan[0]
    for item in plan[1:]:
        if limit is not None and created >= limit:
            break
        number = int(item["number"])
        path = EPISODE_DIR / f"ep{number:03d}.json"
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if not replace_drafts or current.get("status") not in {"draft", "failed"}:
                previous = item
                continue
        print(f"[episode] {number:03d}/100: {item['title']}")
        package = expand_episode(cfg, item, previous)
        _atomic_json(path, package)
        episodes.validate_episode(path, package, episodes.load_series())
        created += 1
        previous = item
        time.sleep(0.75)
    return created


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--limit", type=int, help="Create at most this many missing episode files")
    parser.add_argument("--replace-plan", action="store_true")
    parser.add_argument("--replace-drafts", action="store_true")
    parser.add_argument("--rebind-art-only", action="store_true")
    args = parser.parse_args()
    cfg = Config("config.story.yaml")
    if not cfg.has_llm:
        raise SystemExit("No LLM provider configured; refusing template season generation")
    if args.rebind_art_only:
        changed, released = rebind_arc_art()
        print(f"ART REBOUND: changed {changed}; released {released} episode(s)")
        return
    plan = build_plan(cfg, replace=args.replace_plan)
    print(f"PLAN READY: {len(plan)} unique episodes")
    if args.plan_only:
        return
    created = build_episodes(cfg, plan, args.limit, args.replace_drafts)
    print(f"VAULT READY: created {created} episode package(s)")


if __name__ == "__main__":
    main()
