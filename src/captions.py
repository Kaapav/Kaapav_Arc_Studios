"""Render caption images with Pillow (no ImageMagick needed).

We draw text into a transparent PNG with a semi-transparent rounded band and a
thick outline so it stays readable over any footage. moviepy overlays these as
ImageClips, timed to the narration.
"""
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Bundled DejaVu ships with Pillow/matplotlib on most systems; we locate a
# unicode-capable TTF at runtime. For Devanagari (Hindi) install a Noto font and
# point FONT_CANDIDATES at it (see README).
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def short_caption(text: str, max_words: int = 6) -> str:
    """Convert a narration sentence into a compact visual beat label."""
    words = (text or "").strip().split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(".,!?;:") + "…"


def _load_font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_caption(text: str, width: int, height: int, font_size: int,
                   out_path: Path, style: str = "cinematic",
                   vertical_position: float = 0.78) -> Path:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)

    # wrap to ~90% width
    max_chars = max(10, int(width * 0.9 / (font_size * 0.55)))
    lines = textwrap.wrap(text.strip(), width=max_chars) or [""]

    line_h = int(font_size * 1.25)
    block_h = line_h * len(lines)
    # Keep subtitles below the story action but above Shorts interface controls.
    vertical_position = max(0.68, min(0.84, float(vertical_position)))
    y0 = int(height * vertical_position) - block_h // 2

    measurements = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        measurements.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

    if style != "legacy":
        pad_x = max(12, int(font_size * 0.45))
        pad_y = max(8, int(font_size * 0.28))
        max_w = max((item[0] for item in measurements), default=0)
        band_left = max(8, (width - max_w) // 2 - pad_x)
        band_right = min(width - 8, (width + max_w) // 2 + pad_x)
        band_top = max(8, y0 - pad_y)
        band_bottom = min(height - 8, y0 + block_h + pad_y)
        draw.rounded_rectangle(
            (band_left, band_top, band_right, band_bottom),
            radius=max(12, int(font_size * 0.35)),
            fill=(0, 0, 0, 155),
        )

    for i, line in enumerate(lines):
        tw = measurements[i][0]
        x = (width - tw) // 2
        y = y0 + i * line_h
        # outline
        outline = (-2, 0, 2) if style != "legacy" else (-3, -2, 0, 2, 3)
        for dx in outline:
            for dy in outline:
                draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        fill = (255, 255, 255, 255) if style != "legacy" else (255, 221, 51, 255)
        draw.text((x, y), line, font=font, fill=fill)

    img.save(out_path)
    return out_path


def timed_subtitle_chunks(text: str, duration: float, max_words: int = 5):
    """Return complete, short subtitle chunks timed across one scene.

    Every narration token is retained. Timing is proportional to word count so
    it remains correct for Piper's proportional timings and other offline voices.
    """
    words = (text or "").strip().split()
    if not words:
        return []
    max_words = max(2, min(7, int(max_words)))
    chunks = [words[index:index + max_words] for index in range(0, len(words), max_words)]
    total_words = len(words)
    result = []
    elapsed = 0.0
    for index, chunk in enumerate(chunks):
        start = duration * elapsed / total_words
        elapsed += len(chunk)
        end = duration if index == len(chunks) - 1 else duration * elapsed / total_words
        result.append((" ".join(chunk), start, max(start + 0.35, end)))
    return result


def build_scene_timing(scenes, word_timings, total_duration):
    """Return [(start, end)] per scene.

    If we have edge-tts word timings, allocate time by matching cumulative word
    counts. Otherwise split proportionally to word count.
    """
    counts = [max(1, len(s["text"].split())) for s in scenes]
    total_words = sum(counts)

    if word_timings and len(word_timings) >= total_words * 0.5:
        # cumulative word index -> time from real timings
        boundaries = [0.0]
        idx = 0
        for c in counts:
            idx = min(len(word_timings) - 1, idx + c)
            boundaries.append(word_timings[idx][2])  # end time of that word
        boundaries[-1] = total_duration
        return [(boundaries[i], boundaries[i + 1]) for i in range(len(scenes))]

    # proportional fallback
    spans, t = [], 0.0
    for c in counts:
        d = total_duration * c / total_words
        spans.append((t, t + d))
        t += d
    spans[-1] = (spans[-1][0], total_duration)
    return spans
