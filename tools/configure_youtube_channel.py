#!/usr/bin/env python3
"""Apply and verify text branding for the configured YouTube channel."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config
from src.upload import _get_service


def main() -> None:
    cfg = Config("config.story.yaml")
    service = _get_service(cfg)
    channel_id = cfg.get("youtube", "expected_channel_id")
    channel_name = cfg.get("channel", "name")
    description = str(cfg.get("youtube", "channel_description", default="")).strip()
    phrases = cfg.get("youtube", "channel_keywords", default=[]) or []
    keywords = " ".join(f'"{str(phrase).strip()}"' for phrase in phrases if str(phrase).strip())
    if not channel_id or not channel_name or not description or not keywords:
        raise RuntimeError("Channel id, name, description, and keywords must be configured")
    if len(keywords) > 500:
        raise RuntimeError(f"YouTube channel keywords exceed 500 characters: {len(keywords)}")

    response = service.channels().list(
        part="snippet,brandingSettings", id=channel_id
    ).execute()
    items = response.get("items", [])
    if len(items) != 1 or items[0].get("snippet", {}).get("title") != channel_name:
        raise RuntimeError("Authenticated YouTube channel identity changed; refusing update")

    branding = items[0].get("brandingSettings", {})
    channel = branding.setdefault("channel", {})
    channel.update({
        "description": description,
        "keywords": keywords,
        "country": cfg.get("youtube", "country", default="IN"),
        "defaultLanguage": cfg.get("youtube", "default_language", default="en"),
        "showBrowseView": True,
    })
    service.channels().update(
        part="brandingSettings",
        body={"id": channel_id, "brandingSettings": branding},
    ).execute()

    verified = service.channels().list(
        part="snippet,brandingSettings", id=channel_id
    ).execute()["items"][0]
    result = {
        "id": verified["id"],
        "title": verified["snippet"]["title"],
        "handle": verified["snippet"].get("customUrl"),
        "description": verified["snippet"].get("description"),
        "country": verified["snippet"].get("country"),
        "default_language": verified["snippet"].get("defaultLanguage"),
        "keywords": verified.get("brandingSettings", {}).get("channel", {}).get("keywords"),
        "keyword_characters": len(keywords),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
