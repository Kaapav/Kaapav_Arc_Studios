"""Idempotent upload ledger and duplicate prevention."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


LEDGER_PATH = ROOT / "analytics" / "release_ledger.json"
RECONCILIATION_PATH = ROOT / "analytics" / "release_reconciliation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load() -> dict[str, Any]:
    try:
        value = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"schema_version": 1, "releases": []}
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "releases": []}


def _write(value: dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LEDGER_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(LEDGER_PATH)


def sync_from_outputs() -> dict[str, Any]:
    """Recover ledger entries after a crash between remote upload and ledger write."""
    state = _load()
    known = {entry.get("youtube_id") for entry in state.get("releases", [])}
    for metadata_path in (ROOT / "output" / "story").glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            upload_path = metadata_path.parent / "upload_result.json"
            upload = json.loads(upload_path.read_text(encoding="utf-8")) if upload_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            continue
        youtube_id = metadata.get("youtube_id") or upload.get("id")
        video = metadata_path.parent / "video.mp4"
        if not youtube_id or youtube_id in known or not video.exists():
            continue
        result = {
            "id": youtube_id,
            "url": metadata.get("youtube_url") or upload.get("url"),
            "audit_id": metadata.get("audit_id") or upload.get("audit_id"),
            "privacy": upload.get("privacy", "private"),
            "publish_at": metadata.get("publish_at") or upload.get("publish_at"),
            "thumbnail_set": upload.get("thumbnail_set"),
            "status": metadata.get("status") or upload.get("status"),
        }
        record(video, metadata, result)
        state = _load()
        known.add(youtube_id)
    return _load()


def assert_not_uploaded(video_path: Path, meta: dict[str, Any]) -> None:
    digest = sha256(video_path)
    episode_id = str(meta.get("episode_id") or "")
    for entry in sync_from_outputs().get("releases", []):
        if entry.get("video_sha256") == digest:
            raise RuntimeError(
                f"Duplicate upload blocked: identical video already has YouTube ID {entry.get('youtube_id')}"
            )
        if episode_id and entry.get("episode_id") == episode_id:
            raise RuntimeError(
                f"Duplicate upload blocked: episode {episode_id} already has YouTube ID {entry.get('youtube_id')}"
            )


def record(video_path: Path, meta: dict[str, Any], result: dict[str, Any]) -> None:
    state = _load()
    releases = state.setdefault("releases", [])
    youtube_id = result.get("id")
    releases[:] = [entry for entry in releases if entry.get("youtube_id") != youtube_id]
    releases.append({
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "youtube_id": youtube_id,
        "youtube_url": result.get("url") or (f"https://youtu.be/{youtube_id}" if youtube_id else None),
        "series_id": meta.get("series_id"),
        "episode_id": meta.get("episode_id"),
        "episode": meta.get("episode"),
        "release_kind": meta.get("release_kind", "short"),
        "title": meta.get("title"),
        "video_path": str(Path(video_path).resolve()),
        "video_sha256": sha256(video_path),
        "audit_id": result.get("audit_id"),
        "privacy": result.get("privacy"),
        "publish_at": result.get("publish_at"),
        "thumbnail_set": result.get("thumbnail_set"),
        "status": result.get("status"),
        "made_for_kids": bool(result.get("made_for_kids", meta.get("made_for_kids", False))),
        "remote_contract": result.get("remote_contract") or {},
    })
    state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write(state)


def enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach exact local release identity to remote rows.

    Title parsing is only a legacy fallback. New releases learn against the
    series/episode recorded at the irreversible upload boundary.
    """
    releases = {
        str(entry.get("youtube_id")): entry
        for entry in sync_from_outputs().get("releases", [])
        if entry.get("youtube_id")
    }
    for row in rows:
        entry = releases.get(str(row.get("video_id") or "")) or {}
        for field in ("series_id", "episode_id", "episode", "release_kind"):
            if entry.get(field) is not None:
                row[field] = entry.get(field)
    return rows


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def adopt_legacy_echo(rows: list[dict[str, Any]], cfg) -> dict[str, Any]:
    """Bind owner-confirmed Episodes 1-10 to their authoritative remote IDs.

    These releases predate the strict ledger. Adoption changes release state
    only; it never approves their old assets for a new upload.
    """
    maximum = int(cfg.get("growth", "exclude_owner_test_episodes_through", default=10))
    adopted = []
    known = {
        str(entry.get("youtube_id")): entry
        for entry in _load().get("releases", []) if entry.get("youtube_id")
    }
    for row in rows:
        match = re.search(r"(?i)\bECHO//30\s+Ep\.?\s*(\d{1,2})\b", str(row.get("title") or ""))
        if not match:
            continue
        episode = int(match.group(1))
        if episode < 1 or episode > maximum:
            continue
        manifest_path = ROOT / "content" / "echo100" / "v2" / "cute_style" / f"episode{episode:02d}" / "episode.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        output = ROOT / "output" / "story" / str(manifest.get("output_slug") or "")
        video = output / "video.mp4"
        if not video.exists():
            continue
        privacy = str(row.get("privacy") or "")
        remote_publish = str(row.get("remote_publish_at") or "")
        if privacy == "public":
            release_status = "public"
            publish_at = str(row.get("published_at") or "")
        elif privacy == "private" and remote_publish:
            release_status = "scheduled"
            publish_at = remote_publish
        else:
            continue
        metadata_path = output / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
        metadata.update({
            "series_id": "echo30", "episode_id": manifest.get("episode_id"),
            "episode": episode, "release_kind": "short", "status": release_status,
            "uploaded": True, "youtube_id": row.get("video_id"), "youtube_url": row.get("url"),
            "publish_at": publish_at,
        })
        if release_status == "public":
            metadata["published_at"] = row.get("published_at")
        _atomic_json(metadata_path, metadata)
        entry = known.get(str(row.get("video_id") or "")) or {}
        if entry.get("series_id") != "echo30" or entry.get("episode") != episode:
            record(video, metadata, {
                "id": row.get("video_id"), "url": row.get("url"),
                "privacy": privacy, "publish_at": publish_at,
                "thumbnail_set": entry.get("thumbnail_set"), "audit_id": entry.get("audit_id"),
                "status": release_status, "made_for_kids": bool(row.get("made_for_kids", False)),
            })
            known = {
                str(item.get("youtube_id")): item
                for item in _load().get("releases", []) if item.get("youtube_id")
            }
        adopted.append({"episode": episode, "youtube_id": row.get("video_id"), "status": release_status})
    return {"status": "passed", "adopted": adopted}


