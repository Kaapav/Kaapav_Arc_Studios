"""Create deterministic, original Episode 1 music and sound design offline."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


STORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = STORY_ROOT / "episodes" / "ep001" / "audio" / "design"
SAMPLE_RATE = 48_000
DURATION = 31.0
SAMPLE_COUNT = int(SAMPLE_RATE * DURATION)


def envelope(start: float, duration: float, attack: float = 0.03, release: float = 0.25) -> tuple[slice, np.ndarray]:
    first = max(0, int(start * SAMPLE_RATE))
    last = min(SAMPLE_COUNT, int((start + duration) * SAMPLE_RATE))
    count = max(0, last - first)
    if not count:
        return slice(first, first), np.empty(0)
    local = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    gain = np.minimum(1.0, local / max(attack, 1 / SAMPLE_RATE))
    gain *= np.minimum(1.0, (duration - local) / max(release, 1 / SAMPLE_RATE))
    return slice(first, last), np.clip(gain, 0.0, 1.0)


def add_tone(
    target: np.ndarray,
    start: float,
    duration: float,
    frequency: float,
    amplitude: float,
    *,
    end_frequency: float | None = None,
    pan: float = 0.0,
    attack: float = 0.02,
    release: float = 0.25,
) -> None:
    region, gain = envelope(start, duration, attack, release)
    count = len(gain)
    if not count:
        return
    local = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    if end_frequency is None:
        phase = 2 * np.pi * frequency * local
    else:
        slope = (end_frequency - frequency) / max(duration, 1 / SAMPLE_RATE)
        phase = 2 * np.pi * (frequency * local + 0.5 * slope * local * local)
    signal = np.sin(phase) * gain * amplitude
    target[region, 0] += signal * np.sqrt((1.0 - pan) * 0.5)
    target[region, 1] += signal * np.sqrt((1.0 + pan) * 0.5)


def shaped_noise(rng: np.random.Generator, low_hz: float, high_hz: float) -> np.ndarray:
    spectrum = np.fft.rfft(rng.normal(0.0, 1.0, SAMPLE_COUNT))
    frequencies = np.fft.rfftfreq(SAMPLE_COUNT, 1 / SAMPLE_RATE)
    mask = (frequencies >= low_hz) & (frequencies <= high_hz)
    spectrum *= mask
    signal = np.fft.irfft(spectrum, n=SAMPLE_COUNT)
    peak = float(np.max(np.abs(signal)) or 1.0)
    return signal / peak


def add_noise_burst(
    target: np.ndarray,
    noise: np.ndarray,
    start: float,
    duration: float,
    amplitude: float,
    *,
    pan_start: float = 0.0,
    pan_end: float = 0.0,
    attack: float = 0.02,
    release: float = 0.35,
) -> None:
    region, gain = envelope(start, duration, attack, release)
    count = len(gain)
    if not count:
        return
    first = region.start
    segment = noise[first:first + count] * gain * amplitude
    pan = np.linspace(pan_start, pan_end, count)
    target[region, 0] += segment * np.sqrt((1.0 - pan) * 0.5)
    target[region, 1] += segment * np.sqrt((1.0 + pan) * 0.5)


def build_music() -> np.ndarray:
    music = np.zeros((SAMPLE_COUNT, 2), dtype=np.float64)
    time = np.arange(SAMPLE_COUNT, dtype=np.float64) / SAMPLE_RATE
    master = np.minimum(1.0, time / 1.2) * np.minimum(1.0, (DURATION - time) / 1.0)
    pulse = 0.72 + 0.28 * np.sin(2 * np.pi * 0.075 * time - 0.8)
    for frequency, amplitude, phase, pan in (
        (36.71, 0.105, 0.0, -0.20),
        (55.00, 0.055, 0.6, 0.20),
        (73.42, 0.032, 1.3, -0.05),
    ):
        signal = np.sin(2 * np.pi * frequency * time + phase) * amplitude * pulse * master
        music[:, 0] += signal * np.sqrt((1.0 - pan) * 0.5)
        music[:, 1] += signal * np.sqrt((1.0 + pan) * 0.5)

    motif = [293.66, 349.23, 440.00, 329.63, 293.66, 466.16]
    for index, start in enumerate((1.8, 6.8, 11.8, 16.8, 21.8, 26.8)):
        add_tone(
            music, start, 2.7, motif[index], 0.032,
            pan=-0.35 + index * 0.14, attack=0.01, release=2.45,
        )
        add_tone(
            music, start + 0.018, 2.1, motif[index] * 2.0, 0.011,
            pan=0.35 - index * 0.10, attack=0.01, release=1.9,
        )
    return music


def build_effects() -> np.ndarray:
    effects = np.zeros((SAMPLE_COUNT, 2), dtype=np.float64)
    rng = np.random.default_rng(317001)
    low_noise = shaped_noise(rng, 18.0, 180.0)
    rain_noise = shaped_noise(rng, 900.0, 8_000.0)
    metal_noise = shaped_noise(rng, 280.0, 5_500.0)

    # Wet midnight-platform ambience, deliberately quiet beneath dialogue.
    effects[:, 0] += rain_noise * 0.026
    effects[:, 1] += np.roll(rain_noise, 1_731) * 0.025
    time = np.arange(SAMPLE_COUNT, dtype=np.float64) / SAMPLE_RATE
    effects[:, 0] += low_noise * (0.035 + 0.016 * np.sin(2 * np.pi * 0.11 * time))
    effects[:, 1] += np.roll(low_noise, 863) * (0.034 + 0.015 * np.sin(2 * np.pi * 0.097 * time + 1.1))

    # Shot 1: coherent approach and pressure wave.
    add_tone(effects, 0.0, 5.0, 31.0, 0.18, end_frequency=47.0, release=0.2)
    add_tone(effects, 0.4, 4.6, 62.0, 0.075, end_frequency=94.0, pan=-0.1, release=0.15)
    add_noise_burst(effects, low_noise, 2.5, 2.5, 0.19, pan_start=-0.45, pan_end=0.45, attack=0.7, release=0.12)
    add_tone(effects, 4.58, 0.38, 54.0, 0.22, end_frequency=34.0, release=0.30)

    # Shot 2: brake, sliding brass door, and steam.
    add_tone(effects, 5.02, 1.15, 610.0, 0.055, end_frequency=185.0, pan=-0.35, release=0.25)
    add_noise_burst(effects, rain_noise, 5.10, 1.25, 0.16, pan_start=-0.6, pan_end=0.15, attack=0.04, release=0.55)
    add_noise_burst(effects, metal_noise, 5.25, 0.68, 0.11, pan_start=-0.25, pan_end=0.2, attack=0.03, release=0.18)

    # Shot 3: station mechanism and warning state.
    for index in range(6):
        start = 10.12 + index * 0.62
        add_tone(effects, start, 0.10, 1_280.0 - index * 65, 0.07, pan=(-0.4 + index * 0.16), release=0.08)
        add_tone(effects, start, 0.18, 96.0, 0.09, end_frequency=73.0, release=0.15)
    add_tone(effects, 13.72, 1.0, 225.0, 0.08, end_frequency=112.0, release=0.8)

    # Shot 4: threshold exchange, restrained energy, physical impact.
    add_noise_burst(effects, metal_noise, 15.25, 1.9, 0.13, pan_start=-0.65, pan_end=0.65, attack=0.65, release=0.6)
    add_tone(effects, 15.45, 2.1, 190.0, 0.075, end_frequency=740.0, pan=-0.2, attack=0.5, release=0.55)
    add_tone(effects, 17.55, 0.72, 66.0, 0.23, end_frequency=41.0, release=0.55)
    add_tone(effects, 17.58, 1.1, 880.0, 0.035, end_frequency=420.0, pan=0.4, release=0.9)

    # Shot 5: wheel rhythm accelerates with a left-to-right train pass.
    click = 20.10
    interval = 0.58
    while click < 24.85:
        add_tone(effects, click, 0.11, 112.0, 0.09, end_frequency=73.0, pan=-0.55 + (click - 20.1) / 4.75, release=0.09)
        add_noise_burst(effects, metal_noise, click, 0.08, 0.065, pan_start=-0.4, pan_end=0.4, release=0.07)
        click += interval
        interval = max(0.29, interval * 0.90)
    add_tone(effects, 20.0, 5.0, 42.0, 0.12, end_frequency=68.0, pan=0.25, release=0.20)

    # Shot 6: corridor lamp sequence, ticket reveal, final clock hit.
    for index in range(7):
        start = 25.25 + index * 0.47
        add_tone(effects, start, 0.13, 1_050.0 + index * 75, 0.045, pan=-0.72 + index * 0.24, release=0.11)
    add_noise_burst(effects, metal_noise, 25.42, 1.15, 0.075, pan_start=0.5, pan_end=-0.05, attack=0.25, release=0.50)
    add_tone(effects, 29.15, 1.0, 82.0, 0.25, end_frequency=37.0, release=0.85)
    add_tone(effects, 29.18, 1.25, 1_760.0, 0.038, end_frequency=880.0, pan=0.3, release=1.1)
    add_tone(effects, 30.02, 0.32, 49.0, 0.24, end_frequency=31.0, release=0.28)
    return effects


def write_wave(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(samples)) or 1.0)
    if peak > 0.97:
        samples = samples * (0.97 / peak)
    pcm = np.int16(np.clip(samples, -1.0, 1.0) * 32_767)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    temporary.replace(path)


def main() -> None:
    music = OUTPUT_ROOT / "ep001_original_score.wav"
    effects = OUTPUT_ROOT / "ep001_sound_design.wav"
    write_wave(music, build_music())
    write_wave(effects, build_effects())
    print(music)
    print(effects)


if __name__ == "__main__":
    main()
