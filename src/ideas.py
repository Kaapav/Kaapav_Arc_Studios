"""Pick the next topic for a video.

Order of preference:
  1. Top unused line from topics.txt (deterministic, you control the queue)
  2. LLM-invented fresh topic (only if topics.txt is exhausted AND an LLM key exists)
Used topics are recorded in .cache/used_topics.txt so we never repeat.
"""
from pathlib import Path
from .config import ROOT
from .llm import chat


def _load_used(cache_dir: Path) -> set:
    f = cache_dir / "used_topics.txt"
    if f.exists():
        return {ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()}
    return set()


def _mark_used(cache_dir: Path, topic: str):
    f = cache_dir / "used_topics.txt"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(topic.strip() + "\n")


def _queue_topics() -> list:
    f = ROOT / "topics.txt"
    if not f.exists():
        return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out


def next_topic(cfg) -> str:
    cache = cfg.cache_dir()
    used = _load_used(cache)

    # 1) queue
    for t in _queue_topics():
        if t not in used:
            _mark_used(cache, t)
            return t

    # 2) LLM fallback
    if cfg.has_llm:
        niche = cfg.get("channel", "niche")
        audience = cfg.get("channel", "audience")
        prompt = (
            f"Invent ONE fresh, specific, high-curiosity video topic for a faceless "
            f"YouTube channel about '{niche}' for this audience: {audience}. "
            f"Avoid these already-used topics:\n- " + "\n- ".join(list(used)[-40:]) +
            "\nReturn ONLY the topic as a single short line, no numbering, no quotes."
        )
        topic = chat(cfg, prompt, system="You are a viral content strategist for the Indian market.").strip()
        topic = topic.splitlines()[0].strip().strip('"').strip("-").strip()
        if topic:
            _mark_used(cache, topic)
            return topic

    raise RuntimeError(
        "No topics left in topics.txt and no LLM key set. "
        "Add more lines to topics.txt or set OPENAI_API_KEY."
    )
