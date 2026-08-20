#!/usr/bin/env python3
"""Render exactly one validated ECHO//100 episode and queue/upload it privately."""

import argparse
import datetime as dt
import json
import sys
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config import Config, ROOT
from src import episodes, review, runtime, safety, thumbnail, tts, upload, video


def run_one(cfg: Config, do_upload: bool = True, dry_run: bool = False) -> Path | None:
    # Verify the OAuth destination before claiming an episode. A wrong Google
    # channel must never consume the READY item or receive an accidental upload.
    if do_upload:
        target = upload.verify_upload_target(cfg)
        print(f"Upload target verified: {target['title']} ({target['id']})")
    claimed = episodes.next_ready()
    if claimed is None:
        print("No READY ECHO//100 episode found. Clean no-op; nothing generic was generated.")
        return None

    episode_path, episode, series = claimed
    stage_complete = False
    job_dir = None
    try:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        job_dir = cfg.output_dir() / f"{stamp}-{episode['episode_id']}"
        job_dir.mkdir(parents=True, exist_ok=False)
        episodes.checkpoint(episode_path, active_job_dir=str(job_dir))

        script = episodes.build_script(episode)
        report = safety.screen(
            cfg,
            script["narration"],
            title=script["title"],
            topic=series["title"],
        )
        if not report["safe"] and cfg.get("safety", "on_fail", default="hold") == "block":
            raise RuntimeError("Episode blocked by the configured safety gate")
        if cfg.get("safety", "append_ai_disclosure", default=True):
            script["description"] = script["description"].rstrip() + \
                "\n\nThis video uses AI-generated narration and original AI-assisted visuals."

        (job_dir / "script.json").write_text(
            json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        runtime.write_stage(
            job_dir, "scripted", episode_id=episode["episode_id"], title=script["title"]
        )

        print(f"[1/5] {episode['episode_id']}: {script['title']}")
        print("[2/5] Generating offline narration...")
        voice_path = job_dir / "voice.mp3"
        timings = tts.synthesize(cfg, script["narration"], voice_path)
        runtime.write_stage(job_dir, "voiced", voice_path=str(voice_path))

        print("[3/5] Rendering protected story artwork...")
        video_path = job_dir / "video.mp4"
        video.build_video(cfg, script, voice_path, timings, video_path)
        runtime.write_stage(job_dir, "rendered", video_path=str(video_path))

        print("[4/5] Building story thumbnail...")
        thumb_path = job_dir / "thumbnail.jpg"
        first_image = script["scenes"][0]["image_path"]
        thumbnail.build_thumbnail(
            cfg,
            script["title"],
            episode["episode_id"],
            thumb_path,
            image_path=first_image,
            series_label=f"ECHO//100 • EPISODE {episode['episode']}",
        )

        meta = {
            "title": script["title"],
            "description": script["description"],
            "tags": script.get("tags", []),
            "thumbnail_path": str(thumb_path),
            "safety": report,
            "privacy": "private",
            "series_id": episode["series_id"],
            "episode_id": episode["episode_id"],
            "quality_profile": episode.get("quality_profile", "episode1-benchmark-v1"),
        }
        youtube_result = None
        if do_upload:
            print("[5/5] Uploading PRIVATE draft to YouTube...")
            try:
                youtube_result = upload.upload_video(
                    cfg, video_path, meta, privacy_override="private"
                )
                meta["url"] = youtube_result["url"]
            except Exception as exc:
                meta["upload_error"] = str(exc)
                print(f"      Upload unavailable; local review draft preserved ({exc})")
        else:
            print("[5/5] No-upload verification mode; local review draft preserved.")

        if dry_run:
            item = {"id": "dry-run", "status": "verified"}
        else:
            item = review.add_item(
                cfg,
                title=script["title"],
                topic=f"{series['title']} / {episode['episode_id']}",
                video_path=video_path,
                thumbnail_path=thumb_path,
                youtube=youtube_result,
                safety=report,
                test_only=False,
                metadata=meta,
            )
        (job_dir / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        runtime.write_stage(
            job_dir,
            "complete",
            review_id=item["id"],
            review_status=item["status"],
            youtube_url=(youtube_result or {}).get("url"),
            dry_run=dry_run,
        )
        stage_complete = True
        if dry_run:
            episodes.update(
                episode_path,
                "ready",
                last_verified_at=dt.datetime.now().isoformat(timespec="seconds"),
                last_verified_job=str(job_dir),
                last_error=None,
            )
        else:
            episodes.update(
                episode_path,
                "queued",
                rendered_at=dt.datetime.now().isoformat(timespec="seconds"),
                job_dir=str(job_dir),
                review_id=item["id"],
                youtube_url=(youtube_result or {}).get("url"),
                upload_error=meta.get("upload_error"),
            )
        print(f"READY FOR REVIEW: {video_path}")
        print(f"Review ID: {item['id']} | YouTube: {(youtube_result or {}).get('url') or 'local only'}")
        return job_dir
    except Exception as exc:
        if not stage_complete:
            try:
                episodes.update(
                    episode_path,
                    "failed",
                    failed_at=dt.datetime.now().isoformat(timespec="seconds"),
                    last_error=str(exc)[:500],
                    active_job_dir=str(job_dir) if job_dir else None,
                )
            except Exception:
                pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="ECHO//100 private-draft automation")
    parser.add_argument("--config", default="config.story.yaml")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="render and verify, then leave the episode READY without queueing")
    parser.add_argument("--preview", action="store_true",
                        help="use a fast low-resolution render while exercising the real pipeline")
    args = parser.parse_args()
    cfg = Config(args.config)
    if args.preview:
        cfg.data.setdefault("video", {}).update({
            "width": 360,
            "height": 640,
            "fps": 15,
            "caption_font_size": 22,
            "background_music": False,
        })
    try:
        with runtime.RunLock(cfg):
            run_one(cfg, do_upload=not (args.no_upload or args.dry_run), dry_run=args.dry_run)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
