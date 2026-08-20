"""Assemble the final video: motion footage + short captions + voiceover + music."""
import bisect
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

# Prefer the maintained system FFmpeg over ImageIO's bundled 4.2.2 binary.
# This must be set before importing MoviePy/ImageIO.
_system_ffmpeg = shutil.which("ffmpeg")
if _system_ffmpeg:
    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", _system_ffmpeg)

# MoviePy 1.0.3 still references the Pillow symbol removed in Pillow 10.
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from moviepy.editor import (
    ImageClip, AudioFileClip, ColorClip, CompositeVideoClip, CompositeAudioClip,
    VideoClip, VideoFileClip, concatenate_videoclips, afx, vfx,
)

from .config import ROOT
from . import media, captions, sound


def _ken_burns(clip, duration, scene_index=0, effect="push_in", zoom=0.11):
    """Scene-directed camera motion for the permanent no-GPU visual floor."""
    source_w, source_h = clip.w, clip.h
    effect = str(effect or "push_in").lower()

    def scale(t):
        progress = min(1.0, max(0.0, t / max(duration, 0.01)))
        if effect == "pull_out":
            return 1.15 - 0.12 * progress
        if effect in {"pan_left", "pan_right"}:
            return 1.12
        if effect == "glitch":
            return 1.08 + 0.012 * abs(__import__("math").sin(progress * 34.0))
        return 1.02 + zoom * progress

    def position(t):
        progress = min(1.0, max(0.0, t / max(duration, 0.01)))
        current = scale(t)
        extra_x = source_w * (current - 1)
        extra_y = source_h * (current - 1)
        if effect == "pan_left":
            return (-extra_x * progress, -extra_y * 0.48)
        if effect == "pan_right":
            return (-extra_x * (1 - progress), -extra_y * 0.52)
        if effect == "glitch":
            import math
            jitter_x = 5.0 * math.sin(progress * 91.0)
            jitter_y = 3.0 * math.sin(progress * 67.0)
            return (-extra_x * 0.5 + jitter_x, -extra_y * 0.5 + jitter_y)
        if effect == "pull_out":
            return (-extra_x * 0.5, -extra_y * (0.40 + 0.12 * progress))
        if scene_index % 2:
            return (-extra_x * progress, -extra_y * 0.5)
        return (-extra_x * 0.5, -extra_y * 0.5)

    return clip.resize(scale).set_position(position)


def _vignette_path(cache: Path, width: int, height: int) -> Path:
    path = cache / f"vignette-{width}x{height}.png"
    if path.exists():
        return path
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    cx, cy = width / 2.0, height / 2.0
    for y in range(height):
        ny = abs((y - cy) / cy)
        for x in range(width):
            nx = abs((x - cx) / cx)
            edge = max(nx ** 1.7, ny ** 2.0)
            alpha = int(max(0, min(125, (edge - 0.42) * 190)))
            pixels[x, y] = (0, 0, 0, alpha)
    image.save(path)
    return path


def _cinematic_layers(cache: Path, width: int, height: int, duration: float, effect: str, scene_index: int):
    layers = [ImageClip(str(_vignette_path(cache, width, height))).set_duration(duration)]
    danger = effect == "glitch" or scene_index >= 4
    colour = (118, 12, 40) if danger else (10, 70, 110)
    opacity = 0.075 if effect == "glitch" else 0.035
    wash = ColorClip((width, height), color=colour).set_duration(duration).set_opacity(opacity)
    wash = wash.fx(vfx.fadein, min(0.35, duration / 3)).fx(vfx.fadeout, min(0.35, duration / 3))
    layers.append(wash)
    return layers


def _motion_clip(path: Path, width: int, height: int, duration: float):
    """Load an optional cloud-generated clip and fit it to the Shorts frame."""
    clip = VideoFileClip(str(path), audio=False)
    scale = max(width / clip.w, height / clip.h)
    clip = clip.resize(scale)
    left = max(0, (clip.w - width) / 2)
    top = max(0, (clip.h - height) / 2)
    clip = clip.crop(x1=left, y1=top, x2=left + width, y2=top + height)
    if clip.duration < duration:
        clip = clip.fx(vfx.loop, duration=duration)
    else:
        clip = clip.subclip(0, duration)
    return clip.set_duration(duration).without_audio()


