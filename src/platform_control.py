"""Persistent, fail-closed controls for each release platform."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


STATE_PATH = ROOT / "analytics" / "platform_controls.json"
PLATFORMS = ("youtube", "facebook", "instagram")
DEFAULTS = {
    "youtube": {"enabled": True, "reason": "existing_verified_channel"},
    "facebook": {"enabled": False, "reason": "awaiting_meta_connection_test"},
    "instagram": {"enabled": False, "reason": "awaiting_meta_connection_test"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load() -> dict[str, Any]:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("platform control state is not an object")
    except (OSError, ValueError, json.JSONDecodeError):
        state = {"schema_version": 1, "platforms": {}}
    platforms = state.setdefault("platforms", {})
    for name, defaults in DEFAULTS.items():
        current = platforms.setdefault(name, {})
        for key, value in defaults.items():
            current.setdefault(key, value)
    state.setdefault("schema_version", 1)
    return state


def enabled(platform: str) -> bool:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    return bool((load().get("platforms") or {}).get(platform, {}).get("enabled"))


def set_enabled(platform: str, value: bool, *, source: str, reason: str | None = None) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    state = load()
    item = state["platforms"].setdefault(platform, {})
    item.update({
        "enabled": bool(value),
        "reason": reason or ("owner_enabled" if value else "owner_disabled"),
        "updated_at": _now(),
        "updated_by": source,
    })
    state["updated_at"] = _now()
    _atomic_write(STATE_PATH, state)
    return item


def summary() -> dict[str, dict[str, Any]]:
    state = load()
    return {name: dict((state.get("platforms") or {}).get(name) or {}) for name in PLATFORMS}
