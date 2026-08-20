#!/usr/bin/env python3
"""Normalize ECHO//100 narration to the Episode 1 third-person benchmark."""

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


POV_RE = re.compile(r"(?i)\b(i|me|my|mine|we|us|our|ours)\b")


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?", "", text.strip()).strip()
    text = re.sub(r"```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object returned")
    return json.loads(text[start:end + 1])


def _atomic(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _rewrite(cfg: Config, episode: dict) -> list[str]:
    current = [scene["text"] for scene in episode["scenes"]]
    prompt = f"""
Rewrite ONLY the eight narration strings below so they match ECHO//100 Episode 1's
third-person cinematic narrator. Preserve every event, reveal, order, character action,
and cliffhanger. Refer to the protagonist as Kavi.

TITLE: {episode['title']}
ARC: {episode.get('arc')}
CURRENT NARRATION: {json.dumps(current, ensure_ascii=False)}

Hard rules:
- Return exactly 8 strings, each 7-18 words, total 80-140 words.
- Use third person only.
- Do not use these words anywhere: I, me, my, mine, we, us, our, ours.
- Convert dialogue into attributed third-person narration when needed.
- Keep present tense, fast suspense, and the exact final cliffhanger.
- No recap, CTA, greeting, new event, profanity, or franchise reference.

Return ONLY valid JSON: {{"texts": ["scene 1", "scene 2", "scene 3", "scene 4",
"scene 5", "scene 6", "scene 7", "scene 8"]}}
"""
    for attempt in range(2):
        raw = llm.chat(
            cfg,
            prompt,
            system="You are a strict continuity copy editor. You alter narrative voice only and never change plot facts.",
            temperature=0.35 if attempt == 0 else 0.15,
            max_tokens=1200,
        )
        texts = _extract_json(raw).get("texts", [])
        word_count = sum(len(str(text).split()) for text in texts)
        if (
            len(texts) == 8
            and not POV_RE.search(" ".join(map(str, texts)))
            and 80 <= word_count <= 140
            and all(7 <= len(str(text).split()) <= 18 for text in texts)
        ):
            return [str(text).strip() for text in texts]
        prompt += "\nYour previous result failed the numeric or POV constraints. Correct it exactly."
    raise RuntimeError(f"Could not normalize {episode['episode_id']} after two attempts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    cfg = Config("config.story.yaml")
    changed = 0
    profiled = 0
    for path in sorted(episodes.EPISODES_DIR.glob("ep*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("episode", 0)) <= 1:
            continue
        narration = " ".join(scene.get("text", "") for scene in data.get("scenes", []))
        needs_rewrite = bool(POV_RE.search(narration))
        if needs_rewrite:
            if args.limit is not None and changed >= args.limit:
                break
            print(f"[pov] {data['episode_id']}: rewriting")
            last_error = None
            for retry in range(4):
                try:
                    texts = _rewrite(cfg, data)
                    break
                except Exception as exc:
                    last_error = exc
                    if retry == 3:
                        raise
                    delay = (5, 15, 30)[retry]
                    print(f"      provider retry {retry + 1}/3 in {delay}s ({exc})")
                    time.sleep(delay)
            else:
                raise last_error or RuntimeError("POV normalization failed")
            for scene, text in zip(data["scenes"], texts):
                scene["text"] = text
            changed += 1
            time.sleep(0.5)
        if data.get("pov_profile") != "third-person-v1" or needs_rewrite:
            data["pov_profile"] = "third-person-v1"
            _atomic(path, data)
            episodes.validate_episode(path, data, episodes.load_series())
            profiled += 1
    print(f"POV READY: rewrote {changed}; profiled {profiled} episode(s)")


if __name__ == "__main__":
    main()
