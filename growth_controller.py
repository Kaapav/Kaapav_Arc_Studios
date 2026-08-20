#!/usr/bin/env python3
"""Evidence-gated ECHO//100 release controller.

The renderer may build a large local vault, but this controller exposes only a
small cohort to YouTube. After the cohort has enough time to collect data, weak
results pause the next release instead of mass-publishing a losing template.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

from src.config import Config, ROOT
from src import episodes, llm, performance, quality, review
from maintain_schedule import IST, _next_slots, _parse_publish_at, _refresh_scheduled, _wait_for_renderer


CURATED_PACKAGING = {
    4: "His Bedroom Suddenly Lost Gravity 😳 | ECHO//100 Episode 4",
    5: "The Red Door Opened to 1994 | ECHO//100 Episode 5",
    6: "His Robot Was Covered in Messages From the Future | ECHO//100 Episode 6",
    7: "He Tried to Scream—Only Code Came Out | ECHO//100 Episode 7",
    8: "His Family Photos Kept Rewriting Themselves | ECHO//100 Episode 8",
    9: "His Robot Locked Him Inside to Save Him | ECHO//100 Episode 9",
    10: "Saving Reality Would Erase His Best Friend | ECHO//100 Episode 10",
    11: "His Hand Started Speaking With Stolen Voices | ECHO//100 Episode 11",
    12: "His Shadow Built a Map of a Missing City | ECHO//100 Episode 12",
    13: "He Fell Into a City Trapped in a Time Loop | ECHO//100 Episode 13",
    14: "Every Clock Began Running Backward | ECHO//100 Episode 14",
}


def _episode_number(value: str) -> int | None:
    match = re.fullmatch(r"echo100-s01e(\d{3})", str(value or ""))
    return int(match.group(1)) if match else None


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _state_path(cfg: Config) -> Path:
    return ROOT / cfg.get("growth", "state_file", default="analytics/growth_state.json")


def _load_state(cfg: Config) -> dict:
    path = _state_path(cfg)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        summary, _ = performance.collect(cfg)
        baseline = int(summary.get("subscribers", 0))
    except Exception:
        baseline = None
    state = {
        "version": 1,
        "phase": "launch",
        "released_through": 3,
        "cohort_start": 4,
        "cohort_end": int(cfg.get("growth", "first_cohort_end", default=7)),
        "baseline_subscribers": baseline,
        "created_at": dt.datetime.now(IST).isoformat(timespec="seconds"),
    }
    _atomic_json(path, state)
    return state


def _save_state(cfg: Config, state: dict) -> None:
    state["updated_at"] = dt.datetime.now(IST).isoformat(timespec="seconds")
    _atomic_json(_state_path(cfg), state)


def _repackage_pending(cfg: Config, start: int, end: int) -> None:
    items = review.load_queue(cfg)
    changed_queue = False
    for number in range(start, end + 1):
        ep_path = episodes.EPISODES_DIR / f"ep{number:03d}.json"
        episode = json.loads(ep_path.read_text(encoding="utf-8"))
        if episode.get("status") in {"published", "scheduled"}:
            continue
        title = CURATED_PACKAGING.get(number)
        if not title:
            plot = " ".join(scene.get("text", "") for scene in episode.get("scenes", []))
            response = llm.chat(
                cfg,
                user_prompt=(
                    f"Episode number: {number}\nPlot: {plot}\n"
                    "Return only one truthful curiosity-driven YouTube Shorts title. "
                    "Maximum 58 characters before the suffix. Use plain English, reveal the "
                    "impossible event immediately, and do not use generic words like protocol, "
                    "echoes, archive, mystery, shocking, or unbelievable."
                ),
                system="You package original animated science-fiction stories for new viewers.",
                temperature=0.7,
                max_tokens=80,
            )
            clean = re.sub(r"^[\s\"']+|[\s\"']+$", "", response.splitlines()[0]).strip()
            clean = re.sub(r"\s*\|\s*ECHO.*$", "", clean, flags=re.IGNORECASE).strip()
            if not clean or len(clean) > 58:
                raise RuntimeError(f"LLM returned an invalid discovery title for Episode {number}")
            title = f"{clean} | ECHO//100 Episode {number}"
        episode["title"] = title
        episode["packaging_profile"] = "curiosity-v2"
        _atomic_json(ep_path, episode)
        episode_id = episode["episode_id"]
        for item in items:
            if item.get("episode_id") == episode_id and item.get("status") == "pending":
                item["title"] = title
                item["packaging_profile"] = "curiosity-v2"
                changed_queue = True
    if changed_queue:
        review.save_queue(cfg, items)


def _schedule_cohort(cfg: Config, state: dict) -> None:
    start, end = int(state["cohort_start"]), int(state["cohort_end"])
    _repackage_pending(cfg, start, end)
    items = _refresh_scheduled(cfg, review.load_queue(cfg))
    already = {
        _episode_number(item.get("episode_id"))
        for item in items
        if item.get("status") in {"scheduled", "approved"}
    }
    pending = sorted(
        [
            item for item in items
            if item.get("status") == "pending"
            and (number := _episode_number(item.get("episode_id"))) is not None
            and start <= number <= end
            and number not in already
        ],
        key=lambda item: _episode_number(item.get("episode_id")) or 0,
    )
    missing_numbers = [number for number in range(start, end + 1) if number not in already]
    pending_numbers = {_episode_number(item.get("episode_id")) for item in pending}
    not_ready = [number for number in missing_numbers if number not in pending_numbers]
    if not_ready:
        raise RuntimeError(f"Cohort episodes are not rendered and queued: {not_ready}")

    schedule_time = cfg.get("growth", "schedule_time", default="09:00")
    hour, minute = (int(part) for part in schedule_time.split(":", 1))
    slots = _next_slots(items, len(pending), hour, minute)
    for item, publish_at in zip(pending, slots):
        quality.assert_publishable(item)
        print(review.schedule(cfg, item["id"], publish_at))
        ep_path = quality.episode_path(item["episode_id"])
        queued_item = next(x for x in review.load_queue(cfg) if x["id"] == item["id"])
        episodes.update(
            ep_path,
            "scheduled",
            publish_at=publish_at,
            youtube_id=queued_item["youtube_id"],
            youtube_url=queued_item["youtube_url"],
            review_id=item["id"],
            last_error=None,
        )
    state["phase"] = "collecting"
    state["released_through"] = end
    state["scheduled_count"] = len(pending)
    _save_state(cfg, state)
    print(f"GROWTH COHORT READY: Episodes {start}-{end}; one Short daily")


def _cohort_publications(cfg: Config, start: int, end: int) -> list[dict]:
    items = _refresh_scheduled(cfg, review.load_queue(cfg))
    return [
        item for item in items
        if item.get("status") == "approved"
        and (number := _episode_number(item.get("episode_id"))) is not None
        and start <= number <= end
    ]


def _evaluate(cfg: Config, state: dict) -> None:
    start, end = int(state["cohort_start"]), int(state["cohort_end"])
    public = _cohort_publications(cfg, start, end)
    if len(public) < end - start + 1:
        print(f"GROWTH GATE COLLECTING: {len(public)}/{end - start + 1} cohort episodes public")
        return
    published_times = []
    for number in range(start, end + 1):
        ep = json.loads((episodes.EPISODES_DIR / f"ep{number:03d}.json").read_text(encoding="utf-8"))
        value = ep.get("published_at")
        if value:
            published_times.append(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
    if not published_times:
        print("GROWTH GATE COLLECTING: publication timestamps unavailable")
        return
    last_public = max(value.astimezone(dt.timezone.utc) for value in published_times)
    wait_hours = int(cfg.get("growth", "evaluation_hours", default=72))
    age = dt.datetime.now(dt.timezone.utc) - last_public
    if age < dt.timedelta(hours=wait_hours):
        remaining = dt.timedelta(hours=wait_hours) - age
        print(f"GROWTH GATE COLLECTING: evaluation in {remaining}")
        return

    summary, rows = performance.collect(cfg)
    cohort_ids = {item.get("youtube_id") for item in public}
    cohort_rows = [row for row in rows if row.get("video_id") in cohort_ids]
    total_views = sum(int(row.get("views", 0)) for row in cohort_rows)
    total_likes = sum(int(row.get("likes", 0)) for row in cohort_rows)
    average_views = total_views / max(1, len(cohort_rows))
    baseline = state.get("baseline_subscribers")
    subscriber_gain = (
        int(summary.get("subscribers", 0)) - int(baseline)
        if baseline is not None else 0
    )
    minimum_average = int(cfg.get("growth", "minimum_average_views", default=100))
    minimum_likes = int(cfg.get("growth", "minimum_total_likes", default=3))
    passed = average_views >= minimum_average and (total_likes >= minimum_likes or subscriber_gain > 0)
    state["last_evaluation"] = {
        "evaluated_at": dt.datetime.now(IST).isoformat(timespec="seconds"),
        "episodes": f"{start}-{end}",
        "total_views": total_views,
        "average_views": round(average_views, 2),
        "total_likes": total_likes,
        "subscriber_gain": subscriber_gain,
        "passed": passed,
    }
    if passed:
        size = int(cfg.get("growth", "cohort_size", default=7))
        state["phase"] = "ready_for_next_cohort"
        state["cohort_start"] = end + 1
        state["cohort_end"] = min(100, end + size)
        state["baseline_subscribers"] = int(summary.get("subscribers", 0))
        _save_state(cfg, state)
        print(f"GROWTH GATE PASSED: average {average_views:.1f} views; next cohort unlocked")
    else:
        state["phase"] = "paused_for_repackage"
        _save_state(cfg, state)
        print(
            "GROWTH GATE PAUSED: future publication stopped; "
            f"average_views={average_views:.1f}, likes={total_likes}, subscriber_gain={subscriber_gain}"
        )


def run(cfg: Config, wait_for_render: bool) -> None:
    if wait_for_render:
        _wait_for_renderer(cfg, max_hours=24)
    state = _load_state(cfg)
    phase = state.get("phase")
    if phase in {"launch", "ready_for_next_cohort"}:
        _schedule_cohort(cfg, state)
    elif phase == "collecting":
        _evaluate(cfg, state)
    elif phase == "paused_for_repackage":
        print("GROWTH GATE PAUSED: no future episode will be published until repackaged")
    else:
        raise RuntimeError(f"Unknown growth phase: {phase!r}")


def main() -> None:
    raise SystemExit(
        "growth_controller.py is retired. Evidence learning and future scheduling "
        "are owned by studio_autopilot.py."
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-for-render", action="store_true")
    args = parser.parse_args()
    run(Config("config.story.yaml"), args.wait_for_render)


if __name__ == "__main__":
    main()
