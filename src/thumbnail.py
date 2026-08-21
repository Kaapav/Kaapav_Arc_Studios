"""Generate a bold thumbnail for Shorts (1080x1920 vertical)."""
from pathlib import Path
import re
import textwrap
from PIL import Image, ImageDraw, ImageFont
from . import media
from .captions import _load_font

# Arc-specific color schemes: (text_color, shadow_color, glow_color)
_ARC_COLORS = {
    "the_missing_hour": ((255, 221, 51), (0, 0, 0), (255, 180, 0)),
    "the_architects_lie": ((110, 220, 255), (0, 0, 0), (0, 180, 255)),
    "default": ((255, 221, 51), (0, 0, 0), (255, 180, 0)),
}


def _arc_color(arc: str | None) -> tuple:
    if not arc:
        return _ARC_COLORS["default"]
    key = arc.lower().strip().replace(" ", "_")
    return _ARC_COLORS.get(key, _ARC_COLORS["default"])


def build_thumbnail(cfg, title: str, keywords: str, out_path: Path,
                    image_path: str | None = None, series_label: str | None = None,
                    arc: str | None = None) -> Path:
    W, H = 1080, 1920
    bg = media.get_scene_image(cfg, keywords, W, H, image_path=image_path)
    img = Image.open(bg).convert("RGB").resize((W, H))

    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.blend(img, overlay, 0.35)

    draw = ImageDraw.Draw(img)
    font = _load_font(88)
    channel = cfg.get("channel", "name", default="")
    text_color, shadow_color, _ = _arc_color(arc)

    words = "".join(ch for ch in title.replace("|", " ").strip() if ord(ch) <= 0xFFFF)
    words = re.sub(r"\s+", " ", words).strip()
    lines = textwrap.wrap(words, width=16)[:3]
    y = H // 2 - (len(lines) * 100) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        for dx in (-3, 0, 3):
            for dy in (-3, 0, 3):
                draw.text((x + dx, y + dy), line, font=font, fill=shadow_color)
        draw.text((x, y), line, font=font, fill=text_color)
        y += 100

    badge_font = _load_font(40)
    draw.text((30, 30), channel, font=badge_font, fill=(255, 255, 255))
    if series_label:
        label_font = _load_font(30)
        bbox = draw.textbbox((0, 0), series_label, font=label_font)
        label_w = bbox[2] - bbox[0]
        draw.rounded_rectangle(
            (30, H - 82, 58 + label_w, H - 24), radius=14, fill=(0, 0, 0, 190)
        )
        draw.text((44, H - 72), series_label, font=label_font, fill=(110, 220, 255))

    out_path = Path(out_path)
    img.save(out_path, quality=92)
    return out_path
