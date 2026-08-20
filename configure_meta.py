#!/usr/bin/env python3
"""One-time hidden-input Meta token installation and connection verification."""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from src.config import Config, ROOT
from src import meta_platform, platform_control


def _secure_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value.strip() + "\n")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.story.yaml")
    parser.add_argument("--test-only", action="store_true")
    parser.add_argument("--keep-disabled", action="store_true")
    args = parser.parse_args()
    target = meta_platform.token_path()
    if not args.test_only:
        token = getpass.getpass("Paste the Meta System User token (input is hidden): ").strip()
        if len(token) < 40 or any(character.isspace() for character in token):
            raise SystemExit("Token was empty or malformed; nothing was stored.")
        _secure_write(target, token)
        print(f"Token stored securely in excluded credential file: {target}")
    cfg = Config(args.config)
    status = meta_platform.health_check(cfg)
    print(f"Meta connection: {status.get('status')}")
    print(status.get("detail") or "")
    platform_status = status.get("platforms") or {}
    facebook_ready = (platform_status.get("facebook") or {}).get("status") == "ready"
    instagram_ready = (platform_status.get("instagram") or {}).get("status") == "ready"
    page = status.get("page") or {}
    instagram = status.get("instagram") or {}
    print(f"Facebook: {page.get('name')} ({page.get('id')})")
    print(f"Instagram: @{instagram.get('username')} ({instagram.get('id')})")
    if not args.keep_disabled and facebook_ready:
        platform_control.set_enabled("facebook", True, source="configure_meta", reason="verified_meta_connection")
        print("Facebook automation enabled.")
    if not args.keep_disabled and instagram_ready:
        platform_control.set_enabled("instagram", True, source="configure_meta", reason="verified_meta_connection")
        print("Instagram automation enabled.")
    if not facebook_ready:
        return 2
    return 0 if instagram_ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
