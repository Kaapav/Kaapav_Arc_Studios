"""Deterministic long-form packaging candidates for native YouTube testing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_longform_variants(metadata: dict[str, Any]) -> dict[str, Any]:
    series = str(metadata.get("series_title") or metadata.get("series_id") or "KAAPAV ARC").upper()
    start = int(metadata.get("episode_start") or 1)
    end = int(metadata.get("episode_end") or (start + int(metadata.get("episode_count") or 5) - 1))
    candidates = [
        str(metadata.get("title") or "").strip(),
        f"Five Connected Episodes. One Impossible Choice. | {series} {start}–{end}",
        f"The Complete {series} Story | Episodes {start}–{end}",
    ]
    candidates = list(dict.fromkeys(title[:100].rstrip() for title in candidates if title))
    return {
        "schema_version": 1,
        "test_type": "youtube_native_title_only",
        "candidates": [{"id": chr(65 + index), "title": title} for index, title in enumerate(candidates)],
        "default_candidate": "A",
        "selection_metric": "watch_time",
        "automation_boundary": (
            "YouTube exposes native A/B setup only in Studio; candidates are prepared automatically, "
            "while the zero-touch release uses candidate A and never simulates sequential A/B traffic."
        ),
    }


def write_longform_variants(package_dir: Path, metadata: dict[str, Any]) -> Path:
    path = Path(package_dir) / "packaging_variants.json"
    path.write_text(json.dumps(build_longform_variants(metadata), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
