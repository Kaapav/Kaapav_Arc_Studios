"""Render the first original 3D story pilot without calling an LLM or stock media."""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config, ROOT
from src import tts, video


def main() -> None:
    cfg = Config()
    # Piper can be slow to load on this CPU-only machine; Edge will fall back
    # to Windows SAPI automatically if the network voice is unavailable.
    cfg.data["voice"]["provider"] = "edge"
    # Fast preview profile for this CPU-only machine; the same assets can be
    # re-rendered at 720x1280 after the story is approved.
    cfg.data["video"]["width"] = 360
    cfg.data["video"]["height"] = 640
    cfg.data["video"]["fps"] = 20
    cfg.data["video"]["background_music"] = False
    # This pilot is deliberately image-led: the generated character continuity
    # is the product. Do not let the general Pexels fallback replace these shots.
    cfg.data["video"]["stock_video"] = False
    cfg.data["video"]["ken_burns"] = True

    asset_dir = ROOT / "assets" / "story" / "echo100"
    scenes = [
        {
            "text": "At 2:17 AM, Kavi's dead phone played a voice note in his own voice.",
            "caption": "A message from tomorrow",
            "keywords": "Kavi dead phone abandoned arcade",
            "image_path": str(asset_dir / "exec-87ab096a-0780-4743-b93b-55d6b38522eb.png"),
        },
        {
            "text": "It said, 'Don't open the red door.' Then it added, 'Whatever happens, don't trust Byte.'",
            "caption": "Do not trust Byte",
            "keywords": "Kavi Byte warning phone",
            "image_path": str(asset_dir / "exec-87ab096a-0780-4743-b93b-55d6b38522eb.png"),
        },
        {
            "text": "Byte froze. Mira scanned the file and found something impossible.",
            "caption": "Mira finds the impossible",
            "keywords": "Mira hologram red door arcade",
            "image_path": str(asset_dir / "exec-89230522-4ba4-4bee-8de4-e38689900263.png"),
        },
        {
            "text": "The recording was dated one hundred years ago, even though Kavi had made the phone that morning.",
            "caption": "Recorded 100 years ago",
            "keywords": "hologram scans mysterious red door",
            "image_path": str(asset_dir / "exec-89230522-4ba4-4bee-8de4-e38689900263.png"),
        },
        {
            "text": "Then every screen in the arcade turned red. A shadow with glowing eyes appeared behind the pixels.",
            "caption": "The arcade changed",
            "keywords": "Null glitch arcade red screens",
            "image_path": str(asset_dir / "exec-8915310f-9232-413e-9a22-dd3bad7f366f.png"),
        },
        {
            "text": "A door appeared where there had only been a wall. Byte whispered, 'Kavi, I think I know what's behind it.'",
            "caption": "A door where none was",
            "keywords": "Kavi Byte Null red door",
            "image_path": str(asset_dir / "exec-8915310f-9232-413e-9a22-dd3bad7f366f.png"),
        },
        {
            "text": "Kavi touched the handle. The phone played one final message: 'You already opened it once.'",
            "caption": "You opened it once",
            "keywords": "Kavi opens red door future",
            "image_path": str(asset_dir / "exec-cbbccb8c-b9a3-462d-af4c-7abf2be6bbc4.png"),
        },
        {
            "text": "Behind the door stood tomorrow's Kavi. He looked terrified and said, 'Run before Null sees you.'",
            "caption": "Run before Null sees you",
            "keywords": "future Kavi Null doorway cliffhanger",
            "image_path": str(asset_dir / "exec-cbbccb8c-b9a3-462d-af4c-7abf2be6bbc4.png"),
        },
    ]
    script = {
        "title": "The Message From Tomorrow | Episode 1",
        "description": (
            "Kavi's dead phone receives a warning from the future. "
            "Episode 1 of ECHO-100: The Red Door. AI-generated animation pilot."
        ),
        "tags": ["animated short", "3d animation", "ai story", "webseries", "echo100"],
        "narration": " ".join(scene["text"] for scene in scenes),
        "scenes": scenes,
    }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = cfg.output_dir() / f"{stamp}-echo100-episode-001"
    out_dir.mkdir(parents=True, exist_ok=True)
    voice_path = out_dir / "voice.mp3"
    video_path = out_dir / "video.mp4"
    (out_dir / "script.json").write_text(json.dumps(script, indent=2), encoding="utf-8")

    print("[1/3] Generating offline voiceover...")
    timings = tts.synthesize(cfg, script["narration"], voice_path)
    print("[2/3] Rendering 3D story pilot...")
    video.build_video(cfg, script, voice_path, timings, video_path)
    (out_dir / "manifest.json").write_text(
        json.dumps({"title": script["title"], "video": str(video_path), "scenes": len(scenes)}, indent=2),
        encoding="utf-8",
    )
    print("[3/3] Done")
    print(video_path)


if __name__ == "__main__":
    main()
