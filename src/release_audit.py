"""Fail-closed, content-aware pre-publish audit for KAAPAV ARC releases.

The audit is deliberately enforced at the upload boundary.  A caller cannot
turn a local render into a YouTube upload unless the exact bytes being sent
have a fresh passing report.  Reports contain hashes, never credentials.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from .config import ROOT
from .title_policy import title_opening_overlap, validate_episode_title


AUDIT_SCHEMA = 1
AUDIT_NAME = "prepublish_audit.json"
PLACEHOLDER_RE = re.compile(r"(?i)\b(?:todo|tbd|placeholder|sample title|test video)\b")
SECRET_NAMES = {
    ".env", "token.json", "client_secret.json", "credentials.json",
    "service-account.json", "service_account.json",
}
SECRET_PATTERNS = (
    "client_secret", "refresh_token", "private_key", "access_token",
)
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class PublishAuditError(RuntimeError):
    """Raised when a package is not safe to upload or schedule."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishAuditError(f"Unreadable JSON: {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublishAuditError(f"Expected a JSON object: {path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_sha256(meta: dict[str, Any]) -> str:
    controlled = {
        key: meta.get(key)
        for key in (
            "title", "description", "tags", "series_id", "episode_id", "episode",
            "release_kind", "episode_count", "thumbnail_path",
        )
    }
    encoded = json.dumps(controlled, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve(path_value: str | Path | None, base: Path) -> Path:
    path = Path(path_value or "")
    return path if path.is_absolute() else (base / path).resolve()


def _probe(video_path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(video_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise PublishAuditError(f"ffprobe could not validate {video_path.name}: {exc}") from exc


def _full_decode(video_path: Path) -> None:
    command = [
        "ffmpeg", "-v", "error", "-xerror", "-i", str(video_path),
        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL",
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise PublishAuditError(f"Full media decode failed: {detail[-500:]}") from exc


def build_technical_qc(video_path: Path, scene_count: int) -> dict[str, Any]:
    """Create renderer evidence; the upload boundary independently rechecks it."""
    video_path = Path(video_path).resolve()
    probe = _probe(video_path)
    _full_decode(video_path)
    duration = float((probe.get("format") or {}).get("duration") or 0)
    columns = min(4, max(1, scene_count))
    rows = math.ceil(scene_count / columns)
    contact = video_path.parent / "qc_contact.jpg"
    sample_rate = max(0.01, scene_count / max(duration, 0.01))
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video_path),
        "-vf", f"fps={sample_rate},scale=360:-1,tile={columns}x{rows}",
        "-frames:v", "1", str(contact),
    ], capture_output=True, text=True, check=True)
    streams = probe.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    errors = []
    if not video_stream:
        errors.append("encoded file has no video stream")
    if not audio_stream:
        errors.append("encoded file has no audio stream")
    if duration <= 0:
        errors.append("encoded duration is invalid")
    return {
        "ok": not errors,
        "full_decode": "passed",
        "duration_seconds": duration,
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "contact_sheet": str(contact),
        "errors": errors,
    }


def _image_health(path: Path, *, thumbnail: bool = False) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            variance = sum(ImageStat.Stat(rgb.resize((128, 128))).var) / 3.0
    except (OSError, ValueError) as exc:
        raise PublishAuditError(f"Invalid image {path.name}: {exc}") from exc
    if thumbnail and (width < 1280 or height < 720 or width <= height):
        raise PublishAuditError(
            f"Thumbnail must be horizontal and at least 1280x720; got {width}x{height}"
        )
    if variance < 40:
        raise PublishAuditError(f"Image is blank or nearly blank: {path.name}")
    return {"width": width, "height": height, "variance": round(variance, 2)}


def _find_episode_package(script: dict[str, Any]) -> tuple[Path, dict[str, Any], list[Path]]:
    scenes = script.get("scenes") or []
    if not isinstance(scenes, list) or len(scenes) < 5:
        raise PublishAuditError("Script must contain at least five purposeful scenes")
    image_paths: list[Path] = []
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise PublishAuditError(f"Scene {index} is malformed")
        if not str(scene.get("text") or "").strip():
            raise PublishAuditError(f"Scene {index} has no narration")
        if not str(scene.get("caption") or "").strip():
            raise PublishAuditError(f"Scene {index} has no caption declaration")
        raw = scene.get("image_path") or scene.get("image")
        path = _resolve(raw, ROOT)
        if not path.exists() or path.stat().st_size < 5_000:
            raise PublishAuditError(f"Scene {index} image is missing or too small")
        image_paths.append(path)
    parents = {path.parent.parent for path in image_paths}
    if len(parents) != 1:
        raise PublishAuditError("Story frames do not belong to one episode package")
    episode_root = parents.pop()
    episode_path = episode_root / "episode.json"
    if not episode_path.exists():
        raise PublishAuditError(f"Episode manifest is missing: {episode_path}")
    episode = _read_json(episode_path)
    return episode_root, episode, image_paths


def _check_story_assets(script: dict[str, Any]) -> dict[str, Any]:
    episode_root, episode, image_paths = _find_episode_package(script)
    qc_path = episode_root / "image_qc.json"
    if not qc_path.exists():
        raise PublishAuditError("Visual QC acceptance record is missing")
    image_qc = _read_json(qc_path)
    if image_qc.get("status") != "accepted":
        raise PublishAuditError(f"Visual QC status is {image_qc.get('status')!r}, not accepted")
    accepted = {str(value).replace("\\", "/") for value in image_qc.get("accepted_frames", [])}
    expected = {
        str(Path(scene.get("image") or "")).replace("\\", "/")
        for scene in (episode.get("scenes") or [])
    }
    if not expected or accepted != expected:
        raise PublishAuditError("Visual QC acceptance does not exactly match the episode frames")
    hashes = [_sha256(path) for path in image_paths]
    for index, path in enumerate(image_paths, 1):
        health = _image_health(path)
        if health["height"] <= health["width"]:
            raise PublishAuditError(f"Story frame {index} is not vertical")
    if len(set(hashes)) != len(hashes):
        raise PublishAuditError("Duplicate story frames detected")
    intentions = {
        re.sub(r"\s+", " ", str(scene.get("image_prompt") or "")).strip().lower()
        for scene in (episode.get("scenes") or [])
    }
    if "" in intentions or len(intentions) != len(episode.get("scenes") or []):
        raise PublishAuditError("Repeated or missing visual intentions detected")
    if not str(episode.get("permanent_story_change") or "").strip():
        raise PublishAuditError("Episode has no permanent story change")

    registry_path = None
    style_root = None
    for parent in (episode_root, *episode_root.parents):
        candidate = parent / "characters" / "character_registry.json"
        if candidate.exists():
            style_root, registry_path = parent, candidate
            break
        if parent == ROOT:
            break
    if registry_path is None or style_root is None:
        raise PublishAuditError("Locked character registry is missing")
    registry = _read_json(registry_path)
    if registry.get("pending_before_first_appearance"):
        raise PublishAuditError("Character references are still pending approval")
    locked = registry.get("locked") or []
    if not locked:
        raise PublishAuditError("Character registry contains no locked identities")
    for entry in locked:
        if entry.get("status") != "locked":
            raise PublishAuditError(f"Unlocked character identity: {entry.get('character', 'unknown')}")
        reference = style_root / "characters" / str(entry.get("reference") or "")
        if not reference.exists() or reference.stat().st_size < 5_000:
            raise PublishAuditError(f"Locked character reference is missing: {reference.name}")
        _image_health(reference)

    return {
        "episode_manifest": str(episode_root / "episode.json"),
        "image_qc": str(qc_path),
        "scene_count": len(image_paths),
        "unique_frame_count": len(set(hashes)),
        "character_registry": str(registry_path),
    }


def _check_compilation_assets(package_dir: Path, meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = package_dir / "compilation_manifest.json"
    if not manifest_path.exists():
        raise PublishAuditError("Compilation manifest is missing")
    manifest = _read_json(manifest_path)
    episodes = manifest.get("episodes") or []
    if len(episodes) != 5 or int(manifest.get("episode_count") or 0) != 5:
        raise PublishAuditError("Compilation manifest must contain exactly five episodes")
    numbers = [int(item.get("episode") or 0) for item in episodes]
    if numbers != list(range(numbers[0], numbers[0] + 5)):
        raise PublishAuditError("Compilation episodes must be consecutive and ordered")
    hashes: list[str] = []
    for item in episodes:
        source_video = _resolve(item.get("video_path"), ROOT)
        source_audit = _resolve(item.get("audit_path"), source_video.parent)
        if not source_video.exists() or not source_audit.exists():
            raise PublishAuditError(f"Episode {item.get('episode')} source or audit is missing")
        audit = _read_json(source_audit)
        if audit.get("status") != "passed" or not audit.get("fail_closed"):
            raise PublishAuditError(f"Episode {item.get('episode')} lacks a passing strict audit")
        expected_hash = ((audit.get("inputs") or {}).get("video") or {}).get("sha256")
        actual_hash = _sha256(source_video)
        if not expected_hash or expected_hash != actual_hash:
            raise PublishAuditError(f"Episode {item.get('episode')} changed after its strict audit")
        hashes.append(actual_hash)
    if len(set(hashes)) != 5:
        raise PublishAuditError("Compilation contains duplicate episode videos")
    if int(meta.get("episode_count") or 0) != 5:
        raise PublishAuditError("Compilation metadata must declare five episodes")
    return manifest, {
        "compilation_manifest": str(manifest_path),
        "episodes": numbers,
        "unique_source_videos": len(set(hashes)),
    }


def _check_rights(package_dir: Path, story_evidence: dict[str, Any]) -> dict[str, Any]:
    path = package_dir / "rights_manifest.json"
    if not path.exists():
        raise PublishAuditError("Asset rights and provenance manifest is missing")
    rights = _read_json(path)
    if rights.get("rights_status") != "cleared" or rights.get("unresolved_assets"):
        raise PublishAuditError("Asset rights are unresolved")
    if rights.get("named_studio_imitation_requested"):
        raise PublishAuditError("Named-studio imitation request detected")
    story = rights.get("story") or {}
    visuals = rights.get("visuals") or {}
    audio = rights.get("music_and_sfx") or {}
    if story.get("third_party_adaptation"):
        raise PublishAuditError("Third-party story adaptation is not cleared")
    if visuals.get("stock_media_used") or audio.get("stock_track_used"):
        raise PublishAuditError("Uncleared stock media is not allowed")
    for item in visuals.get("frame_hashes") or []:
        frame = Path(str(item.get("path") or ""))
        if not frame.exists() or _sha256(frame) != item.get("sha256"):
            raise PublishAuditError("A story frame changed after provenance was recorded")
    return {
        "manifest": str(path),
        "rights_status": rights.get("rights_status"),
        "original_story": not story.get("third_party_adaptation"),
        "stock_media_used": bool(visuals.get("stock_media_used") or audio.get("stock_track_used")),
        "recorded_frames": len(visuals.get("frame_hashes") or []),
    }


def _check_metadata(meta: dict[str, Any], script: dict[str, Any]) -> dict[str, Any]:
    title = str(meta.get("title") or "").strip()
    description = str(meta.get("description") or "").strip()
    tags = [str(value).strip() for value in (meta.get("tags") or []) if str(value).strip()]
    failures: list[str] = []
    failures.extend(
        f"title policy: {failure}"
        for failure in validate_episode_title(title)
    )
    if not 12 <= len(title) <= 100:
        failures.append("title length must be 12-100 characters")
    if len(description) < 120:
        failures.append("description is too thin")
    if not 5 <= len(set(tags)) <= 30:
        failures.append("use 5-30 unique relevant tags")
    if sum(len(tag) + 1 for tag in set(tags)) > 480:
        failures.append("tag payload is too large")
    if PLACEHOLDER_RE.search(f"{title}\n{description}"):
        failures.append("placeholder wording detected")
    series_title = str(script.get("title") or "")
    series_id = str(script.get("series_id") or "")
    episode_id = str(script.get("episode_id") or "")
    if title != series_title:
        failures.append("metadata title does not match the rendered script title")
    if series_id and series_id not in str(script.get("series_id")):
        failures.append("series identity mismatch")
    if episode_id and not episode_id.startswith(series_id):
        failures.append("episode identity does not belong to the series")
    if "KAAPAV ARC Studios" not in description:
        failures.append("channel attribution is missing")
    scenes = script.get("scenes") or []
    opening = " ".join(
        str(scene.get("text") or scene.get("caption") or "")
        for scene in scenes[:2] if isinstance(scene, dict)
    )
    promise = title_opening_overlap(title, opening)
    if not promise["passed"]:
        failures.append("opening does not immediately pay off a concrete title term")
    if failures:
        raise PublishAuditError("Metadata gate failed: " + "; ".join(failures))
    return {
        "title": title,
        "description_characters": len(description),
        "unique_tags": len(set(tags)),
        "series_id": series_id,
        "episode_id": episode_id,
        "opening_promise": promise,
    }


def _check_compilation_metadata(meta: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    title = str(meta.get("title") or "").strip()
    description = str(meta.get("description") or "").strip()
    tags = [str(value).strip() for value in (meta.get("tags") or []) if str(value).strip()]
    numbers = [int(item.get("episode") or 0) for item in (manifest.get("episodes") or [])]
    failures: list[str] = []
    if not 12 <= len(title) <= 100:
        failures.append("title length must be 12-100 characters")
    if len(description) < 200:
        failures.append("compilation description is too thin")
    if not 5 <= len(set(tags)) <= 30:
        failures.append("use 5-30 unique relevant tags")
    if PLACEHOLDER_RE.search(f"{title}\n{description}"):
        failures.append("placeholder wording detected")
    if "KAAPAV ARC Studios" not in description:
        failures.append("channel attribution is missing")
    if numbers and not all(str(number) in description for number in (numbers[0], numbers[-1])):
        failures.append("description does not identify the episode block")
    variants_path = Path(str(meta.get("thumbnail_path") or "")).parent / "packaging_variants.json"
    variants = _read_json(variants_path) if variants_path.exists() else {}
    titles = [str(item.get("title") or "") for item in variants.get("candidates", [])]
    if len(titles) != 3 or len(set(titles)) != 3 or any(not 12 <= len(value) <= 100 for value in titles):
        failures.append("three distinct valid long-form packaging candidates are required")
    if failures:
        raise PublishAuditError("Compilation metadata gate failed: " + "; ".join(failures))
    return {
        "title": title,
        "description_characters": len(description),
        "unique_tags": len(set(tags)),
        "series_id": manifest.get("series_id"),
        "episode_range": numbers,
        "packaging_variants": str(variants_path),
    }


def _check_schedule(cfg, publish_at: str | None, release_kind: str) -> dict[str, Any]:
    if not publish_at:
        return {"mode": "private_review", "publish_at": None}
    try:
        parsed = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublishAuditError(f"Invalid publish_at value: {publish_at}") from exc
    if parsed.tzinfo is None:
        raise PublishAuditError("publish_at must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    lead_minutes = int(cfg.get("autopilot", "minimum_publish_lead_minutes", default=60))
    if parsed < _now_utc() + timedelta(minutes=lead_minutes):
        raise PublishAuditError(f"Schedule needs at least {lead_minutes} minutes of lead time")
    local = parsed.astimezone(IST)
    if release_kind == "compilation":
        if local.weekday() not in {5, 6} or (local.hour, local.minute) != (10, 0):
            raise PublishAuditError("Compilations must publish on a weekend at 10:00 IST")
    elif (local.hour, local.minute) != (10, 0):
        raise PublishAuditError("Short episodes must publish at 10:00 IST")
    return {
        "mode": "scheduled_private",
        "publish_at": parsed.isoformat().replace("+00:00", "Z"),
        "local_slot": local.isoformat(),
        "release_kind": release_kind,
    }


def _scan_package_for_secrets(package_dir: Path) -> None:
    for path in package_dir.rglob("*"):
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if lowered in SECRET_NAMES or any(pattern in lowered for pattern in SECRET_PATTERNS):
            raise PublishAuditError(f"Credential-like file found in release package: {path.name}")


def run_publish_audit(
    cfg,
    video_path: Path,
    meta: dict[str, Any],
    *,
    publish_at: str | None = None,
    online_channel: dict[str, Any] | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    """Audit exact upload bytes and return a signed-by-hash local evidence report."""
    video_path = Path(video_path).resolve()
    package_dir = video_path.parent
    script_path = package_dir / "script.json"
    thumbnail_path = _resolve(meta.get("thumbnail_path") or package_dir / "thumbnail.jpg", package_dir)
    failures: list[str] = []
    evidence: dict[str, Any] = {}
    try:
        if not video_path.exists() or video_path.stat().st_size < 500_000:
            raise PublishAuditError("Final video is missing or implausibly small")
        if not thumbnail_path.exists() or thumbnail_path.stat().st_size < 20_000:
            raise PublishAuditError("Custom thumbnail is missing or implausibly small")
        _scan_package_for_secrets(package_dir)
        release_kind = str(meta.get("release_kind") or "short")
        if release_kind == "compilation":
            manifest, story_evidence = _check_compilation_assets(package_dir, meta)
            evidence["metadata"] = _check_compilation_metadata(meta, manifest)
            evidence["story"] = story_evidence
        else:
            if not script_path.exists():
                raise PublishAuditError("Rendered script.json is missing")
            script = _read_json(script_path)
            evidence["metadata"] = _check_metadata(meta, script)
            evidence["story"] = _check_story_assets(script)
        evidence["rights"] = _check_rights(package_dir, evidence["story"])
        evidence["thumbnail"] = _image_health(thumbnail_path, thumbnail=True)

        probe = _probe(video_path)
        streams = probe.get("streams") or []
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if not video_stream or not audio_stream:
            raise PublishAuditError("Video and audio streams are both mandatory")
        duration = float((probe.get("format") or {}).get("duration") or 0)
        width, height = int(video_stream.get("width") or 0), int(video_stream.get("height") or 0)
        if release_kind == "short":
            if not 20 <= duration <= 60:
                raise PublishAuditError(f"Short duration {duration:.2f}s is outside 20-60s")
            if height <= width:
                raise PublishAuditError("Short must be vertical")
        else:
            if duration < 120:
                raise PublishAuditError("Compilation is implausibly short")
            if width <= height:
                raise PublishAuditError("Compilation must be horizontal")
            if int(meta.get("episode_count") or 0) != 5:
                raise PublishAuditError("Future compilations must contain exactly five episodes")
        _full_decode(video_path)
        evidence["media"] = {
            "duration_seconds": round(duration, 3), "width": width, "height": height,
            "video_codec": video_stream.get("codec_name"),
            "audio_codec": audio_stream.get("codec_name"), "full_decode": "passed",
        }
        qc_path = package_dir / "qc_report.json"
        if not qc_path.exists():
            raise PublishAuditError("Technical QC report is missing")
        technical_qc = _read_json(qc_path)
        contact_path = _resolve(technical_qc.get("contact_sheet"), package_dir)
        if not technical_qc.get("ok") or technical_qc.get("full_decode") != "passed":
            raise PublishAuditError("Technical QC report is not a clean pass")
        if not contact_path.exists() or contact_path.stat().st_size < 20_000:
            raise PublishAuditError("QC contact sheet is missing")
        evidence["contact_sheet"] = _image_health(contact_path)
        evidence["schedule"] = _check_schedule(cfg, publish_at, release_kind)
        expected_channel = str(cfg.get("youtube", "expected_channel_id", default="") or "")
        if online_channel:
            if online_channel.get("id") != expected_channel:
                raise PublishAuditError("Authenticated YouTube channel does not match the locked channel")
            evidence["channel"] = {
                "id": online_channel.get("id"), "title": online_channel.get("title")
            }
        else:
            evidence["channel"] = {"id": expected_channel, "online_verified": False}
    except PublishAuditError as exc:
        failures.append(str(exc))

    inputs = {}
    for label, path in (("video", video_path), ("thumbnail", thumbnail_path), ("script", script_path)):
        if path.exists() and path.is_file():
            inputs[label] = {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
    inputs["metadata"] = {"sha256": _metadata_sha256(meta)}
    report = {
        "schema_version": AUDIT_SCHEMA,
        "audit_id": f"audit-{_now_utc().strftime('%Y%m%dT%H%M%SZ')}-{inputs.get('video', {}).get('sha256', '')[:12]}",
        "created_at": _now_utc().isoformat().replace("+00:00", "Z"),
        "status": "passed" if not failures else "blocked",
        "fail_closed": True,
        "inputs": inputs,
        "evidence": evidence,
        "failures": failures,
    }
    if write_report:
        report_path = package_dir / AUDIT_NAME
        temp = report_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(report_path)
    if failures:
        raise PublishAuditError("Strict publish audit blocked: " + "; ".join(failures))
    return report


def assert_fresh_audit(cfg, video_path: Path, meta: dict[str, Any], report: dict[str, Any]) -> None:
    """Refuse stale reports or any file mutated after the audit."""
    if report.get("status") != "passed" or not report.get("fail_closed"):
        raise PublishAuditError("No passing fail-closed audit supplied")
    created = datetime.fromisoformat(str(report.get("created_at")).replace("Z", "+00:00"))
    max_age = int(cfg.get("autopilot", "audit_max_age_minutes", default=30))
    if _now_utc() - created.astimezone(timezone.utc) > timedelta(minutes=max_age):
        raise PublishAuditError(f"Publish audit is older than {max_age} minutes")
    inputs = report.get("inputs") or {}
    expected_video = (inputs.get("video") or {}).get("sha256")
    if not expected_video or _sha256(Path(video_path)) != expected_video:
        raise PublishAuditError("Video changed after its publish audit")
    thumbnail = _resolve(meta.get("thumbnail_path") or Path(video_path).parent / "thumbnail.jpg", Path(video_path).parent)
    expected_thumbnail = (inputs.get("thumbnail") or {}).get("sha256")
    if not expected_thumbnail or _sha256(thumbnail) != expected_thumbnail:
        raise PublishAuditError("Thumbnail changed after its publish audit")
    script = Path(video_path).parent / "script.json"
    expected_script = (inputs.get("script") or {}).get("sha256")
    if expected_script and (not script.exists() or _sha256(script) != expected_script):
        raise PublishAuditError("Rendered script changed after its publish audit")
    expected_metadata = (inputs.get("metadata") or {}).get("sha256")
    if not expected_metadata or _metadata_sha256(meta) != expected_metadata:
        raise PublishAuditError("Upload metadata changed after its publish audit")


def assert_persisted_release_evidence(
    video_path: Path,
    meta: dict[str, Any],
    audit_path: Path,
    *,
    expected_audit_id: str | None = None,
) -> dict[str, Any]:
    """Revalidate an older passing audit immediately before a timed release.

    A platform scheduler can publish days after the upload audit was created, so
    the ordinary freshness window is not applied. Every immutable input is
    re-hashed instead, preserving the quality boundary at the release moment.
    """
    report = _read_json(Path(audit_path))
    if report.get("status") != "passed" or report.get("fail_closed") is not True:
        raise PublishAuditError("Persisted release evidence is not a passing fail-closed audit")
    if expected_audit_id and report.get("audit_id") != expected_audit_id:
        raise PublishAuditError("Persisted release audit ID does not match the queued release")
    inputs = report.get("inputs") or {}
    video = Path(video_path)
    if not video.is_file() or _sha256(video) != (inputs.get("video") or {}).get("sha256"):
        raise PublishAuditError("Video changed after strict QC")
    thumbnail = _resolve((inputs.get("thumbnail") or {}).get("path"), video.parent)
    if not thumbnail.is_file() or _sha256(thumbnail) != (inputs.get("thumbnail") or {}).get("sha256"):
        raise PublishAuditError("Thumbnail changed after strict QC")
    script = _resolve((inputs.get("script") or {}).get("path"), video.parent)
    if not script.is_file() or _sha256(script) != (inputs.get("script") or {}).get("sha256"):
        raise PublishAuditError("Rendered script changed after strict QC")
    if _metadata_sha256(meta) != (inputs.get("metadata") or {}).get("sha256"):
        raise PublishAuditError("Release metadata changed after strict QC")
    if report.get("failures"):
        raise PublishAuditError("Persisted release evidence contains failures")
    return report


def assert_persisted_release_evidence(
    video_path: Path,
    meta: dict[str, Any],
    audit_path: Path,
    *,
    expected_audit_id: str | None = None,
) -> dict[str, Any]:
    """Revalidate an older passing audit immediately before a timed release.

    A platform scheduler can publish days after the upload audit was created, so
    the ordinary freshness window is not applied. Every immutable input is
    re-hashed instead, preserving the quality boundary at the release moment.
    """
    report = _read_json(Path(audit_path))
    if report.get("status") != "passed" or report.get("fail_closed") is not True:
        raise PublishAuditError("Persisted release evidence is not a passing fail-closed audit")
    if expected_audit_id and report.get("audit_id") != expected_audit_id:
        raise PublishAuditError("Persisted release audit ID does not match the queued release")
    inputs = report.get("inputs") or {}
    video = Path(video_path)
    if not video.is_file() or _sha256(video) != (inputs.get("video") or {}).get("sha256"):
        raise PublishAuditError("Video changed after strict QC")
    thumbnail = _resolve((inputs.get("thumbnail") or {}).get("path"), video.parent)
    if not thumbnail.is_file() or _sha256(thumbnail) != (inputs.get("thumbnail") or {}).get("sha256"):
        raise PublishAuditError("Thumbnail changed after strict QC")
    script = _resolve((inputs.get("script") or {}).get("path"), video.parent)
    if not script.is_file() or _sha256(script) != (inputs.get("script") or {}).get("sha256"):
        raise PublishAuditError("Rendered script changed after strict QC")
    if _metadata_sha256(meta) != (inputs.get("metadata") or {}).get("sha256"):
        raise PublishAuditError("Release metadata changed after strict QC")
    if report.get("failures"):
        raise PublishAuditError("Persisted release evidence contains failures")
    return report
