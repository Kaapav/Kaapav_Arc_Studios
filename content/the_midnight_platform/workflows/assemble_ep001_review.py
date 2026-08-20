"""Assemble six verified native-motion shots into the private Episode 1 review master."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


STORY_ROOT = Path(__file__).resolve().parents[1]
EPISODE_ROOT = STORY_ROOT / "episodes" / "ep001"
MOTION_ROOT = EPISODE_ROOT / "motion"
AUDIO_ROOT = EPISODE_ROOT / "audio"
ASSEMBLY_ROOT = EPISODE_ROOT / "assembly"
REVIEW_ROOT = EPISODE_ROOT / "review"
OUTPUT = REVIEW_ROOT / "THE_MIDNIGHT_PLATFORM_EP001_PRIVATE_REVIEW.mp4"
MANIFEST = REVIEW_ROOT / "review_manifest.json"
TOTAL_SECONDS = 31.0
SHOT_SECONDS = 5.0


def run(command: list[str]) -> str:
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stderr[-8000:]}"
        )
    return completed.stdout


def probe(path: Path, *, count_frames: bool = False) -> dict:
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
    command.extend([
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate,nb_read_frames:format=duration,size",
        "-of", "json", str(path),
    ])
    return json.loads(run(command))


def ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60
    return f"{hours}:{minutes:02d}:{remaining:05.2f}"


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def build_subtitles(path: Path, dialogue: dict) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dialogue,Bahnschrift,41,&H00FFFFFF,&H000000FF,&HD40A0D13,&H780A0D13,-1,0,0,0,100,100,0,0,1,3.2,0.8,2,52,52,130,1
Style: Hook,Bahnschrift,60,&H00FFFFFF,&H000000FF,&HE0000000,&H90000000,-1,0,0,0,98,100,1.2,0,1,4,0,8,40,40,164,1
Style: Editorial,Bahnschrift,48,&H00E6C98A,&H000000FF,&HE00A0D13,&HA0000000,-1,0,0,0,98,100,1.6,0,1,4,0,5,48,48,0,1
Style: Label,Bahnschrift,25,&H00E6C98A,&H000000FF,&HC00A0D13,&H60000000,-1,0,0,0,100,100,2.2,0,1,2,0,7,40,40,52,1
Style: End,Bahnschrift,49,&H00F4EADA,&H000000FF,&HFF000000,&HFF000000,-1,0,0,0,98,100,1.4,0,1,3,0,5,50,50,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = [
        "Dialogue: 2,0:00:00.00,0:00:01.90,Label,,0,0,0,,KAAPAV ARC STUDIOS  /  ORIGINAL SERIES",
        "Dialogue: 1,0:00:00.10,0:00:02.35,Hook,,0,0,0,,THE TRAIN RETURNED HER.",
        "Dialogue: 1,0:00:10.20,0:00:14.25,Editorial,,0,0,0,,ONE MAY RETURN.\\NONE MUST TAKE THEIR PLACE.",
        "Dialogue: 1,0:00:25.10,0:00:29.55,Label,,0,0,0,,PASSENGER 01 / 13",
        "Dialogue: 3,0:00:30.00,0:00:30.96,End,,0,0,0,,THE NEXT DOOR OPENS\\NAT MIDNIGHT",
    ]
    for line in dialogue["lines"]:
        start = float(line["timeline_start"])
        end = min(29.92, start + float(line["duration"]) + 0.13)
        # The station announcement is already presented as the central editorial beat.
        if line["speaker"] == "station":
            continue
        events.append(
            f"Dialogue: 2,{ass_time(start)},{ass_time(end)},Dialogue,,0,0,0,,"
            f"{ass_escape(line['text'])}"
        )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def validate_inputs() -> tuple[list[Path], Path, Path, dict]:
    clips = [MOTION_ROOT / f"midnight_platform_ep001_shot_{index:02d}.mp4" for index in range(1, 7)]
    missing = [str(path) for path in clips if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing WAN motion clips: {missing}")
    for index, clip in enumerate(clips, 1):
        payload = probe(clip, count_frames=True)
        stream = next(item for item in payload["streams"] if item["codec_type"] == "video")
        duration = float(payload["format"]["duration"])
        frames = int(stream.get("nb_read_frames") or 0)
        if stream.get("width") != 480 or stream.get("height") != 832:
            raise RuntimeError(f"Shot {index} dimensions failed: {payload}")
        if frames < 80 or duration < SHOT_SECONDS:
            raise RuntimeError(f"Shot {index} motion duration failed: {payload}")

    score = AUDIO_ROOT / "design" / "ep001_original_score.wav"
    effects = AUDIO_ROOT / "design" / "ep001_sound_design.wav"
    dialogue_path = AUDIO_ROOT / "dialogue_manifest.json"
    for path in (score, effects, dialogue_path):
        if not path.exists():
            raise FileNotFoundError(path)
    dialogue = json.loads(dialogue_path.read_text(encoding="utf-8"))
    if len(dialogue.get("lines", [])) != 9:
        raise RuntimeError("Episode 1 must contain exactly nine locked dialogue lines")
    for line in dialogue["lines"]:
        if not Path(line["path"]).exists():
            raise FileNotFoundError(line["path"])
    return clips, score, effects, dialogue


def main() -> None:
    clips, score, effects, dialogue = validate_inputs()
    ASSEMBLY_ROOT.mkdir(parents=True, exist_ok=True)
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    subtitles = ASSEMBLY_ROOT / "ep001_editorial.ass"
    build_subtitles(subtitles, dialogue)

    inputs: list[str] = []
    for clip in clips:
        inputs.extend(["-i", str(clip)])
    inputs.extend(["-i", str(score), "-i", str(effects)])
    for line in dialogue["lines"]:
        inputs.extend(["-i", str(line["path"])])

    filters: list[str] = []
    shot_labels = []
    for index in range(6):
        label = f"shot{index}"
        filters.append(
            f"[{index}:v]trim=start=0:end={SHOT_SECONDS},setpts=PTS-STARTPTS,"
            "minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
            "scale=739:1280:flags=lanczos,crop=720:1280:9:0,setsar=1"
            f"[{label}]"
        )
        shot_labels.append(f"[{label}]")
    filters.append("".join(shot_labels) + "concat=n=6:v=1:a=0[episode]")
    subtitle_filter = str(subtitles).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    filters.append(
        "[episode]tpad=stop_mode=clone:stop_duration=1,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.82:t=fill:enable='between(t,30,31)',"
        f"subtitles=filename='{subtitle_filter}'[video]"
    )

    filters.extend([
        "[6:a]atrim=0:31,asetpts=PTS-STARTPTS,volume=0.37[score]",
        "[7:a]atrim=0:31,asetpts=PTS-STARTPTS,volume=0.68[effects]",
        "[score][effects]amix=inputs=2:duration=longest:normalize=0[background]",
    ])
    dialogue_labels = []
    for index, line in enumerate(dialogue["lines"]):
        input_index = 8 + index
        delay = int(round(float(line["timeline_start"]) * 1000))
        label = f"dialogue{index}"
        filters.append(
            f"[{input_index}:a]pan=stereo|c0=c0|c1=c0,adelay={delay}|{delay},"
            f"volume=1.0[{label}]"
        )
        dialogue_labels.append(f"[{label}]")
    filters.append(
        "".join(dialogue_labels)
        + f"amix=inputs={len(dialogue_labels)}:duration=longest:normalize=0,"
        "apad=whole_dur=31,atrim=0:31[dialogue]"
    )
    filters.extend([
        "[background][dialogue]sidechaincompress=threshold=0.020:ratio=7:attack=8:release=220[ducked]",
        "[ducked][dialogue]amix=inputs=2:duration=longest:normalize=0,"
        "loudnorm=I=-16:TP=-1.5:LRA=10,atrim=0:31[audio]",
    ])

    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[video]", "-map", "[audio]", "-t", str(TOTAL_SECONDS),
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(OUTPUT),
    ])

    result = probe(OUTPUT, count_frames=True)
    video = next(item for item in result["streams"] if item["codec_type"] == "video")
    audio = next((item for item in result["streams"] if item["codec_type"] == "audio"), None)
    duration = float(result["format"]["duration"])
    if video.get("width") != 720 or video.get("height") != 1280:
        raise RuntimeError(f"Final dimensions failed: {result}")
    if video.get("r_frame_rate") != "24/1" or not audio or audio.get("codec_name") != "aac":
        raise RuntimeError(f"Final stream contract failed: {result}")
    if not 30.95 <= duration <= 31.05:
        raise RuntimeError(f"Final duration failed: {duration}")

    manifest = {
        "status": "technical_assembly_passed_visual_qc_pending",
        "private_review_only": True,
        "youtube_uploaded": False,
        "source_model": "Wan2.1-I2V-14B-FP8",
        "native_motion_clips": [str(path) for path in clips],
        "looping": False,
        "time_stretch": False,
        "motion_interpolation": "16fps source to 24fps delivery; duration unchanged",
        "output": str(OUTPUT),
        "probe": result,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