def _motion_candidates(scene: dict):
    """Yield ordered external motion candidates without making any one mandatory."""
    seen = set()
    legacy = scene.get("video_path")
    raw = ([{"provider": "attached", "path": legacy}] if legacy else []) + list(
        scene.get("video_candidates") or []
    )
    for item in raw:
        if isinstance(item, str):
            item = {"provider": "external", "path": item}
        if not isinstance(item, dict) or not item.get("path"):
            continue
        key = str(item["path"])
        if key in seen:
            continue
        seen.add(key)
        yield str(item.get("provider") or "external"), Path(key)


def _safe_still_frame(
    source: Image.Image,
    vignette: Image.Image,
    caption: Image.Image | None,
    width: int,
    height: int,
    duration: float,
    local_time: float,
    effect: str,
    scene_index: int,
) -> np.ndarray:
    """Compose one uint8 frame without MoviePy's float64 alpha-mask arrays."""
    progress = min(1.0, max(0.0, local_time / max(duration, 0.01)))
    effect = str(effect or "push_in").lower()
    if effect == "none":
        scale = 1.0
    elif effect == "pull_out":
        scale = 1.15 - 0.12 * progress
    elif effect in {"pan_left", "pan_right"}:
        scale = 1.12
    elif effect == "glitch":
        scale = 1.08 + 0.012 * abs(math.sin(progress * 34.0))
    else:
        scale = 1.02 + 0.11 * progress

    resized_width = max(width, int(round(width * scale)))
    resized_height = max(height, int(round(height * scale)))
    resized = source.resize((resized_width, resized_height), Image.Resampling.BICUBIC)
    extra_x = max(0, resized_width - width)
    extra_y = max(0, resized_height - height)
    if effect == "pan_left":
        crop_x = extra_x * progress
        crop_y = extra_y * 0.48
    elif effect == "pan_right":
        crop_x = extra_x * (1.0 - progress)
        crop_y = extra_y * 0.52
    elif effect == "glitch":
        crop_x = extra_x * 0.5 - 5.0 * math.sin(progress * 91.0)
        crop_y = extra_y * 0.5 - 3.0 * math.sin(progress * 67.0)
    elif effect == "pull_out":
        crop_x = extra_x * 0.5
        crop_y = extra_y * (0.40 + 0.12 * progress)
    elif scene_index % 2:
        crop_x = extra_x * progress
        crop_y = extra_y * 0.5
    else:
        crop_x = extra_x * 0.5
        crop_y = extra_y * 0.5
    crop_x = int(round(min(extra_x, max(0.0, crop_x))))
    crop_y = int(round(min(extra_y, max(0.0, crop_y))))
    frame = resized.crop((crop_x, crop_y, crop_x + width, crop_y + height))
    resized.close()

    danger = effect == "glitch" or scene_index >= 4
    colour = (118, 12, 40) if danger else (10, 70, 110)
    base_opacity = 0.075 if effect == "glitch" else 0.035
    fade_duration = min(0.35, duration / 3.0)
    fade = min(
        1.0,
        local_time / max(fade_duration, 0.01),
        max(0.0, duration - local_time) / max(fade_duration, 0.01),
    )
    opacity = max(0.0, min(1.0, base_opacity * fade))
    if opacity:
        wash = Image.new("RGB", (width, height), colour)
        tinted = Image.blend(frame, wash, opacity)
        frame.close()
        wash.close()
        frame = tinted

    composed = frame.convert("RGBA")
    frame.close()
    composed.alpha_composite(vignette)
    if caption is not None:
        composed.alpha_composite(caption)
    rgb = composed.convert("RGB")
    result = np.asarray(rgb, dtype=np.uint8).copy()
    rgb.close()
    composed.close()
    return result


