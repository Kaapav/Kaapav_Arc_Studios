"""Generate a bold thumbnail (useful for 'long' format; Shorts use a frame)."""
from pathlib import Path
import re
import textwrap
from PIL import Image, ImageDraw, ImageFont
from . import media
from .captions import _load_font


def build_thumbnail(cfg, title: str, keywords: str, out_path: Path,
                    image_path: str | None = None, series_label: str | None = None) -> Path:
    W, H = 1280, 720
    bg = media.get_scene_image(cfg, keywords, W, H, image_path=image_path)
    img = Image.open(bg).convert("RGB").resize((W, H))

    # darken for text contrast
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.blend(img, overlay, 0.35)

    draw = ImageDraw.Draw(img)
    font = _load_font(96)
    channel = cfg.get("channel", "name", default="")

    
    # The default Windows font cannot render emoji reliably; remove non-BMP
    # symbols so thumbnails never contain empty boxes.
    words = "".join(ch for ch in title.replace("|", " ").strip() if ord(ch) <= 0xFFFF)
    words = re.sub(r"\s+", " ", words).strip()
    lines = textwrap.wrap(words, width=18)[:3]
    y = H // 2 - (len(lines) * 110) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        for dx in (-4, 0, 4):
            for dy in (-4, 0, 4):
                draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 221, 51))
        y += 110

    # channel badge
    badge_font = _load_font(44)
    draw.text((30, 30), channel, font=badge_font, fill=(255, 255, 255))
    if series_label:
        label_font = _load_font(34)
        bbox = draw.textbbox((0, 0), series_label, font=label_font)
        label_w = bbox[2] - bbox[0]
        draw.rounded_rectangle(
            (30, H - 82, 58 + label_w, H - 24), radius=14, fill=(0, 0, 0, 190)
        )
        draw.text((44, H - 72), series_label, font=label_font, fill=(110, 220, 255))

    out_path = Path(out_path)
    img.save(out_path, quality=92)
    return out_path
