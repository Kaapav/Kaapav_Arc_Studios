"""Fail-closed publish checks for unattended ECHO//100 releases."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import ROOT
from . import episodes


BENCHMARK = "episode1-benchmark-v1"


def episode_path(episode_id: str) -> Path:
    match = re.fullmatch(r"echo100-s01e(\d{3})", str(episode_id or ""))
    if not match:
        raise RuntimeError(f"Invalid ECHO//100 episode id: {episode_id!r}")
    return episodes.EPISODES_DIR / f"ep{int(match.group(1)):03d}.json"


def _probe_video(path: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def assert_publishable(item: dict) -> tuple[Path, dict]:
    failures: list[str] = []
    if item.get("series_id") != "echo100":
        failures.append("review item is not an ECHO//100 episode")
    if item.get("quality_profile") != BENCHMARK:
        failures.append("Episode 1 benchmark profile is missing")
    if item.get("status") != "pending":
        failures.append(f"review status is {item.get('status')!r}, not pending")
    safety = item.get("safety") or {}
    if not safety.get("safe") or safety.get("flags") or safety.get("profanity"):
        failures.append("safety gate did not pass cleanly")

    ep_path = episode_path(item.get("episode_id"))
    if not ep_path.exists():
        failures.append(f"episode package missing: {ep_path}")
        episode = {}
    else:
        episode = json.loads(ep_path.read_text(encoding="utf-8"))
        episodes.validate_episode(ep_path, episode, episodes.load_series())
        if episode.get("status") != "queued":
            failures.append(f"episode state is {episode.get('status')!r}, not queued")
        if int(episode.get("episode", 0)) > 1:
            if episode.get("pov_profile") != "third-person-v1":
                failures.append("third-person narration profile is missing")
            narration = " ".join(scene.get("text", "") for scene in episode.get("scenes", []))
            if re.search(r"(?i)\b(i|me|my|mine|we|us|our|ours)\b", narration):
                failures.append("first-person POV drift detected")
            bad_visuals = [
                index for index, scene in enumerate(episode.get("scenes", []), 1)
                if scene.get("visual_status") != "arc_art"
            ]
            if bad_visuals:
                failures.append(f"scenes without approved arc art: {bad_visuals}")
        unique_art = {scene.get("image_path") for scene in episode.get("scenes", [])}
        if len(unique_art) < 4:
            failures.append("fewer than four distinct story shots")
        word_count = sum(len(scene.get("text", "").split()) for scene in episode.get("scenes", []))
        if not 80 <= word_count <= 145:
            failures.append(f"narration is {word_count} words; expected 80-145")

    video_path = Path(item.get("video_path") or "")
    if not video_path.is_absolute():
        video_path = ROOT / video_path
    if not video_path.exists() or video_path.stat().st_size < 500_000:
        failures.append("final video is missing or implausibly small")
    else:
        duration = _probe_video(video_path)
        if not 25 <= duration <= 58:
            failures.append(f"video duration is {duration:.2f}s; expected 25-58s")
    thumbnail = Path(item.get("thumbnail_path") or "")
    if not thumbnail.exists() or thumbnail.stat().st_size < 20_000:
        failures.append("thumbnail is missing or implausibly small")
    title = str(item.get("title") or "")
    if not re.search(r"\|\s*ECHO//100\s+(?:Episode|Ep\.)\s+\d+\s*$", title) or len(title) > 90:
        failures.append("title does not match the locked series format")
    description = str(item.get("description") or "")
    if "AI-assisted" not in description:
        failures.append("AI-assisted disclosure is missing from description")

    if failures:
        raise RuntimeError("Publish gate blocked: " + "; ".join(failures))
    return ep_path, episode
