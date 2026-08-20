"""Human-in-the-loop review queue.

Each morning the pipeline renders a video, uploads it as PRIVATE, runs the safety
gate, and appends an entry here. Nothing goes public until you approve it — via the
top-level `review.py` CLI (`list` / `approve` / `reject` / `approve-safe`).

Queue is a simple JSON list at review.queue_file (default output/review_queue.json).
Statuses:
  pending  — safe, waiting for your OK
  held     — safety gate flagged it; needs manual review, will NOT auto-publish
  approved — published (public)
  rejected — you declined; stays private
"""
import json
from datetime import datetime
from pathlib import Path

from .config import ROOT


def _queue_path(cfg) -> Path:
    rel = cfg.get("review", "queue_file", default="output/review_queue.json")
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_queue(cfg) -> list:
    p = _queue_path(cfg)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Review queue is unreadable; refusing to overwrite {p}: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError(f"Review queue must contain a JSON list: {p}")
    return data


def save_queue(cfg, items: list):
    path = _queue_path(cfg)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def add_item(cfg, *, title, topic, video_path, thumbnail_path=None,
             youtube=None, safety=None, status=None, test_only=False,
             metadata=None) -> dict:
    """Append a new review entry. `youtube` is the dict from upload_video (or None).
    `status` override lets auto-publish log items directly as 'approved'."""
    items = load_queue(cfg)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe = bool(safety.get("safe", True)) if safety else True
    item = {
        "id": stamp,
        "created": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "topic": topic,
        "video_path": str(video_path),
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "description": (metadata or {}).get("description", ""),
        "tags": (metadata or {}).get("tags", []),
        "series_id": (metadata or {}).get("series_id"),
        "episode_id": (metadata or {}).get("episode_id"),
        "quality_profile": (metadata or {}).get("quality_profile"),
        "release_kind": (metadata or {}).get("release_kind", "short"),
        "episode_count": (metadata or {}).get("episode_count"),
        "youtube_id": (youtube or {}).get("id"),
        "youtube_url": (youtube or {}).get("url"),
        "safety": safety or {"safe": True},
        "test_only": bool(test_only),
        "status": status or ("test_only" if test_only else ("pending" if safe else "held")),
    }
    items.append(item)
    save_queue(cfg, items)
    return item


def _find(items, item_id):
    for it in items:
        if it["id"] == item_id:
            return it
    return None


def pending(cfg):
    return [it for it in load_queue(cfg) if it["status"] in ("pending", "held")]


def approve(cfg, item_id, force=False) -> str:
    """Legacy command retained as a safe refusal; public-now is no longer allowed."""
    items = load_queue(cfg)
    it = _find(items, item_id)
    if not it:
        return f"No item {item_id}."
    if it.get("test_only") and not force:
        return (f"{item_id} is TEST-ONLY because it was generated without an LLM key. "
                "Configure OPENAI_API_KEY and generate a real draft before publishing.")
    if it["status"] == "held" and not force:
        flags = ", ".join(f["category"] for f in it["safety"].get("flags", [])) or "profanity"
        return (f"{item_id} was HELD by the safety gate ({flags}). "
                f"Review it, then re-run with --force if it's genuinely fine.")
    return (
        "Immediate publication is disabled. The autopilot must assign a future "
        "slot and pass the strict audit immediately before scheduling."
    )


def schedule(cfg, item_id, publish_at: str) -> str:
    """Upload/schedule one safe pending episode; YouTube publishes it server-side."""
    items = load_queue(cfg)
    it = _find(items, item_id)
    if not it:
        raise RuntimeError(f"No review item {item_id}")
    if it.get("status") != "pending":
        raise RuntimeError(f"{item_id} is {it.get('status')!r}, not pending")
    if it.get("test_only"):
        raise RuntimeError(f"{item_id} is test-only and cannot be scheduled")
    safety = it.get("safety") or {}
    if not safety.get("safe") or safety.get("flags") or safety.get("profanity"):
        raise RuntimeError(f"{item_id} did not pass the safety gate")

    from . import upload as upload_mod
    upload_meta = {
        "title": it["title"],
        "tags": it.get("tags", []),
        "description": it.get("description", ""),
        "thumbnail_path": it.get("thumbnail_path"),
        "safety": safety,
        "publish_at": publish_at,
        "series_id": it.get("series_id"),
        "episode_id": it.get("episode_id"),
        "release_kind": it.get("release_kind", "short"),
        "episode_count": it.get("episode_count"),
    }
    if not it.get("youtube_id"):
        res = upload_mod.upload_video(
            cfg,
            Path(it["video_path"]),
            upload_meta,
            privacy_override="private",
            publish_at=publish_at,
        )
        it["youtube_id"], it["youtube_url"] = res["id"], res["url"]
        it["audit_id"] = res.get("audit_id")
    else:
        res = upload_mod.schedule_video(
            cfg,
            it["youtube_id"],
            publish_at,
            video_path=Path(it["video_path"]),
            meta=upload_meta,
        )
    if not res.get("thumbnail_set") or not res.get("schedule_confirmed"):
        it["status"] = "private_uploaded"
        it["publish_at"] = None
        it["last_error"] = res.get("status") or "remote release contract not confirmed"
        save_queue(cfg, items)
        raise RuntimeError(f"Scheduling held private: {it['last_error']}")
    it["status"] = "scheduled"
    it["publish_at"] = publish_at
    save_queue(cfg, items)
    return f"Scheduled {item_id}: {it['youtube_url']} -> {publish_at}"


def reject(cfg, item_id) -> str:
    items = load_queue(cfg)
    it = _find(items, item_id)
    if not it:
        return f"No item {item_id}."
    it["status"] = "rejected"  # video stays private on YouTube
    save_queue(cfg, items)
    return f"Rejected {item_id} (kept private)."


def approve_all_safe(cfg) -> str:
    """One command to publish every safe, pending item. Skips held/flagged ones."""
    out = []
    for it in list(pending(cfg)):
        if it["status"] == "pending":
            out.append(approve(cfg, it["id"]))
    return "\n".join(out) if out else "Nothing safe & pending to publish."
