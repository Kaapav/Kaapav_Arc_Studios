"""Small, credential-safe backups of the studio control plane.

Rendered media and generated images are intentionally excluded: they are large
and reproducible. Story canon, manifests, code, configuration and operating
state are the irreplaceable inputs protected here.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


BACKUP_ROOT = ROOT / "backups" / "control-plane"
STATE_PATH = ROOT / "analytics" / "backup_state.json"
ALLOWED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".ps1", ".cmd", ".txt", ".html"}
EXCLUDED_PARTS = {
    ".git", ".venv", ".cache", "__pycache__", "assets", "output", "logs",
    "credentials", "backups", "archive", "generated_images",
}
SECRET_MARKERS = {
    ".env", "client_secret", "service_account", "credential", "oauth", "token",
    "private_key", "refresh_token",
}
MAX_FILE_BYTES = 5 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    # The snapshot's own state changes after every write. Including it would
    # make the source fingerprint self-referential and force needless rebuilds.
    if relative.as_posix().lower() in {
        "analytics/backup_state.json",
        "analytics/setup_certification.json",
        "setup_certification.md",
    }:
        return False
    lowered_parts = {part.lower() for part in relative.parts}
    lowered_name = path.name.lower()
    return (
        path.is_file()
        and path.suffix.lower() in ALLOWED_SUFFIXES
        and not (lowered_parts & EXCLUDED_PARTS)
        and not any(marker in lowered_name for marker in SECRET_MARKERS)
        and path.stat().st_size <= MAX_FILE_BYTES
    )


def _candidates() -> list[Path]:
    roots = [ROOT, ROOT / "src", ROOT / "tools", ROOT / "content", ROOT / "analytics"]
    found: dict[str, Path] = {}
    for base in roots:
        if not base.exists():
            continue
        iterator = base.iterdir() if base == ROOT else base.rglob("*")
        for path in iterator:
            try:
                if _safe(path):
                    found[path.relative_to(ROOT).as_posix()] = path
            except (OSError, ValueError):
                continue
    return [found[key] for key in sorted(found)]


def _write_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATE_PATH)


def create_daily_snapshot(retention_days: int = 30) -> dict[str, Any]:
    """Create one verified UTC-day snapshot and prune expired local copies."""
    now = _now()
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    target = BACKUP_ROOT / f"kaapav-control-{now:%Y%m%d}.zip"
    existing_state = {}
    try:
        existing_state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    files = _candidates()
    fingerprint = hashlib.sha256()
    for path in files:
        stat = path.stat()
        fingerprint.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        fingerprint.update(f":{stat.st_size}:{stat.st_mtime_ns}\n".encode("ascii"))
    source_fingerprint = fingerprint.hexdigest()
    if (
        target.exists() and existing_state.get("status") == "passed"
        and existing_state.get("source_fingerprint") == source_fingerprint
    ):
        return existing_state

    temporary = target.with_suffix(".zip.tmp")
    manifest = []
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            archive.write(path, relative)
            manifest.append({"path": relative, "size": path.stat().st_size, "sha256": _sha256(path)})
        archive.writestr("BACKUP_MANIFEST.json", json.dumps({
            "schema_version": 1,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "security": "credentials, tokens, keys, media and caches excluded",
            "files": manifest,
        }, indent=2, ensure_ascii=False))
    temporary.replace(target)

    # Verify the central directory and every compressed member before accepting.
    with zipfile.ZipFile(target, "r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"Control-plane backup verification failed at {corrupt}")

    cutoff = now - timedelta(days=max(7, int(retention_days)))
    pruned = 0
    for old in BACKUP_ROOT.glob("kaapav-control-*.zip"):
        if old == target:
            continue
        modified = datetime.fromtimestamp(old.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            old.unlink()
            pruned += 1
    payload = {
        "schema_version": 1,
        "status": "passed",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "path": str(target),
        "sha256": _sha256(target),
        "file_count": len(files),
        "source_fingerprint": source_fingerprint,
        "size_bytes": target.stat().st_size,
        "retention_days": max(7, int(retention_days)),
        "pruned": pruned,
        "off_device_copy": False,
    }
    _write_state(payload)
    return payload
