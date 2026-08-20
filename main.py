#!/usr/bin/env python3
"""
Faceless YouTube automation — one command produces (and optionally publishes) a video.

    python main.py                 # full run: pick topic -> render -> upload
    python main.py --no-upload     # render only, skip YouTube (great for testing)
    python main.py --topic "Why the sky is blue"   # force a specific topic
    python main.py --config config.yaml

Run it daily via cron / GitHub Actions (see .github/workflows/daily.yml) and the
channel posts on its own.
"""
import argparse
import datetime as dt
import json
import re
import sys
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config import Config
from src import (ideas, script_writer, tts, video as video_mod, thumbnail,
                 upload as upload_mod, safety, review, runtime)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:50] or "video"


def run(cfg: Config, topic: str | None, do_upload: bool):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    # 1) topic
    topic = topic or ideas.next_topic(cfg)
    print(f"\n[1/7] Topic: {topic}")

    # 2) script + metadata
    print("[2/7] Writing script...")
    script = script_writer.write_script(cfg, topic)
    print(f"      Title: {script['title']}")
    degraded_script = bool(script.get("_fallback_mode"))
    if degraded_script:
        print("      ⚠ fallback script: this draft will remain PRIVATE for review")
    if not cfg.has_llm:
        print("      ⚠ TEST-ONLY: no LLM key; fallback script is not publishable content.")
        if do_upload:
            print("      Upload disabled until OPENAI_API_KEY is configured.")
            do_upload = False

    # 3) content-safety gate (protects the channel from strikes/demonetization)
    print("[3/7] Safety screening...")
    report = safety.screen(cfg, script["narration"], title=script["title"], topic=topic)
    if report["safe"]:
        print("      ✅ safe")
    else:
        cats = ", ".join(f["category"] for f in report["flags"]) or \
               f"profanity: {', '.join(report['profanity'])}"
        on_fail = cfg.get("safety", "on_fail", default="hold")
        if on_fail == "block":
            print(f"      ⛔ BLOCKED ({cats}) — skipping this video entirely.")
            return None
        print(f"      ⚠ HELD ({cats}) — will render + upload PRIVATE, but it will NOT")
        print("        be publishable until you review it (python review.py list).")

    # transparency: viewers + YouTube both reward honesty about AI content
    if cfg.get("safety", "append_ai_disclosure", default=True):
        script["description"] = script.get("description", "").rstrip() + \
            "\n\nThis video uses AI-generated narration and visuals."
    if cfg.pexels_key and any(not scene.get("image_path") for scene in script.get("scenes", [])):
        script["description"] = script.get("description", "").rstrip() + \
            "\n\nStock media may include footage provided by Pexels: https://www.pexels.com"

    job_dir = cfg.output_dir() / f"{stamp}-{slugify(topic)}"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    runtime.write_stage(job_dir, "scripted", topic=topic, title=script["title"])

    # 4) voiceover
    print("[4/7] Generating voiceover...")
    voice_path = job_dir / "voice.mp3"
    word_timings = tts.synthesize(cfg, script["narration"], voice_path)
    print(f"      {len(word_timings)} word timings captured")
    runtime.write_stage(job_dir, "voiced", voice_path=str(voice_path))

    # 5) video
    print("[5/7] Rendering video (this is the slow part)...")
    video_path = job_dir / "video.mp4"
    video_mod.build_video(cfg, script, voice_path, word_timings, video_path)
    print(f"      Saved {video_path}")
    runtime.write_stage(job_dir, "rendered", video_path=str(video_path))

    # 6) thumbnail
    print("[6/7] Building thumbnail...")
    thumb_path = job_dir / "thumbnail.jpg"
    kw = script["scenes"][0].get("keywords", topic) if script.get("scenes") else topic
    thumbnail.build_thumbnail(cfg, script["title"], kw, thumb_path)
    runtime.write_stage(job_dir, "thumbnailed", thumbnail_path=str(thumb_path))

    # 7) upload + publish decision
    meta = {"title": script["title"], "description": script["description"],
            "tags": script.get("tags", []), "safety": report,
            "thumbnail_path": str(thumb_path)}
    yt_result = None
    # FULL-AUTO mode: safety-passed videos go public immediately, no human step.
    # Flagged videos ALWAYS upload private and wait for review, regardless of mode.
    auto_publish = cfg.get("youtube", "auto_publish", default=False)
    go_public = auto_publish and report["safe"] and not degraded_script
    privacy = "public" if go_public else "private"
    if do_upload:
        print(f"[7/7] Uploading to YouTube as {privacy.upper()}"
              + (" (auto-publish: safety passed)" if go_public else " draft..."))
        try:
            yt_result = upload_mod.upload_video(cfg, video_path, meta,
                                                privacy_override=privacy)
            meta["url"] = yt_result["url"]
        except Exception as e:
            print(f"      Upload failed: {e}")
            meta["upload_error"] = str(e)
            go_public = False
    else:
        print("[7/7] Skipping upload (--no-upload). Still queued for review (local file).")
        go_public = False

    if go_public and yt_result:
        item = review.add_item(cfg, title=script["title"], topic=topic,
                               video_path=video_path, thumbnail_path=thumb_path,
                               youtube=yt_result, safety=report,
                               test_only=not cfg.has_llm,
                               status="approved", metadata=meta)
        print(f"      🚀 LIVE: {yt_result['url']}  (logged as {item['id']})")
    else:
        item = review.add_item(cfg, title=script["title"], topic=topic,
                               video_path=video_path, thumbnail_path=thumb_path,
                               youtube=yt_result, safety=report,
                               test_only=not cfg.has_llm, metadata=meta)
        print(f"      Queued for review as {item['id']} (status: {item['status']})")

    (job_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    runtime.write_stage(
        job_dir,
        "complete",
        review_id=item["id"],
        review_status=item["status"],
        youtube_url=(yt_result or {}).get("url"),
    )
    print(f"\nDone. Everything is in: {job_dir}")
    return job_dir


def main():
    ap = argparse.ArgumentParser(description="Faceless YouTube automation pipeline")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--topic", default=None, help="override the topic for this run")
    ap.add_argument("--no-upload", action="store_true", help="render only, don't publish")
    ap.add_argument("--count", type=int, default=1,
                    help="generate this many independent drafts sequentially")
    args = ap.parse_args()

    cfg = Config(args.config)
    print(f"Channel: {cfg.get('channel', 'name')} | LLM: {cfg.has_llm} | "
          f"Pexels: {bool(cfg.pexels_key)} | Format: {cfg.get('video', 'format')}")
    count = max(1, min(args.count, 7))
    failures = 0
    with runtime.RunLock(cfg):
        for index in range(count):
            print(f"\n=== Draft {index + 1}/{count} ===")
            topic = args.topic if index == 0 else None
            try:
                run(cfg, topic, do_upload=not args.no_upload)
            except Exception:
                failures += 1
                traceback.print_exc()
                print(f"Draft {index + 1} failed; continuing with the next slot.")
    if failures == count:
        sys.exit(1)


if __name__ == "__main__":
    main()
