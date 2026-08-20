"""Fetch a background visual for each scene.

Primary: Pexels (free API key) — real stock photos/videos matching scene keywords.
Fallback: a generated gradient background so the pipeline never hard-fails.
Everything is cached in .cache/ so re-runs are fast and quota-friendly.
"""
import hashlib
import json
import random
from pathlib import Path
import requests
from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parent.parent

_PALETTES = [
    ((13, 27, 62), (83, 52, 131)),
    ((28, 12, 44), (110, 30, 80)),
    ((7, 42, 62), (18, 120, 120)),
    ((40, 12, 12), (140, 60, 20)),
    ((10, 10, 30), (40, 40, 90)),
]


def _cache_key(keywords: str, kind: str) -> str:
    return hashlib.md5(f"{kind}:{keywords}".encode()).hexdigest()[:16]


def _gradient(width, height, seed_text, out_path):
    random.seed(seed_text)
    top, bottom = random.choice(_PALETTES)
    top = np.array(top, dtype=float)
    bottom = np.array(bottom, dtype=float)
    ramp = np.linspace(0, 1, height)[:, None]
    grad = (top[None, :] * (1 - ramp) + bottom[None, :] * ramp)  # (H,3)
    img = np.repeat(grad[:, None, :], width, axis=1).astype("uint8")
    Image.fromarray(img).save(out_path)
    return out_path


def get_scene_image(cfg, keywords: str, width: int, height: int,
                    image_path: str | None = None) -> Path:
    """Return a scene image, preferring an explicitly supplied story asset."""
    if image_path:
        source = Path(image_path)
        if not source.is_absolute():
            source = ROOT / source
        if source.exists():
            identity = f"{source.resolve()}:{source.stat().st_mtime_ns}:{width}x{height}"
            out = cfg.cache_dir() / f"custom_{_cache_key(identity, 'custom')}.jpg"
            if not out.exists():
                _fit_cover(source, width, height, destination=out)
            return out

    cache = cfg.cache_dir()
    out = cache / f"img_{_cache_key(f'{keywords}:{width}x{height}', 'pexels')}.jpg"
    if out.exists():
        return out

    if cfg.pexels_key:
        try:
            orient = "portrait" if height > width else "landscape"
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": cfg.pexels_key},
                params={"query": keywords, "per_page": 5, "orientation": orient},
                timeout=30,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if photos:
                pick = random.choice(photos)
                src = pick["src"].get("large2x") or pick["src"]["large"]
                raw = out.with_name(out.stem + ".download" + out.suffix)
                _download(src, raw, timeout=60)
                _fit_cover(raw, width, height, destination=out)
                raw.unlink(missing_ok=True)
                _write_attribution(out, {
                    "provider": "Pexels",
                    "creator": pick.get("photographer"),
                    "source_url": pick.get("url"),
                })
                return out
        except Exception as e:
            print(f"  [media] Pexels failed for '{keywords}': {e}. Using gradient.")

    return _gradient(width, height, keywords, out)


def get_scene_video(cfg, keywords: str, width: int, height: int,
                    duration: float = 5.0) -> Path | None:
    """Fetch one short Pexels video for a scene when the free API provides one.

    Video is deliberately best-effort: a missing result, quota error, or bad
    download returns None and the renderer falls back to a still image. Files
    are cached so rerenders do not repeatedly spend API quota.
    """
    if not cfg.pexels_key:
        return None

    cache = cfg.cache_dir()
    out = cache / f"vid_{_cache_key(f'{keywords}:{width}x{height}', 'pexels-video')}.mp4"
    if out.exists() and out.stat().st_size > 10000:
        return out

    try:
        orient = "portrait" if height > width else "landscape"
        r = requests.get(
            "https://api.pexels.com/v1/videos/search",
            headers={"Authorization": cfg.pexels_key},
            params={"query": keywords, "per_page": 8, "orientation": orient},
            timeout=30,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        if not videos:
            return None

        # Prefer a reasonably large file, but keep CPU rendering practical.
        candidates = []
        for item in videos:
            for vf in item.get("video_files", []):
                link = vf.get("link")
                w, h = int(vf.get("width") or 0), int(vf.get("height") or 0)
                if link and w >= 480 and h >= 480:
                    candidates.append((w * h, link, item))
        if not candidates:
            return None
        _, link, source_item = sorted(candidates, key=lambda item: item[0])[0]
        _download(link, out, timeout=90)
        if out.stat().st_size < 10000:
            out.unlink(missing_ok=True)
            return None
        user = source_item.get("user", {})
        _write_attribution(out, {
            "provider": "Pexels",
            "creator": user.get("name"),
            "source_url": source_item.get("url"),
        })
        return out
    except Exception as e:
        print(f"  [media] Pexels video failed for '{keywords}': {e}. Using still.")
        return None


def _download(url: str, destination: Path, timeout: int):
    """Stream to a temporary file and publish atomically after success."""
    destination = Path(destination)
    temp = destination.with_name(destination.name + ".part")
    temp.unlink(missing_ok=True)
    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(temp, "wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


def _write_attribution(media_path: Path, data: dict):
    sidecar = media_path.with_suffix(media_path.suffix + ".source.json")
    temp = sidecar.with_name(sidecar.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(sidecar)


def _fit_cover(path: Path, width: int, height: int, destination: Path | None = None):
    """Center-crop + resize so the image fully covers the frame."""
    img = Image.open(path).convert("RGB")
    src_ratio = img.width / img.height
    dst_ratio = width / height
    if src_ratio > dst_ratio:
        new_w = int(img.height * dst_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / dst_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    img = img.resize((width, height), Image.LANCZOS)
    out = Path(destination or path)
    temp = out.with_name(out.stem + ".part" + out.suffix)
    img.save(temp, quality=90)
    temp.replace(out)
