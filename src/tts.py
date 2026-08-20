"""Text -> voiceover mp3 + word-level timing.

Default: edge-tts (free, no key, excellent hi-IN / en-IN voices). It streams both
audio bytes AND WordBoundary events, which we turn into precise caption timings.

Optional: ElevenLabs (set ELEVENLABS_API_KEY) for a premium voice, but without
word timings we fall back to proportional caption timing.
"""
import asyncio
import re
import shutil
import subprocess
import wave
from pathlib import Path
import edge_tts


_PIPER_VOICES = {}


async def _edge_synthesize(text, voice, rate, pitch, out_path):
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    words = []  # list of (word, start_sec, end_sec)
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000       # 100-ns ticks -> seconds
                dur = chunk["duration"] / 10_000_000
                words.append((chunk["text"], start, start + dur))
    return words


def synthesize(cfg, text: str, out_path: Path):
    """Returns list of (word, start, end). Writes mp3 to out_path."""
    provider = cfg.get("voice", "provider", default="edge")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if provider == "elevenlabs" and cfg.eleven_key:
        return _elevenlabs(cfg, text, out_path)

    if provider == "piper":
        try:
            return _piper_synthesize(cfg, text, out_path)
        except Exception as exc:
            print(f"  [tts] Piper unavailable ({exc}); trying Edge TTS.")

    voice = cfg.get("voice", "edge_voice", default="hi-IN-MadhurNeural")
    rate = cfg.get("voice", "rate", default="+0%")
    pitch = cfg.get("voice", "pitch", default="+0Hz")
    try:
        timeout = float(cfg.get("voice", "edge_timeout_seconds", default=25) or 25)
        return asyncio.run(asyncio.wait_for(
            _edge_synthesize(text, voice, rate, pitch, out_path), timeout=timeout
        ))
    except Exception as exc:
        if not shutil.which("powershell"):
            raise RuntimeError(
                f"Edge TTS failed ({exc}) and Windows PowerShell is unavailable."
            ) from exc
        print(f"  [tts] Edge TTS unavailable ({exc}); using Windows offline voice.")
    return _sapi_synthesize(text, rate, out_path)


def _piper_synthesize(cfg, text: str, out_path: Path):
    """Local neural TTS using Piper; no API key or network call at render time."""
    from piper import PiperVoice

    model_path = Path(cfg.get(
        "voice", "piper_model",
        default="assets/voices/piper/en_US-lessac-medium.onnx",
    ))
    if not model_path.is_absolute():
        model_path = Path(__file__).resolve().parent.parent / model_path
    if not model_path.exists():
        raise FileNotFoundError(f"Piper model not found: {model_path}")

    wav_path = out_path.with_suffix(".wav")
    cache_key = str(model_path.resolve())
    voice = _PIPER_VOICES.get(cache_key)
    if voice is None:
        voice = PiperVoice.load(model_path)
        _PIPER_VOICES[cache_key] = voice
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(voice.config.sample_rate)
        for chunk in voice.synthesize(text):
            wav_file.writeframes(chunk.audio_int16_bytes)

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), str(out_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    with wave.open(str(wav_path), "rb") as audio:
        duration = audio.getnframes() / float(audio.getframerate())
    wav_path.unlink(missing_ok=True)

    timing_provider = str(cfg.get(
        "voice", "word_timing_provider", default="proportional"
    ) or "proportional").lower()
    if timing_provider == "whisper":
        try:
            return _whisper_timings(cfg, out_path)
        except Exception as exc:
            print(f"  [tts] Whisper timings unavailable ({exc}); using proportional timings.")
    return _proportional_timings(text, duration)


def _proportional_timings(text: str, duration: float):
    tokens = text.split()
    if not tokens:
        return []
    step = duration / len(tokens)
    return [(word, i * step, (i + 1) * step) for i, word in enumerate(tokens)]


_WHISPER_MODELS = {}


def _whisper_timings(cfg, audio_path: Path):
    """Use faster-whisper word timestamps when available."""
    from faster_whisper import WhisperModel

    model_name = cfg.get("voice", "whisper_model", default="tiny.en")
    cache_root = cfg.cache_dir() / "whisper"
    key = str(cache_root / model_name)
    model = _WHISPER_MODELS.get(key)
    if model is None:
        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(cache_root),
        )
        _WHISPER_MODELS[key] = model
    segments, _ = model.transcribe(
        str(audio_path),
        language="en",
        word_timestamps=True,
        vad_filter=True,
    )
    timings = []
    for segment in segments:
        for word in segment.words or []:
            timings.append((word.word.strip(), word.start, word.end))
    if not timings:
        raise RuntimeError("Whisper returned no word timings")
    return timings


def _sapi_synthesize(text: str, rate: str, out_path: Path):
    """Offline Windows fallback using the built-in SAPI speech engine."""
    wav_path = out_path.with_suffix(".wav")
    text_path = out_path.with_suffix(".txt")
    # Pass narration through a UTF-8 file instead of embedding it in a
    # PowerShell command. Apostrophes, newlines, em dashes, and quotes are
    # common in generated scripts and otherwise break PowerShell parsing.
    text_path.write_text(text, encoding="utf-8-sig")
    ps_path = str(wav_path).replace("'", "''")
    ps_text_path = str(text_path).replace("'", "''")
    match = re.search(r"[-+]?\d+", str(rate))
    sapi_rate = max(-10, min(10, round(int(match.group()) / 10))) if match else 0
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate={sapi_rate}; "
        f"$s.SetOutputToWaveFile('{ps_path}'); "
        f"$text=[IO.File]::ReadAllText('{ps_text_path}'); "
        "$s.Speak($text); $s.Dispose();"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        text_path.unlink(missing_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), str(out_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    with wave.open(str(wav_path), "rb") as audio:
        duration = audio.getnframes() / float(audio.getframerate())
    wav_path.unlink(missing_ok=True)
    return _proportional_timings(text, duration)


def _elevenlabs(cfg, text, out_path):
    import requests
    voice_id = cfg.eleven_voice or "21m00Tcm4TlvDq8ikWAM"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    r = requests.post(
        url,
        headers={"xi-api-key": cfg.eleven_key, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=120,
    )
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return []  # no word timings -> caller uses proportional timing
