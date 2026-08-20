"""Assemble the verified Wan motion clips into the private Episode 1 review master."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config import Config
from src import sound, tts


SHOT_SECONDS = 4.0
TOTAL_SECONDS = SHOT_SECONDS * 8
SOURCE_SECONDS = (41 / 16) * 8
LINES = [
    ("narrator", "At 2:17 AM, Kavi's dead phone rang."),
    ("future", "Don't open the red door. And whatever happens... don't trust Byte."),
    ("narrator", "Byte's eyes went dark."),
    ("mira", "Kavi, this recording is a hundred years old."),
    ("narrator", "Every arcade screen turned red. Something looked back from inside the static."),
    ("byte", "I remember what's behind it."),
    ("future", "You already opened it once."),
    ("future", "Run. Null can see you now."),
]
CAPTIONS = [
    "AT 2:17 AM,\nKAVI'S DEAD PHONE RANG.",
    "DON'T OPEN THE RED DOOR.\nDON'T TRUST BYTE.",
    "BYTE'S EYES\nWENT DARK.",
    "THIS RECORDING IS\nA HUNDRED YEARS OLD.",
    "EVERY SCREEN TURNED RED.\nSOMETHING LOOKED BACK.",
    "I REMEMBER\nWHAT'S BEHIND IT.",
    "YOU ALREADY\nOPENED IT ONCE.",
    "RUN.\nNULL CAN SEE YOU NOW.",
]


def run(command: list[str]) -> str:
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr[-5000:]}"
        )
    return completed.stdout


def probe(path: Path) -> dict:
    return json.loads(run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate:format=duration,size",
        "-of", "json", str(path),
    ]))


def ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60
    return f"{hours}:{minutes:02d}:{remaining:05.2f}"


def build_subtitles(path: Path) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,Arial,47,&H00FFFFFF,&H000000FF,&HCC080B14,&H90080B14,-1,0,0,0,100,100,0,0,1,4,1,2,48,48,154,1
Style: Brand,Arial,25,&H00F2E8D5,&H000000FF,&H90080B14,&H50080B14,1,0,0,0,100,100,2,0,1,2,0,8,40,40,52,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = ["Dialogue: 1,0:00:00.00,0:00:02.40,Brand,,0,0,0,,ECHO//100  •  EPISODE 1"]
    for index, caption in enumerate(CAPTIONS):
        start = index * SHOT_SECONDS + 0.25
        end = (index + 1) * SHOT_SECONDS - 0.25
        events.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{caption.replace(chr(10), r'\N')}"
        )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def voice_filter(role: str, duration: float) -> str:
    filters = []
    if role == "future":
        filters.extend(["asetrate=22050*0.94", "aresample=22050", "atempo=1.06383", "highpass=f=180", "lowpass=f=3200", "aecho=0.8:0.35:45:0.12"])
    elif role == "mira":
        filters.extend(["asetrate=22050*1.07", "aresample=22050", "atempo=0.93458", "highpass=f=220", "aecho=0.8:0.25:28:0.08"])
    elif role == "byte":
        filters.extend(["asetrate=22050*1.13", "aresample=22050", "atempo=0.88496", "highpass=f=260", "lowpass=f=4200", "acrusher=bits=12:mode=log:aa=1"])
    if duration > SHOT_SECONDS - 0.45:
        filters.append(f"atempo={duration / (SHOT_SECONDS - 0.45):.6f}")
    filters.extend(["adelay=140", f"apad=pad_dur={SHOT_SECONDS}", f"atrim=0:{SHOT_SECONDS}"])
    return ",".join(filters)


def build_dialogue(work: Path) -> Path:
    cfg = Config("config.story.yaml")
    cfg.data["voice"]["provider"] = "piper"
    segments = []
    for index, (role, line) in enumerate(LINES, 1):
        raw = work / f"voice_{index:02d}_raw.mp3"
        processed = work / f"voice_{index:02d}.wav"
        tts.synthesize(cfg, line, raw)
        duration = float(probe(raw)["format"]["duration"])
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
            "-af", voice_filter(role, duration), "-ar", "22050", "-ac", "1", str(processed),
        ])
        segments.append(processed)

    concat = work / "dialogue_concat.txt"
    concat.write_text("".join(f"file '{item.as_posix()}'\n" for item in segments), encoding="utf-8")
    dialogue = work / "dialogue.wav"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat), "-c:a", "pcm_s16le", str(dialogue),
    ])
    return dialogue


def build_soundscape(work: Path, dialogue: Path) -> Path:
    music, effects = sound.ensure_story_audio()
    inputs = ["-i", str(dialogue), "-stream_loop", "-1", "-i", str(music)]
    for effect in effects:
        inputs.extend(["-i", str(effect)])
    # One final phone ring closes the loop into the opening.
    inputs.extend(["-i", str(effects[0])])
    chains = [
        "[0:a]volume=1.0[dialogue]",
        f"[1:a]atrim=0:{TOTAL_SECONDS},volume=0.055[music]",
    ]
    labels = ["[dialogue]", "[music]"]
    for index in range(8):
        delay = round(index * SHOT_SECONDS * 1000 + 90)
        chains.append(f"[{index + 2}:a]adelay={delay},volume=0.16[sfx{index}]")
        labels.append(f"[sfx{index}]")
    final_delay = round(TOTAL_SECONDS * 1000 - 900)
    chains.append(f"[10:a]adelay={final_delay},volume=0.22[ring]")
    labels.append("[ring]")
    chains.append(
        "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{TOTAL_SECONDS}[mix]"
    )
    soundscape = work / "episode1_soundscape.wav"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
        "-filter_complex", ";".join(chains), "-map", "[mix]", "-ar", "48000", "-ac", "2", str(soundscape),
    ])
    return soundscape


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("silent_video", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    silent_video = args.silent_video.resolve()
    output = args.output.resolve()
    if not silent_video.exists():
        raise FileNotFoundError(silent_video)
    source_probe = probe(silent_video)
    duration = float(source_probe["format"]["duration"])
    stream = next(item for item in source_probe["streams"] if item["codec_type"] == "video")
    if stream.get("width") != 480 or stream.get("height") != 832 or not 20 <= duration <= 21:
        raise RuntimeError(f"Unexpected silent render: {source_probe}")

    work = output.parent / "episode1_assembly"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    subtitles = work / "episode1.ass"
    build_subtitles(subtitles)
    dialogue = build_dialogue(work)
    soundscape = build_soundscape(work, dialogue)

    output.parent.mkdir(parents=True, exist_ok=True)
    subtitle_filter = str(subtitles).replace("\\", "/").replace(":", r"\:")
    video_filter = (
        f"setpts={TOTAL_SECONDS / SOURCE_SECONDS:.8f}*PTS,"
        "scale=739:1280:flags=lanczos,crop=720:1280:9:0,fps=24,"
        f"subtitles='{subtitle_filter}',fade=t=out:st={TOTAL_SECONDS - 0.25}:d=0.25"
    )
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent_video),
        "-i", str(soundscape), "-vf", video_filter, "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(output),
    ])
    final_probe = probe(output)
    final_duration = float(final_probe["format"]["duration"])
    streams = final_probe["streams"]
    video_stream = next(item for item in streams if item["codec_type"] == "video")
    if video_stream.get("width") != 720 or video_stream.get("height") != 1280:
        raise RuntimeError(f"Final dimensions failed: {final_probe}")
    if not any(item["codec_type"] == "audio" for item in streams) or not 31.5 <= final_duration <= 32.5:
        raise RuntimeError(f"Final A/V validation failed: {final_probe}")
    manifest = {
        "status": "passed",
        "video": str(output),
        "probe": final_probe,
        "source": str(silent_video),
        "shots": 8,
        "actual_motion_only": True,
        "youtube_uploaded": False,
    }
    (output.parent / "episode1_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
