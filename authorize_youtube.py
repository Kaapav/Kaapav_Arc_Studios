#!/usr/bin/env python3
"""Authorize YouTube once without generating or uploading a video."""

import argparse
import datetime as dt
from pathlib import Path

from src.config import Config, ROOT
from src.upload import _get_service


def _move_token(token: Path, label: str) -> Path | None:
    if not token.exists():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = token.with_name(f"{token.stem}.{label}-{stamp}{token.suffix}")
    token.replace(target)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--switch-channel",
        action="store_true",
        help="back up the current token and choose the configured channel again",
    )
    args = parser.parse_args()
    cfg = Config()
    token = ROOT / cfg.yt_token
    if args.switch_channel:
        backup = _move_token(token, "backup")
        if backup:
            print(f"Previous OAuth token backed up to {backup}")
        channel_name = cfg.get("channel", "name", default="the configured channel")
        print("Before approving in the browser:")
        print(f"  1. Select the Google account that owns {channel_name}.")
        print(f"  2. If Google shows YouTube identities, choose {channel_name}.")
    try:
        _get_service(
            cfg,
            allow_interactive=True,
            force_account_selection=args.switch_channel,
        )
    except RuntimeError as exc:
        rejected = _move_token(token, "rejected")
        if rejected:
            print(f"Rejected OAuth token quarantined at {rejected}")
        print(f"Authorization rejected: {exc}")
        print(f"Set {cfg.get('channel', 'name', default='the configured channel')} "
              "as the default YouTube channel, then retry.")
        print("Help: https://support.google.com/youtube/answer/6019090")
        raise SystemExit(2) from None
    print("Correct YouTube channel verified. credentials/token.json is ready.")


if __name__ == "__main__":
    main()
