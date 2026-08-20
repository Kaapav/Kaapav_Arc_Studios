#!/usr/bin/env python3
"""Safely upload one QC-approved KAAPAV ARC video to the verified channel.

Designed for the `KAAPAV Upload Video` shortcut. It never publishes a video
immediately: uploads are either private or scheduled for a future IST time.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import Config
from src.upload import _get_service, upload_video


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "output" / "story"
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def known_uploaded_paths() -> set[Path]:
    known: set[Path] = set()
    for manifest in (ROOT / "content").rglob("release_manifest.json"):
        try:
            payload = read_json(manifest)
        except Exception:
            continue
        for episode in payload.get("episodes", []):
            if episode.get("youtube_id") and episode.get("video_path"):
                known.add((ROOT / episode["video_path"]).resolve())
    return known


def verify_local_package(folder: Path) -> dict:
    folder = folder.resolve()
    required = {
        "video": folder / "video.mp4",
        "thumbnail": folder / "thumbnail.jpg",
        "metadata": folder / "metadata.json",
        "qc": folder / "qc_report.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise ValueError(f"Package is missing: {', '.join(missing)}")
    qc = read_json(required["qc"])
    if not qc.get("ok") or qc.get("full_decode") != "passed":
        raise ValueError("Package QC has not passed full decode")
    metadata = read_json(required["metadata"])
    for key in ("title", "description", "tags"):
        if not metadata.get(key):
            raise ValueError(f"Metadata is missing {key}")
    if len(metadata["title"]) > 100:
        raise ValueError("Title exceeds YouTube's 100-character limit")
    if (folder / "upload_result.json").exists():
        result = read_json(folder / "upload_result.json")
        raise ValueError(
            f"Local upload record already exists for {result.get('url', result.get('id', 'this video'))}"
        )
    if required["video"].resolve() in known_uploaded_paths():
        raise ValueError("Release manifest already records this exact video as uploaded")
    return {**required, "metadata_payload": metadata, "qc_payload": qc}


def candidates() -> list[Path]:
    found: list[Path] = []
    if not OUTPUT_ROOT.exists():
        return found
    for video in OUTPUT_ROOT.glob("*/video.mp4"):
        folder = video.parent
        try:
            verify_local_package(folder)
        except ValueError:
            continue
        found.append(folder)
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def choose_folder() -> Path:
    options = candidates()
    if not options:
        raise ValueError("No unuploaded, QC-approved local video packages are available")
    print("\nQC-APPROVED VIDEOS READY TO UPLOAD\n")
    for index, folder in enumerate(options, 1):
        metadata = read_json(folder / "metadata.json")
        duration = read_json(folder / "qc_report.json").get("duration_seconds")
        print(f"{index:2d}. {metadata['title']}  [{duration}s]")
        print(f"    {folder}")
    value = input("\nSelect video number: ").strip()
    if not value.isdigit() or not 1 <= int(value) <= len(options):
        raise ValueError("Invalid video selection")
    return options[int(value) - 1]


def parse_schedule(value: str) -> str:
    try:
        local = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    except ValueError as exc:
        raise ValueError("Schedule must use YYYY-MM-DD HH:MM in IST") from exc
    if local <= datetime.now(IST) + timedelta(minutes=15):
        raise ValueError("Scheduled time must be at least 15 minutes in the future")
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def choose_release_mode() -> tuple[str, str | None]:
    print("\nRelease mode:")
    print("  1. Private review upload")
    print("  2. Schedule for a future IST date/time")
    value = input("Select 1 or 2: ").strip()
    if value == "1":
        return "private", None
    if value == "2":
        schedule = input("Publish time in IST (YYYY-MM-DD HH:MM): ")
        return "scheduled", parse_schedule(schedule)
    raise ValueError("Invalid release mode")


def confirm_exact_title(title: str, mode: str, publish_at: str | None) -> None:
    print("\nFINAL SAFETY CHECK")
    print(f"Title: {title}")
    print(f"Mode: {mode}")
    if publish_at:
        utc_value = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
        print(f"Publish IST: {utc_value.astimezone(IST).strftime('%Y-%m-%d %H:%M %Z')}")
    typed = input("Type the complete title exactly to authorize this upload:\n> ")
    if typed != title:
        raise ValueError("Title confirmation did not match; upload cancelled")


def authoritative_readback(service, video_id: str, timeout_seconds: int = 600) -> dict:
    deadline = time.time() + timeout_seconds
    item = None
    while time.time() < deadline:
        response = service.videos().list(
            part="snippet,status,contentDetails,processingDetails", id=video_id
        ).execute()
        if not response.get("items"):
            raise RuntimeError("Uploaded video was not returned by YouTube readback")
        item = response["items"][0]
        processing = item.get("processingDetails", {}).get("processingStatus", "unknown")
        print(f"YouTube processing: {processing}")
        if processing in {"succeeded", "failed", "rejected"}:
            break
        time.sleep(15)
    if item is None:
        raise RuntimeError("YouTube readback timed out")
    processing = item.get("processingDetails", {}).get("processingStatus")
    if processing != "succeeded":
        raise RuntimeError(f"YouTube processing ended with: {processing}")
    return item


def download_served_thumbnail(item: dict, destination: Path) -> Path:
    thumbnails = item.get("snippet", {}).get("thumbnails", {})
    source = thumbnails.get("maxres") or thumbnails.get("standard") or thumbnails.get("high")
    if not source or not source.get("url"):
        raise RuntimeError("YouTube did not return a served thumbnail URL")
    urllib.request.urlretrieve(source["url"], destination)
    if destination.stat().st_size < 10_000:
        raise RuntimeError("Downloaded YouTube thumbnail is unexpectedly small")
    return destination


def perform_upload(folder: Path, publish_at: str | None) -> dict:
    package = verify_local_package(folder)
    cfg = Config("config.story.yaml")
    service = _get_service(cfg)
    channel = service.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not channel:
        raise RuntimeError("OAuth account returned no YouTube channel")
    actual_id = channel[0]["id"]
    expected_id = cfg.get("youtube", "expected_channel_id")
    if actual_id != expected_id:
        raise RuntimeError(f"Wrong channel: expected {expected_id}, got {actual_id}")

    metadata = dict(package["metadata_payload"])
    metadata["thumbnail_path"] = str(package["thumbnail"])
    result = upload_video(
        cfg,
        package["video"],
        metadata,
        privacy_override="private",
        publish_at=publish_at,
    )
    upload_record = {
        **result,
        "local_video": str(package["video"]),
        "channel_id": actual_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing": "pending",
    }
    write_json(folder / "upload_result.json", upload_record)

    item = authoritative_readback(service, result["id"])
    served = download_served_thumbnail(item, folder / "remote_thumbnail_check.jpg")
    status = item["status"]
    details = item["contentDetails"]
    readback = {
        "id": item["id"],
        "channel_id": item["snippet"]["channelId"],
        "title": item["snippet"]["title"],
        "privacy_status": status["privacyStatus"],
        "publish_at": status.get("publishAt"),
        "made_for_kids": status.get("madeForKids", False),
        "definition": details.get("definition"),
        "duration": details.get("duration"),
        "custom_thumbnail": details.get("hasCustomThumbnail", False),
        "processing_status": item["processingDetails"]["processingStatus"],
        "served_thumbnail": str(served),
    }
    upload_record.update({"processing": "succeeded", "readback": readback})
    write_json(folder / "upload_result.json", upload_record)
    metadata.update({
        "uploaded": True,
        "youtube_id": item["id"],
        "youtube_url": result["url"],
        "publish_at": status.get("publishAt"),
        "status": "scheduled" if status.get("publishAt") else "private_review",
    })
    metadata.pop("thumbnail_path", None)
    write_json(package["metadata"], metadata)
    return upload_record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, help="Rendered output folder")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--private", action="store_true", help="Upload as private review")
    mode.add_argument("--schedule", help="Future IST time: YYYY-MM-DD HH:MM")
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip title typing; only valid with explicit --folder and release mode",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    interactive = args.folder is None
    folder = choose_folder() if interactive else args.folder.resolve()
    package = verify_local_package(folder)
    title = package["metadata_payload"]["title"]

    if args.private:
        mode, publish_at = "private", None
    elif args.schedule:
        mode, publish_at = "scheduled", parse_schedule(args.schedule)
    elif interactive:
        mode, publish_at = choose_release_mode()
    else:
        raise ValueError("Use --private or --schedule with --folder")
    if args.yes and interactive:
        raise ValueError("--yes requires explicit --folder and release mode")
    if not args.yes:
        confirm_exact_title(title, mode, publish_at)

    result = perform_upload(folder, publish_at)
    print("\nUPLOAD VERIFIED")
    print(json.dumps(result["readback"], ensure_ascii=False, indent=2))
    print(result["url"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"\nUPLOAD CANCELLED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
