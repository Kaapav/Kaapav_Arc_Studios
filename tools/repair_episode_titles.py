"""Repair episode titles against the audience-facing title contract across the whole content tree.

Deterministic and story-grounded: the original hook is preserved and extended with
keywords taken from the episode's own description and scene narration. Every edit is
backed up first and logged. Safe to re-run; already-valid titles are never touched.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(r"D:\Apps\YT-Auto")
CONTENT = ROOT / "content"
BACKUP_ROOT = ROOT / "backups" / "control-plane" / "title-repairs"

sys.path.insert(0, str(ROOT))
from src.title_policy import (  # noqa: E402
    STOP_WORDS,
    display_title,
    title_opening_overlap,
    validate_episode_title,
)

PREPOSITIONS = ("in", "during", "of", "after", "before", "inside", "beyond", "at")
CONNECTORS = ("the", "a", "her", "his", "its", "their")

MANUAL_OVERRIDES = {
    "echo30-ep020": "Everyone Remembers in the Restored City Square | ECHO//30 Ep. 20",
    "echo30-ep024": "The Architect in the First Red Door | ECHO//30 Ep. 24",
    "echo30-ep026": "The Door War in the Red Sky | ECHO//30 Ep. 26",
    "echo30-ep028": "Change One Word in the Same Doomed Future | ECHO//30 Ep. 28",
    "echo30-ep030": "2:17 Passes in Silence in the Silent Phone Socket | ECHO//30 Ep. 30",
    "endnightlibrary-ep002": "Morning Forgot to Begin for the Exhausted Citizens | THE LIBRARY AT THE END OF NIGHT Ep. 2",
    "endnightlibrary-ep018": "Iyra Erased the Exit From the Borrowed Ending | THE LIBRARY AT THE END OF NIGHT Ep. 18",
    "endnightlibrary-ep030": "He Let the Night End Beyond the Final Door | THE LIBRARY AT THE END OF NIGHT Ep. 30",
    "the-midnight-platform-ep005": "Tick Lost One Minute and the Train Left | MIDNIGHT PLATFORM Ep. 5",
    "the-midnight-platform-ep010": "Platform 13 Took Saira Sen Away | MIDNIGHT PLATFORM Ep. 10",
    "the-midnight-platform-ep014": "The Train Chose Arin Between the Minutes | MIDNIGHT PLATFORM Ep. 14",
    "the-midnight-platform-ep015": "Tick's Thirteenth Gear at the Station | MIDNIGHT PLATFORM Ep. 15",
    "the-midnight-platform-ep018": "The First Exchange of Thirteen Lives | MIDNIGHT PLATFORM Ep. 18",
    "the-midnight-platform-ep020": "The Man Behind the Mask Kept Listening | MIDNIGHT PLATFORM Ep. 20",
    "the-midnight-platform-ep022": "Twelve Doors Open for the Wrong Name | MIDNIGHT PLATFORM Ep. 22",
    "the-midnight-platform-ep025": "Arin Gave Away Her Face for Meera | MIDNIGHT PLATFORM Ep. 25",
    "the-midnight-platform-ep027": "Tick Stopped the Clock for Sixty Seconds | MIDNIGHT PLATFORM Ep. 27",
    "the-midnight-platform-ep028": "Thirteen Passengers Chose How to Leave | MIDNIGHT PLATFORM Ep. 28",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _story_text(manifest: dict) -> str:
    parts = [str(manifest.get("description") or "")]
    for scene in manifest.get("scenes") or []:
        parts.append(str(scene.get("text") or ""))
    parts.append(str(manifest.get("permanent_story_change") or ""))
    parts.append(str(manifest.get("arc") or ""))
    return "\n".join(parts)


_NOISE = {
    "animatedseries", "kaapav", "shorts", "episode", "series", "studio",
    "anime", "animation", "animated", "mystery", "original", "cinematic",
    "every", "inside", "again", "once", "also", "still", "even", "never",
    "watch", "subscribes", "subscriber", "channel", "twitter", "instagram",
}

_FRAGMENTS = {
    "is", "are", "was", "were", "be", "been", "can", "cannot", "cant",
    "must", "may", "might", "will", "would", "shall", "should", "do",
    "does", "did", "have", "has", "had", "remain", "remains", "stays",
    "stay", "keep", "keeps", "kept", "mean", "means", "show", "shows",
    "showed", "reveals", "prove", "proves", "turn", "turns", "turned",
    "save", "saves", "saved", "own", "owns", "choose", "chooses", "chose",
    "ask", "asks", "asked", "begin", "begins", "began", "stop", "stops",
    "stopped", "start", "starts", "started", "take", "takes", "took",
    "give", "gives", "gave", "make", "makes", "made", "break", "breaks",
    "broke", "come", "comes", "came", "go", "goes", "went", "say", "says",
    "said", "tell", "tells", "told", "hear", "hears", "heard", "see",
    "sees", "saw", "find", "finds", "found", "lose", "loses", "lost",
    "forget", "forgets", "forgot", "learn", "learns", "learned", "erase",
    "erases", "erased", "build", "builds", "built", "strike", "struck",
    "fall", "falls", "fell", "let", "lets", "arrive", "arrives", "arrived",
    "remember", "remembers", "remembered", "trap", "traps", "trapped",
    "too", "that", "really", "between", "above", "below", "apart",
    "isn't", "isnt", "aren't", "arent", "wasn't", "wasnt",
}


def _clean_word(word: str) -> str:
    word = word.strip().strip(".,;:!?()[]\"''")
    for suffix in ("'s", "\u2019s", "’s"):
        if word.lower().endswith(suffix):
            word = word[: -len(suffix)]
            break
    return word


def _phrases(manifest: dict, hook_words: set[str]) -> list[str]:
    import re

    patterns = [
        r"\b(?:the|her|his|its|their|a|an)\s+([A-Za-z][A-Za-z'\u2019-]*(?:\s+[A-Za-z][A-Za-z'\u2019-]*){0,2})",
    ]
    phrase_sources: list[str] = []
    desc = str(manifest.get("description") or "")
    first_line = desc.splitlines()[0] if desc.splitlines() else desc
    scene_text = " ".join(str(s.get("text") or "") for s in manifest.get("scenes") or [])
    arc = str(manifest.get("arc") or "")
    if arc:
        phrase_sources.append(arc)
    if first_line:
        phrase_sources.append(first_line)
    if scene_text:
        phrase_sources.append(scene_text)
    found: list[str] = []
    for source in phrase_sources:
        for match in re.finditer(patterns[0], source, flags=re.IGNORECASE):
            phrase = _clean_word(match.group(1))
            words = phrase.split()
            if not 1 <= len(words) <= 3:
                continue
            if any(w.casefold() in STOP_WORDS or w.casefold() in _NOISE for w in words):
                continue
            if len(words) >= 2 and any(w.casefold() in _FRAGMENTS for w in words[1:]):
                continue
            if any(w.casefold() in hook_words for w in words):
                continue
            found.append(" ".join(w.capitalize() for w in words))
    seen: set[str] = set()
    out: list[str] = []
    for p in found:
        key = p.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _candidates(hook: str, phrases: list[str]) -> list[str]:
    out = []
    for phrase in phrases:
        for prep in PREPOSITIONS:
            out.append(f"{hook} {prep} the {phrase}")
            out.append(f"{hook} {prep} {phrase}")
    return list(dict.fromkeys(out))


def _text_tokens(text: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z0-9]+(?:[''\u2019][A-Za-z0-9]+)?", text)


def _opening(manifest: dict) -> str:
    return " ".join(
        str(scene.get("text") or scene.get("caption") or "")
        for scene in (manifest.get("scenes") or [])[:2] if isinstance(scene, dict)
    )


def _find_fix(manifest: dict) -> str | None:
    episode_id = str(manifest.get("episode_id") or "")
    override = MANUAL_OVERRIDES.get(episode_id)
    if override:
        opening = _opening(manifest)
        if not validate_episode_title(override) and title_opening_overlap(override, opening).get("passed"):
            return override
    original = str(manifest.get("title") or "")
    hook = display_title(original)
    opening = _opening(manifest)
    if not validate_episode_title(original) and title_opening_overlap(original, opening).get("passed"):
        return None
    hook_words = {w.casefold() for w in _text_tokens(hook)}
    phrases = _phrases(manifest, hook_words)
    for candidate in _candidates(hook, phrases):
        tail = candidate[len(hook):].strip().split()[0].strip(",;:") if len(candidate) > len(hook) else ""
        if tail and hook.rstrip().lower().endswith(f" {tail}"):
            continue
        full = f"{candidate} | ECHO//30 Ep. {manifest.get('episode')}" if str(
            manifest.get("series_id") or ""
        ).startswith("echo") else candidate
        failures = validate_episode_title(full)
        if failures:
            continue
        if title_opening_overlap(full, opening).get("passed"):
            return full
    return None


def _backup(manifest_path: pathlib.Path, stamp: str) -> pathlib.Path | None:
    rel = manifest_path.relative_to(CONTENT)
    dest = BACKUP_ROOT / stamp / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, dest)
    return dest


def _apply(manifest_path: pathlib.Path, new_title: str, stamp: str) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["title"] = new_title
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(manifest_path)


def _active_episode_ids() -> set[str]:
    ids: set[str] = set()
    try:
        inv = json.loads((ROOT / "analytics" / "studio_inventory.json").read_text(encoding="utf-8"))
        in_pipeline = {"images_pending", "image_qc_pending", "render_ready", "technical_qc_pending",
                       "strict_audit_pending"}
        ids.update(e.get("episode_id") for e in inv.get("episodes", [])
                   if e.get("state") in in_pipeline)
    except Exception:
        pass
    try:
        queue = json.loads((ROOT / "analytics" / "production_queue.json").read_text(encoding="utf-8"))
        for item in queue.get("tasks") or []:
            if str(item.get("action") or "") != "render":
                ids.add(f"{item.get('series_id')}-ep{item.get('episode'):03d}")
    except Exception:
        pass
    return {i for i in ids if i}


def _in_scope(manifest_path: pathlib.Path, manifest: dict, active_only: bool) -> bool:
    if not active_only:
        return True
    episode_id = str(manifest.get("episode_id") or "")
    if episode_id in _active_episode_ids():
        return True
    rel = manifest_path.as_posix()
    return any(marker in rel for marker in ("episode16", "episode17", "episode18", "episode19",
                                            "episode20", "episode21", "episode22", "episode23",
                                            "episode24", "episode25", "episode26", "episode27",
                                            "episode28", "episode29", "episode30"))


def scan(apply: bool = False, active_only: bool = False) -> dict:
    stamp = _now().replace(":", "").replace(".", "")
    report: dict = {
        "schema_version": 1,
        "checked_at": _now(),
        "scanned": 0,
        "already_valid": 0,
        "repaired": [],
        "needs_manual": [],
        "unchanged_invalid": [],
    }
    for manifest_path in sorted(CONTENT.rglob("episode.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            report["unchanged_invalid"].append({"path": str(manifest_path), "error": "unreadable"})
            continue
        report["scanned"] += 1
        title = str(manifest.get("title") or "")
        opening = _opening(manifest)
        title_bad = bool(validate_episode_title(title))
        overlap_bad = not title_opening_overlap(title, opening).get("passed")
        if not title_bad and not overlap_bad:
            report["already_valid"] += 1
            continue
        if not _in_scope(manifest_path, manifest, active_only):
            report["unchanged_invalid"].append({
                "path": str(manifest_path), "series_id": manifest.get("series_id"),
                "episode": manifest.get("episode"), "old_title": title,
                "reason": "title_policy" if title_bad else "opening_overlap",
            })
            continue
        fixed = _find_fix(manifest)
        entry = {
            "path": str(manifest_path),
            "series_id": manifest.get("series_id"),
            "episode": manifest.get("episode"),
            "old_title": title,
            "new_title": fixed,
            "reason": "title_policy" if title_bad else "opening_overlap",
        }
        if fixed is None:
            report["needs_manual"].append(entry)
            continue
        if apply:
            backup = _backup(manifest_path, stamp)
            _apply(manifest_path, fixed, stamp)
            entry["backup"] = str(backup)
            entry["fixed_at"] = _now()
        report["repaired"].append(entry)
    report["summary"] = {
        "scanned": report["scanned"],
        "already_valid": report["already_valid"],
        "repaired": len(report["repaired"]),
        "needs_manual": len(report["needs_manual"]),
        "invalid_remaining": len(report["needs_manual"]),
    }
    return report


def main() -> None:
    apply = "--apply" in sys.argv
    active_only = "--scope" in sys.argv and sys.argv[sys.argv.index("--scope") + 1] == "active"
    report = scan(apply=apply, active_only=active_only)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if apply:
        report_path = ROOT / "analytics" / "title_repair_report.json"
        temp = report_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(report_path)


if __name__ == "__main__":
    main()