def backfill_strict_contracts(cfg) -> int:
    """Upgrade strict releases created before remote-contract persistence."""
    state = _load()
    changed = 0
    from .upload import build_upload_body, _remote_contract
    for entry in state.get("releases", []):
        if not entry.get("audit_id") or entry.get("remote_contract"):
            continue
        video_path = Path(str(entry.get("video_path") or ""))
        metadata_path = video_path.parent / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        body, _, _ = build_upload_body(
            cfg, metadata, privacy_override="private", publish_at=entry.get("publish_at"),
        )
        entry["remote_contract"] = _remote_contract(body)
        entry["made_for_kids"] = bool(cfg.get("youtube", "made_for_kids", default=False))
        changed += 1
    if changed:
        state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write(state)
    return changed


def _promote_local_public(entry: dict[str, Any], row: dict[str, Any]) -> None:
    """Make elapsed remote publication authoritative for local inventory."""
    video_path = Path(str(entry.get("video_path") or ""))
    if not video_path.exists():
        return
    output = video_path.parent
    metadata_path = output / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    metadata.update({
        "status": "public",
        "uploaded": True,
        "youtube_id": entry.get("youtube_id"),
        "youtube_url": entry.get("youtube_url") or row.get("url"),
        "published_at": row.get("published_at"),
    })
    _atomic_json(metadata_path, metadata)
    upload_path = output / "upload_result.json"
    try:
        upload = json.loads(upload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        upload = {}
    upload.update({
        "id": entry.get("youtube_id"), "privacy": "public", "status": "public",
        "published_at": row.get("published_at"),
    })
    _atomic_json(upload_path, upload)


def reconcile_remote(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare local release intent with current remote YouTube state."""
    ledger = sync_from_outputs()
    remote = {str(row.get("video_id")): row for row in rows}
    checks = []
    failures = []
    now = datetime.now(timezone.utc)
    changed = False
    for entry in ledger.get("releases", []):
        youtube_id = str(entry.get("youtube_id") or "")
        row = remote.get(youtube_id)
        if not row:
            failures.append(f"ledger video missing from channel inventory: {youtube_id}")
            checks.append({"youtube_id": youtube_id, "status": "missing_remote"})
            continue
        expected_publish = str(entry.get("publish_at") or "")
        remote_publish = str(row.get("remote_publish_at") or "")
        status = "matched"
        if expected_publish and remote_publish and expected_publish != remote_publish:
            status = "schedule_mismatch"
            failures.append(f"schedule mismatch for {youtube_id}")
        expected_time = None
        if expected_publish:
            try:
                expected_time = datetime.fromisoformat(expected_publish.replace("Z", "+00:00"))
            except ValueError:
                expected_time = None
        if row.get("privacy") == "public":
            if entry.get("status") == "scheduled" and expected_time and expected_time > now:
                status = "premature_public"
                failures.append(f"scheduled video became public unexpectedly: {youtube_id}")
            else:
                status = "published_as_scheduled" if expected_time else "published_remote"
                entry["status"] = "public"
                entry["privacy"] = "public"
                entry["remote_published_at"] = row.get("published_at")
                _promote_local_public(entry, row)
                changed = True
        elif entry.get("status") == "scheduled" and row.get("privacy") == "private" and expected_time:
            if now > expected_time + timedelta(minutes=30):
                status = "overdue_private"
                failures.append(f"scheduled release remained private after grace period: {youtube_id}")

        # Exact remote metadata checks apply only to new, byte-audited releases.
        contract = entry.get("remote_contract") or {}
        if entry.get("audit_id") and contract:
            snippet = contract.get("snippet") or {}
            mismatches = []
            if str(row.get("title") or "") != str(snippet.get("title") or ""):
                mismatches.append("title")
            if str(row.get("_remote_description") or "") != str(snippet.get("description") or ""):
                mismatches.append("description")
            if set(row.get("_remote_tags") or []) != set(snippet.get("tags") or []):
                mismatches.append("tags")
            if str(row.get("_remote_category_id") or "") != str(snippet.get("categoryId") or ""):
                mismatches.append("category")
            if str(row.get("_remote_default_language") or "") != str(snippet.get("defaultLanguage") or ""):
                mismatches.append("language")
            if bool(row.get("made_for_kids")) != bool(entry.get("made_for_kids", False)):
                mismatches.append("made_for_kids")
            if mismatches:
                status = "remote_metadata_mismatch"
                failures.append(f"remote metadata mismatch for {youtube_id}: {','.join(mismatches)}")
        checks.append({
            "youtube_id": youtube_id, "status": status,
            "local_publish_at": expected_publish, "remote_publish_at": remote_publish,
            "remote_privacy": row.get("privacy"), "title": row.get("title"),
        })
    if changed:
        ledger["updated_at"] = now.isoformat().replace("+00:00", "Z")
        _write(ledger)
    payload = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "passed" if not failures else "attention",
        "checks": checks,
        "failures": failures,
    }
    temporary = RECONCILIATION_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(RECONCILIATION_PATH)
    return payload
