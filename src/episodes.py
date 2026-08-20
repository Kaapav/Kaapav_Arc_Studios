"""Validated, readiness-gated episode queue for original story automation."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import ROOT


CONTENT_ROOT = ROOT / "content" / "echo100"
SERIES_PATH = CONTENT_ROOT / "series.json"
EPISODES_DIR = CONTENT_ROOT / "episodes"
VALID_STATUSES = {
    "draft", "ready", "rendering", "queued", "scheduled", "published", "failed"
}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid episode JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return data


def _write_json(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_series() -> dict:
    if not SERIES_PATH.exists():
        raise RuntimeError(f"Series configuration missing: {SERIES_PATH}")
    series = _read_json(SERIES_PATH)
    if series.get("canon_status") != "locked":
        raise RuntimeError("Series canon is not locked; automation remains paused")
    return series


def validate_episode(path: Path, episode: dict, series: dict) -> None:
    rules = series.get("episode_rules", {})
    required = ("episode_id", "series_id", "status", "title", "description", "scenes")
    missing = [key for key in required if not episode.get(key)]
    if missing:
        raise RuntimeError(f"{path.name} missing fields: {', '.join(missing)}")
    if episode["series_id"] != series["series_id"]:
        raise RuntimeError(f"{path.name} belongs to a different series")
    if episode.get("canon_version") != series.get("canon_version"):
        raise RuntimeError(f"{path.name} uses an outdated canon version")
    if episode["status"] not in VALID_STATUSES:
        raise RuntimeError(f"{path.name} has invalid status {episode['status']!r}")

    scenes = episode["scenes"]
    minimum = int(rules.get("scene_count_min", 6))
    maximum = int(rules.get("scene_count_max", 10))
    if not minimum <= len(scenes) <= maximum:
        raise RuntimeError(f"{path.name} requires {minimum}-{maximum} scenes; found {len(scenes)}")
    caption_limit = int(rules.get("caption_words_max", 6))
    for index, scene in enumerate(scenes, 1):
        if not scene.get("text") or not scene.get("caption") or not scene.get("image_path"):
            raise RuntimeError(f"{path.name} scene {index} needs text, caption, and image_path")
        if len(scene["caption"].split()) > caption_limit:
            raise RuntimeError(f"{path.name} scene {index} caption exceeds {caption_limit} words")
        asset = (ROOT / scene["image_path"]).resolve()
        if not asset.is_relative_to(ROOT.resolve()) or not asset.exists():
            raise RuntimeError(f"{path.name} scene {index} asset missing or outside project: {asset}")
        if scene.get("allow_stock_video"):
            raise RuntimeError(f"{path.name} scene {index} cannot enable stock footage")
        candidates = scene.get("video_candidates", [])
        if not isinstance(candidates, list):
            raise RuntimeError(f"{path.name} scene {index} video_candidates must be a list")
        for candidate in candidates:
            if isinstance(candidate, str):
                candidate_path = candidate
            elif isinstance(candidate, dict) and candidate.get("path"):
                candidate_path = candidate["path"]
            else:
                raise RuntimeError(f"{path.name} scene {index} has an invalid motion candidate")
            resolved = (ROOT / candidate_path).resolve()
            if not resolved.is_relative_to(ROOT.resolve()):
                raise RuntimeError(f"{path.name} scene {index} motion path is outside the project")


def _recover_stale_render(path: Path, episode: dict) -> dict:
    if episode.get("status") != "rendering":
        return episode
    claimed = float(episode.get("claimed_epoch", 0) or 0)
    if claimed and time.time() - claimed <= 6 * 60 * 60:
        return episode
    active_job = episode.get("active_job_dir")
    if active_job:
        status_path = Path(active_job) / "status.json"
        if status_path.exists():
            try:
                job_status = _read_json(status_path)
                if job_status.get("stage") == "complete":
                    episode["status"] = "ready" if job_status.get("dry_run") else "queued"
                    episode["review_id"] = job_status.get("review_id")
                    episode["youtube_url"] = job_status.get("youtube_url")
                    episode.pop("claimed_epoch", None)
                    _write_json(path, episode)
                    return episode
            except Exception:
                pass
    episode["status"] = "ready"
    episode["last_error"] = "Recovered stale rendering claim"
    episode.pop("claimed_epoch", None)
    _write_json(path, episode)
    return episode


def next_ready() -> tuple[Path, dict, dict] | None:
    series = load_series()
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(EPISODES_DIR.glob("ep*.json")):
        episode = _recover_stale_render(path, _read_json(path))
        validate_episode(path, episode, series)
        if episode["status"] == "ready":
            episode["status"] = "rendering"
            episode["claimed_epoch"] = time.time()
            _write_json(path, episode)
            return path, episode, series
    return None


def update(path: Path, status: str, **fields) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid episode status: {status}")
    episode = _read_json(path)
    episode["status"] = status
    episode.update(fields)
    episode.pop("claimed_epoch", None)
    if status != "rendering":
        episode.pop("active_job_dir", None)
    _write_json(path, episode)
    return episode


def checkpoint(path: Path, **fields) -> dict:
    """Persist in-progress job identity without releasing the rendering claim."""
    episode = _read_json(path)
    episode.update(fields)
    _write_json(path, episode)
    return episode


def build_script(episode: dict) -> dict:
    scenes = []
    for scene in episode["scenes"]:
        item = dict(scene)
        item["allow_stock_video"] = False
        scenes.append(item)
    return {
        "title": episode["title"],
        "description": episode["description"],
        "tags": episode.get("tags", []),
        "narration": " ".join(scene["text"] for scene in scenes),
        "scenes": scenes,
        "series_id": episode["series_id"],
        "episode_id": episode["episode_id"],
    }
