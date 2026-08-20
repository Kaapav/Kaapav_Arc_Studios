"""Generate original, royalty-clear ECHO//100 music and scene effects offline."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .config import ROOT


AUDIO_DIR = ROOT / "assets" / "audio" / "echo100"
SAMPLE_RATE = 22050


def _write_wav(path: Path, samples: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(samples)) or 1.0)
    pcm = np.int16(np.clip(samples / max(1.0, peak) * 32767, -32767, 32767))
    temporary = path.with_name(path.name + ".tmp")
    with wave.open(str(temporary), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    temporary.replace(path)
    return path


def _music_bed(seconds: float = 64.0) -> np.ndarray:
    count = int(SAMPLE_RATE * seconds)
    t = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    slow = 0.5 + 0.5 * np.sin(2 * np.pi * 0.055 * t)
    drone = (
        0.34 * np.sin(2 * np.pi * 55.0 * t)
        + 0.18 * np.sin(2 * np.pi * 82.41 * t + 0.4)
        + 0.10 * np.sin(2 * np.pi * 110.0 * t + 1.1)
    ) * (0.38 + 0.22 * slow)
    notes = np.array([164.81, 196.00, 220.00, 146.83, 174.61, 220.00, 246.94, 196.00])
    step = np.minimum((t / 2.0).astype(int), 10_000)
    freq = notes[step % len(notes)]
    pulse_phase = np.cumsum(2 * np.pi * freq / SAMPLE_RATE)
    pulse_env = np.exp(-2.2 * (t % 2.0))
    pulse = 0.10 * np.sin(pulse_phase) * pulse_env
    rng = np.random.default_rng(100)
    anchors = rng.normal(0, 1, int(seconds * 4) + 2)
    haze = np.interp(np.arange(count), np.linspace(0, count - 1, len(anchors)), anchors)
    haze *= 0.015
    fade = np.minimum(1.0, t / 2.0) * np.minimum(1.0, (seconds - t) / 2.0)
    return (drone + pulse + haze) * np.clip(fade, 0, 1)


def _effect(index: int, seconds: float = 1.5) -> np.ndarray:
    count = int(SAMPLE_RATE * seconds)
    t = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    rng = np.random.default_rng(700 + index)
    decay = np.exp(-(2.2 + index * 0.12) * t)
    if index == 0:  # phone wake
        signal = np.sin(2 * np.pi * 880 * t) + 0.55 * np.sin(2 * np.pi * 1320 * t)
        return 0.5 * signal * np.exp(-5.0 * t)
    if index == 1:  # red warning
        signal = np.sin(2 * np.pi * (160 - 70 * t) * t)
        return 0.7 * signal * np.exp(-2.8 * t)
    if index in {2, 3}:  # hologram scan / anomaly
        sweep = np.sin(2 * np.pi * (280 + 900 * t) * t)
        return 0.34 * sweep * np.exp(-2.2 * t)
    if index == 4:  # Null glitch
        noise = rng.normal(0, 1, count)
        gate = ((t * 24).astype(int) % 3 == 0).astype(float)
        return 0.42 * (noise * gate + np.sin(2 * np.pi * 72 * t)) * decay
    if index in {5, 6}:  # door / future message
        rumble = np.sin(2 * np.pi * (48 + 12 * np.sin(2 * np.pi * 0.7 * t)) * t)
        shimmer = 0.22 * np.sin(2 * np.pi * 740 * t) * np.exp(-4 * t)
        return 0.6 * rumble * decay + shimmer
    # final threat hit
    hit = np.sin(2 * np.pi * (92 - 36 * t) * t)
    return 0.8 * hit * np.exp(-1.9 * t) + 0.12 * rng.normal(0, 1, count) * decay


def ensure_story_audio() -> tuple[Path, list[Path]]:
    """Create deterministic local assets once and return music + eight SFX paths."""
    music = AUDIO_DIR / "echo100-ambient-bed.wav"
    if not music.exists():
        _write_wav(music, _music_bed())
    effects = []
    for index in range(8):
        path = AUDIO_DIR / f"scene-{index + 1:02d}.wav"
        if not path.exists():
            _write_wav(path, _effect(index))
        effects.append(path)
    return music, effects
