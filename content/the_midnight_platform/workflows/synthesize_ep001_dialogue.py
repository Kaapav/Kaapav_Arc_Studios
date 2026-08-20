"""Generate distinct, fully offline Piper dialogue for Episode 1."""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig


STORY_ROOT = Path(__file__).resolve().parents[1]
EPISODE_ROOT = STORY_ROOT / "episodes" / "ep001"
EPISODE_PATH = EPISODE_ROOT / "episode.json"
VOICE_ROOT = STORY_ROOT / "assets" / "voices"
AUDIO_ROOT = EPISODE_ROOT / "audio" / "dialogue"
MANIFEST_PATH = EPISODE_ROOT / "audio" / "dialogue_manifest.json"

# One voice model is never reused with the same acoustic treatment for two
# characters. Pitch changes preserve duration; Piper length_scale controls pace.
PROFILES = {
    "narrator": {
        "model": "en_US-lessac-medium.onnx",
        "length_scale": 0.93,
        "pitch": 0.94,
        "filter": "highpass=f=75,lowpass=f=12500,acompressor=threshold=-18dB:ratio=2.2:attack=8:release=90",
    },
    "arin": {
        "model": "en_US-ryan-medium.onnx",
        "length_scale": 0.88,
        "pitch": 1.11,
        "filter": "highpass=f=105,lowpass=f=13500,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=70",
    },
    "meera": {
        "model": "en_US-amy-medium.onnx",
        "length_scale": 0.86,
        "pitch": 1.14,
        "filter": "highpass=f=130,lowpass=f=14000,acompressor=threshold=-21dB:ratio=2.4:attack=5:release=65",
    },
    "station": {
        "model": "en_US-amy-medium.onnx",
        "length_scale": 1.02,
        "pitch": 0.91,
        "filter": "highpass=f=160,lowpass=f=5200,aecho=0.8:0.72:45|90:0.17|0.09,acompressor=threshold=-19dB:ratio=2.7",
    },
    "conductor": {
        "model": "en_US-ryan-medium.onnx",
        "length_scale": 1.08,
        "pitch": 0.82,
        "filter": "highpass=f=62,lowpass=f=6800,equalizer=f=135:t=q:w=1.2:g=3,aecho=0.8:0.70:55|110:0.15|0.07,acompressor=threshold=-20dB:ratio=3.0",
    },
}


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def render_base(voice: PiperVoice, text: str, profile: dict, wav_path: Path) -> int:
    config = SynthesisConfig(
        length_scale=float(profile["length_scale"]),
        noise_scale=0.62,
        noise_w_scale=0.72,
        normalize_audio=True,
        volume=0.96,
    )
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(voice.config.sample_rate)
        for chunk in voice.synthesize(text, syn_config=config):
            handle.writeframes(chunk.audio_int16_bytes)
    return int(voice.config.sample_rate)


def process_voice(source: Path, destination: Path, sample_rate: int, profile: dict) -> None:
    pitch = float(profile["pitch"])
    filters = (
        f"asetrate={sample_rate}*{pitch:.6f},aresample=48000,"
        f"atempo={1.0 / pitch:.6f},{profile['filter']},"
        "loudnorm=I=-18:TP=-2:LRA=7"
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-af", filters,
            "-ar", "48000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
            str(destination),
        ],
        check=True,
    )


def main() -> None:
    episode = json.loads(EPISODE_PATH.read_text(encoding="utf-8"))
    AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    loaded: dict[str, PiperVoice] = {}
    manifest = {
        "schema_version": 1,
        "provider": "piper_offline",
        "license": "MIT voice repository; model cards retained at source",
        "lines": [],
    }
    for shot_index, shot in enumerate(episode["shots"], 1):
        for line_index, line in enumerate(shot.get("dialogue", []), 1):
            speaker = line["speaker"]
            profile = PROFILES[speaker]
            model_path = VOICE_ROOT / profile["model"]
            if not model_path.exists() or not model_path.with_suffix(model_path.suffix + ".json").exists():
                raise FileNotFoundError(model_path)
            voice = loaded.get(profile["model"])
            if voice is None:
                voice = PiperVoice.load(model_path)
                loaded[profile["model"]] = voice
            destination = AUDIO_ROOT / f"{shot['id']}_{line_index:02d}_{speaker}.mp3"
            wav_path = destination.with_suffix(".base.wav")
            sample_rate = render_base(voice, line["text"], profile, wav_path)
            try:
                process_voice(wav_path, destination, sample_rate, profile)
            finally:
                wav_path.unlink(missing_ok=True)
            duration = probe_duration(destination)
            available = float(shot["seconds"]) - float(line["at"])
            if duration > available + 0.05:
                raise RuntimeError(
                    f"{shot['id']} {speaker} line is {duration:.2f}s but only {available:.2f}s is available"
                )
            manifest["lines"].append(
                {
                    "shot": shot["id"],
                    "speaker": speaker,
                    "text": line["text"],
                    "shot_offset": line["at"],
                    "timeline_start": (shot_index - 1) * 5 + float(line["at"]),
                    "duration": round(duration, 3),
                    "model": profile["model"],
                    "pitch_factor": profile["pitch"],
                    "path": str(destination),
                }
            )
            print(f"{shot['id']} {speaker}: {duration:.2f}s", flush=True)
    temp = MANIFEST_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(MANIFEST_PATH)
    print(MANIFEST_PATH)


if __name__ == "__main__":
    main()
