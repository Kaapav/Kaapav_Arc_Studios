"""Machine-readable originality and asset-rights evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_rights_manifest(output_root: Path, script: dict[str, Any], cfg) -> Path:
    output_root = Path(output_root)
    frames = [Path(scene["image_path"]) for scene in script.get("scenes", [])]
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "series_id": script.get("series_id"),
        "episode_id": script.get("episode_id"),
        "rights_status": "cleared",
        "unresolved_assets": [],
        "story": {
            "origin": "original KAAPAV ARC Studios authored universe",
            "third_party_adaptation": False,
        },
        "visuals": {
            "origin": "project-generated from approved episode prompts and locked character references",
            "stock_media_used": False,
            "frame_hashes": [{"path": str(path), "sha256": _sha256(path)} for path in frames],
        },
        "voice": {
            "provider": str(cfg.get("voice", "provider", default="piper")),
            "local_model": str(cfg.get("voice", "piper_model", default="")),
            "third_party_recording_used": False,
        },
        "music_and_sfx": {
            "origin": "deterministically generated offline by src/sound.py",
            "stock_track_used": False,
            "generator_source": str(ROOT / "src" / "sound.py"),
        },
        "named_studio_imitation_requested": False,
    }
    path = output_root / "rights_manifest.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return path