def _build_video_memory_safe(cfg, script: dict, voice_path: Path, word_timings, out_path: Path) -> Path:
    """Render still-image stories with one lazy scene in memory at a time."""
    width = int(cfg.get("video", "width", default=1080))
    height = int(cfg.get("video", "height", default=1920))
    fps = int(cfg.get("video", "fps", default=30))
    font_size = int(cfg.get("video", "caption_font_size", default=70))
    caption_style = cfg.get("video", "caption_style", default="cinematic")
    caption_words = int(cfg.get("video", "caption_words_per_chunk", default=5))
    caption_position = float(cfg.get("video", "caption_vertical_position", default=0.78))
    use_captions = bool(cfg.get("video", "captions", default=True))
    use_kb = bool(cfg.get("video", "ken_burns", default=True))
    encoder_threads = int(cfg.get("video", "encoder_threads", default=2))
    cache = cfg.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)

    voice = AudioFileClip(str(voice_path))
    total = float(voice.duration)
    max_seconds = float(cfg.get("video", "max_seconds", default=0) or 0)
    if max_seconds and total > max_seconds + 0.25:
        voice.close()
        raise RuntimeError(
            f"Voiceover is {total:.1f}s, above configured Shorts limit {max_seconds:.1f}s. "
            "Shorten the script before upload."
        )
    scenes = script["scenes"]
    spans = captions.build_scene_timing(scenes, word_timings, total)
    specs = []
    visual_report = []
    for index, (scene, (start, end)) in enumerate(zip(scenes, spans)):
        duration = max(0.8, end - start)
        image_path = media.get_scene_image(
            cfg, scene.get("keywords", scene["text"]), width, height,
            image_path=scene.get("image_path"),
        )
        caption_specs = []
        if use_captions:
            for chunk_index, (caption_text, cap_start, cap_end) in enumerate(
                captions.timed_subtitle_chunks(scene["text"], duration, caption_words)
            ):
                cap_id = hashlib.md5(
                    f"{out_path}:{width}x{height}:{font_size}:{index}:{chunk_index}:{caption_text}".encode()
                ).hexdigest()[:12]
                cap_png = cache / f"cap_{cap_id}.png"
                captions.render_caption(
                    caption_text, width, height, font_size, cap_png,
                    style=caption_style, vertical_position=caption_position,
                )
                caption_specs.append((cap_start, cap_end, cap_png))
        specs.append({
            "start": start, "end": end, "duration": duration,
            "image": Path(image_path), "effect": scene.get("effect", "push_in") if use_kb else "none",
            "captions": caption_specs,
        })
        visual_report.append({
            "scene": index + 1,
            "selected": {"type": "image_motion", "provider": "local", "path": str(image_path)},
            "fallback_failures": [], "compositor": "bounded_uint8",
        })

    with Image.open(_vignette_path(cache, width, height)) as opened_vignette:
        vignette = opened_vignette.convert("RGBA")
    ends = [float(spec["end"]) for spec in specs]
    state = {"scene": -1, "source": None, "caption_path": None, "caption": None, "next_progress": 0}

    def close_cached_images() -> None:
        for key in ("source", "caption"):
            image = state.get(key)
            if image is not None:
                image.close()
                state[key] = None

    def make_frame(at: float) -> np.ndarray:
        scene_index = min(len(specs) - 1, bisect.bisect_right(ends, float(at)))
        spec = specs[scene_index]
        if state["scene"] != scene_index:
            close_cached_images()
            with Image.open(spec["image"]) as opened:
                source = opened.convert("RGB")
            if source.size != (width, height):
                resized = source.resize((width, height), Image.Resampling.LANCZOS)
                source.close()
                source = resized
            state["source"] = source
            state["scene"] = scene_index
            state["caption_path"] = None
        local_time = max(0.0, min(float(spec["duration"]), float(at) - float(spec["start"])))
        caption_path = next(
            (path for start, end, path in spec["captions"] if start <= local_time < end), None
        )
        if caption_path != state["caption_path"]:
            if state["caption"] is not None:
                state["caption"].close()
                state["caption"] = None
            if caption_path is not None:
                with Image.open(caption_path) as opened:
                    state["caption"] = opened.convert("RGBA")
            state["caption_path"] = caption_path
        percent = int(min(100, max(0, float(at) / max(total, 0.01) * 100)))
        if percent >= state["next_progress"]:
            print(f"RENDER_PROGRESS {percent}% scene={scene_index + 1}/{len(specs)}", flush=True)
            state["next_progress"] = min(101, ((percent // 10) + 1) * 10)
        return _safe_still_frame(
            state["source"], vignette, state["caption"], width, height,
            float(spec["duration"]), local_time, str(spec["effect"]), scene_index,
        )

    audio_tracks = [voice]
    opened_audio_clips = []
    generated_music, generated_effects = sound.ensure_story_audio()
    legacy_music = ROOT / "assets" / "music.mp3"
    music_path = legacy_music if legacy_music.exists() else generated_music
    if cfg.get("video", "background_music", default=True) and music_path.exists():
        volume = float(cfg.get("video", "music_volume", default=0.08))
        music = AudioFileClip(str(music_path)).fx(afx.audio_loop, duration=total).volumex(volume)
        opened_audio_clips.append(music)
        audio_tracks.append(music)
    sfx_volume = float(cfg.get("video", "sfx_volume", default=0.12))
    for (start, _), effect_path in zip(spans, generated_effects):
        if effect_path.exists():
            effect_clip = AudioFileClip(str(effect_path)).volumex(sfx_volume).set_start(start + 0.08)
            opened_audio_clips.append(effect_clip)
            audio_tracks.append(effect_clip)
    audio = CompositeAudioClip(audio_tracks)
    rendered = VideoClip(make_frame=make_frame, duration=total).set_fps(fps).set_audio(audio)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    temp_path.unlink(missing_ok=True)
    succeeded = False
    try:
        print(
            f"RENDER_MODE bounded_uint8 resolution={width}x{height} fps={fps} threads={encoder_threads}",
            flush=True,
        )
        rendered.write_videofile(
            str(temp_path), fps=fps, codec="libx264", audio_codec="aac",
            preset="veryfast", threads=max(1, min(encoder_threads, 4)),
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            verbose=False, logger=None,
        )
        temp_path.replace(out_path)
        succeeded = True
        report_path = out_path.with_name("visual_sources.json")
        report_temp = report_path.with_name(report_path.name + ".tmp")
        report_temp.write_text(
            json.dumps({"version": 2, "scenes": visual_report}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_temp.replace(report_path)
        print("RENDER_PROGRESS 100% complete", flush=True)
    finally:
        if not succeeded:
            temp_path.unlink(missing_ok=True)
        close_cached_images()
        vignette.close()
        try:
            rendered.close()
        except Exception:
            pass
        try:
            audio.close()
        except Exception:
            pass
        voice.close()
        for audio_clip in opened_audio_clips:
            try:
                audio_clip.close()
            except Exception:
                pass
    return out_path


def build_video(cfg, script: dict, voice_path: Path, word_timings, out_path: Path) -> Path:
    memory_safe = bool(cfg.get("video", "memory_safe_compositor", default=False))
    still_only = all(not any(_motion_candidates(scene)) for scene in script.get("scenes", []))
    if memory_safe and still_only:
        return _build_video_memory_safe(cfg, script, voice_path, word_timings, out_path)
    W = cfg.get("video", "width", default=1080)
    H = cfg.get("video", "height", default=1920)
    fps = cfg.get("video", "fps", default=30)
    font_size = cfg.get("video", "caption_font_size", default=70)
    caption_style = cfg.get("video", "caption_style", default="cinematic")
    caption_words = int(cfg.get("video", "caption_words_per_chunk", default=5))
    caption_position = float(cfg.get("video", "caption_vertical_position", default=0.78))
    use_captions = cfg.get("video", "captions", default=True)
    use_kb = cfg.get("video", "ken_burns", default=True)
    cache = cfg.cache_dir()

    voice = AudioFileClip(str(voice_path))
    total = voice.duration
    max_seconds = float(cfg.get("video", "max_seconds", default=0) or 0)
    if max_seconds and total > max_seconds + 0.25:
        voice.close()
        raise RuntimeError(
            f"Voiceover is {total:.1f}s, above configured Shorts limit {max_seconds:.1f}s. "
            "Shorten the script before upload."
        )

    scenes = script["scenes"]
    spans = captions.build_scene_timing(scenes, word_timings, total)

    clips = []
    opened_motion_clips = []
    visual_report = []
    for i, (scene, (start, end)) in enumerate(zip(scenes, spans)):
        dur = max(0.8, end - start)
        base = None
        selected = None
        failures = []
        for provider, motion_path in _motion_candidates(scene):
            candidate = motion_path
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            if not candidate.exists():
                failures.append({"provider": provider, "path": str(candidate), "error": "missing"})
                continue
            try:
                base = _motion_clip(candidate, W, H, dur)
                opened_motion_clips.append(base)
                selected = {"type": "video", "provider": provider, "path": str(candidate)}
                break
            except Exception as exc:
                failures.append({"provider": provider, "path": str(candidate), "error": str(exc)[:180]})
                print(f"  [video] {provider} clip failed for scene {i + 1}: {exc}; trying fallback")

        if base is None:
            # Explicit episode artwork owns the scene. Generic stock footage must
            # never silently replace a recurring character or story location.
            has_story_art = bool(scene.get("image_path"))
            allow_stock = scene.get("allow_stock_video", not has_story_art)
            if cfg.get("video", "stock_video", default=True) and allow_stock:
                stock_path = media.get_scene_video(cfg, scene.get("keywords", scene["text"]),
                                                   W, H, dur)
                if stock_path:
                    try:
                        base = _motion_clip(stock_path, W, H, dur)
                        opened_motion_clips.append(base)
                        selected = {"type": "stock", "provider": "pexels", "path": str(stock_path)}
                    except Exception as exc:
                        print(f"  [video] stock video failed for scene {i + 1}: {exc}; using still")

        if base is None:
            img_path = media.get_scene_image(
                cfg,
                scene.get("keywords", scene["text"]),
                W,
                H,
                image_path=scene.get("image_path"),
            )
            base = ImageClip(str(img_path)).set_duration(dur)
            if use_kb:
                base = _ken_burns(
                    base, dur, scene_index=i, effect=scene.get("effect", "push_in")
                )
            else:
                base = base.set_position("center")
            selected = {"type": "image_motion", "provider": "local", "path": str(img_path)}

        visual_report.append({
            "scene": i + 1,
            "selected": selected,
            "fallback_failures": failures,
        })

        layers = [base] + _cinematic_layers(
            cache, W, H, dur, scene.get("effect", "push_in"), i
        )
        if use_captions:
            for chunk_index, (caption_text, cap_start, cap_end) in enumerate(
                captions.timed_subtitle_chunks(scene["text"], dur, caption_words)
            ):
                cap_id = hashlib.md5(
                    f"{out_path}:{W}x{H}:{font_size}:{i}:{chunk_index}:{caption_text}".encode()
                ).hexdigest()[:12]
                cap_png = cache / f"cap_{cap_id}.png"
                captions.render_caption(
                    caption_text, W, H, font_size, cap_png,
                    style=caption_style, vertical_position=caption_position,
                )
                cap = (
                    ImageClip(str(cap_png))
                    .set_start(cap_start)
                    .set_duration(max(0.35, cap_end - cap_start))
                    .set_position("center")
                )
                layers.append(cap)

        scene_clip = CompositeVideoClip(layers, size=(W, H)).set_duration(dur)
        clips.append(scene_clip)

    video = concatenate_videoclips(clips, method="compose").set_duration(total)

    # ── audio: voiceover (+ optional looped background music) ──
    audio_tracks = [voice]
    opened_audio_clips = []
    generated_music, generated_effects = sound.ensure_story_audio()
    legacy_music = ROOT / "assets" / "music.mp3"
    music_path = legacy_music if legacy_music.exists() else generated_music
    if cfg.get("video", "background_music", default=True) and music_path.exists():
        vol = cfg.get("video", "music_volume", default=0.08)
        music = AudioFileClip(str(music_path)).fx(afx.audio_loop, duration=total).volumex(vol)
        opened_audio_clips.append(music)
        audio_tracks.append(music)
    sfx_volume = float(cfg.get("video", "sfx_volume", default=0.12))
    for i, ((start, end), effect_path) in enumerate(zip(spans, generated_effects)):
        if not effect_path.exists():
            continue
        effect_clip = AudioFileClip(str(effect_path)).volumex(sfx_volume).set_start(start + 0.08)
        opened_audio_clips.append(effect_clip)
        audio_tracks.append(effect_clip)
    audio = CompositeAudioClip(audio_tracks)
    video = video.set_audio(audio)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    temp_path.unlink(missing_ok=True)
    try:
        video.write_videofile(
            str(temp_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="veryfast",
            threads=4,
            verbose=False,
            logger=None,
        )
        temp_path.replace(out_path)
        report_path = out_path.with_name("visual_sources.json")
        report_temp = report_path.with_name(report_path.name + ".tmp")
        report_temp.write_text(
            json.dumps({"version": 1, "scenes": visual_report}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_temp.replace(report_path)
    finally:
        temp_path.unlink(missing_ok=True)
    video.close()
    voice.close()
    for motion in opened_motion_clips:
        try:
            motion.close()
        except Exception:
            pass
    for audio_clip in opened_audio_clips:
        try:
            audio_clip.close()
        except Exception:
            pass
    return out_path
