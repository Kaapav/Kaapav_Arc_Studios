#!/usr/bin/env python3
"""Audit the complete KAAPAV ARC ten-series production universe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from studio_manual_pipeline import validate_manifest


ROOT = Path(__file__).resolve().parent
PLAN = ROOT / "content" / "studio_master_release_plan.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def episode_files(item: dict) -> list[Path]:
    root = ROOT / item["content_root"]
    pattern = "episode*/episode.json" if item["slug"] == "echo30" else "manual_production/episodes/ep*/episode.json"
    return sorted(root.glob(pattern))


def reference_evidence(item: dict) -> dict:
    root = ROOT / item["content_root"]
    slug = item["slug"]
    if slug == "echo30":
        bible = ROOT / "content" / "echo100" / "v2" / "SERIES_BIBLE.md"
        refs = ROOT / "content" / "echo100" / "v2" / "cute_style" / "episode01" / "story_frames"
        return {"bible": str(bible), "bible_exists": bible.exists(), "reference_evidence": str(refs), "reference_exists": refs.exists()}
    if slug == "the_midnight_platform":
        bible = root / "series.json"
        refs = root / "assets" / "references" / "turnarounds"
        prompts = root / "manual_production" / "MISSING_CHARACTER_TURNAROUND_PROMPTS.md"
        return {"bible": str(bible), "bible_exists": bible.exists(), "reference_evidence": str(refs), "reference_exists": refs.exists(), "supporting_turnaround_prompts": str(prompts), "supporting_turnaround_prompts_exist": prompts.exists()}
    bible = root / "SERIES_BIBLE.md"
    refs = root / "CHARACTER_TURNAROUND_PROMPTS.md"
    return {"bible": str(bible), "bible_exists": bible.exists(), "reference_evidence": str(refs), "reference_exists": refs.exists()}


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []
    results = []
    seen_titles: set[str] = set()
    total_scenes = total_existing_images = total_missing_images = 0

    if len(plan.get("series", [])) != 10:
        errors.append(f"master plan must contain 10 series, got {len(plan.get('series', []))}")

    for item in plan["series"]:
        files = episode_files(item)
        numbers: list[int] = []
        local_errors: list[str] = []
        local_warnings: list[str] = []
        contextual_advisories: list[str] = []
        scenes = existing_images = missing_images = 0
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            number = int(data["episode"])
            numbers.append(number)
            scenes += len(data["scenes"])
            title = data["title"]
            key = f"{item['slug']}::{title.casefold()}"
            if key in seen_titles:
                local_errors.append(f"duplicate title: {title}")
            seen_titles.add(key)
            report = validate_manifest(path, require_prompts=True)
            if not (path.parent / "IMAGE_PROMPTS.md").exists():
                local_errors.append(f"episode {number}: IMAGE_PROMPTS.md missing")
            for issue in report["errors"]:
                if ": missing image " in issue:
                    missing_images += 1
                else:
                    local_errors.append(f"episode {number}: {issue}")
            planned_seconds = sum(float(scene.get("planned_seconds", 0)) for scene in data["scenes"])
            for issue in report["warnings"]:
                if "narration has only" in issue and 0 < planned_seconds <= 35:
                    contextual_advisories.append(f"episode {number}: {issue} (accepted for {planned_seconds:g}s dialogue-led format)")
                else:
                    local_warnings.append(f"episode {number}: {issue}")
            existing_images += len(report.get("images", []))
            if number > 10 or item["slug"] != "echo30":
                upload_record = path.parent / "upload_result.json"
                if upload_record.exists():
                    local_errors.append(f"unfinished episode {number} has upload_result.json")

        expected = set(range(1, 31))
        missing_numbers = sorted(expected - set(numbers))
        extra_numbers = sorted(set(numbers) - expected)
        if len(files) != 30 or missing_numbers or extra_numbers:
            local_errors.append(f"episode coverage files={len(files)} missing={missing_numbers} extra={extra_numbers}")
        if len(numbers) != len(set(numbers)):
            local_errors.append("duplicate episode numbers")
        if "script_and_prompt_pack_complete" not in item.get("status", ""):
            local_errors.append(f"master status is stale: {item.get('status')}")
        references = reference_evidence(item)
        if not references.get("bible_exists"):
            local_errors.append("series bible/source record missing")
        if not references.get("reference_exists"):
            local_errors.append("character/reference evidence missing")

        results.append({
            "sequence": item["sequence"],
            "slug": item["slug"],
            "title": item["public_title"],
            "episode_manifests": len(files),
            "episode_numbers": sorted(numbers),
            "scene_scripts": scenes,
            "existing_story_images": existing_images,
            "pending_story_images": missing_images,
            "non_image_errors": local_errors,
            "warnings": local_warnings,
            "contextual_advisories": contextual_advisories,
            "references": references,
        })
        errors.extend(f"{item['public_title']}: {issue}" for issue in local_errors)
        warnings.extend(f"{item['public_title']}: {issue}" for issue in local_warnings)
        total_scenes += scenes
        total_existing_images += existing_images
        total_missing_images += missing_images

    required_tools = [
        ROOT / "studio_manual_pipeline.py",
        ROOT / "story_blueprint_compiler.py",
        ROOT / "studio_upload_shortcut.py",
        ROOT / "KAAPAV_Upload_Video.cmd",
        ROOT / "KAAPAV Upload Video.lnk",
    ]
    missing_tools = [str(path) for path in required_tools if not path.exists()]
    errors.extend(f"missing required tool: {path}" for path in missing_tools)
    uploader_text = (ROOT / "studio_upload_shortcut.py").read_text(encoding="utf-8")
    uploader_checks = {
        "verifies_channel": "expected_channel_id" in uploader_text,
        "blocks_immediate_public": 'mode, publish_at = "private", None' in uploader_text and 'mode, publish_at = "scheduled"' in uploader_text and 'mode, publish_at = "public"' not in uploader_text,
        "requires_qc": "qc_report.json" in uploader_text,
        "duplicate_guard": "Local upload record already exists" in uploader_text and "Release manifest already records" in uploader_text,
    }
    for name, ok in uploader_checks.items():
        if not ok:
            errors.append(f"uploader safety check absent: {name}")
    if sum(item["episode_manifests"] for item in results) != 300:
        errors.append("universe must contain exactly 300 episode manifests")
    if total_scenes != 2340:
        errors.append(f"universe must contain exactly 2340 scene scripts, got {total_scenes}")

    report = {
        "schema_version": 1,
        "status": "pass" if not errors and not warnings else "fail",
        "series_count": len(results),
        "episode_manifest_count": sum(item["episode_manifests"] for item in results),
        "scene_script_count": total_scenes,
        "existing_story_image_count": total_existing_images,
        "pending_story_image_count": total_missing_images,
        "series": results,
        "uploader_safety": uploader_checks,
        "required_tools": [{"path": str(path), "exists": path.exists(), "sha256": sha256(path) if path.is_file() else None} for path in required_tools],
        "errors": errors,
        "warnings": warnings,
        "completion_definition": "All 300 episode story/image-prompt/video-script manifests structurally complete; unfinished images/videos remain upload-blocked.",
    }
    out = ROOT / "content" / "studio_universe_audit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "series_count", "episode_manifest_count", "scene_script_count", "existing_story_image_count", "pending_story_image_count", "errors", "warnings")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
