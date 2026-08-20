"""Fast, no-upload smoke test for the permanent local fallback path."""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config
from src import media, runtime, tts, video


def main() -> None:
    cfg = Config()
    cfg.data["video"].update({
        "width": 180,
        "height": 320,
        "fps": 12,
        "max_seconds": 20,
        "stock_video": True,
        "background_music": False,
        "caption_font_size": 20,
    })
    cfg.data["voice"]["provider"] = "piper"
    cfg.data["voice"]["word_timing_provider"] = "proportional"

    source = ROOT / "assets" / "story" / "echo100" / \
        "exec-87ab096a-0780-4743-b93b-55d6b38522eb.png"
    if not source.exists():
        raise SystemExit(f"Missing smoke-test story asset: {source}")

    small = media.get_scene_image(cfg, "smoke", 180, 320, image_path=str(source))
    large = media.get_scene_image(cfg, "smoke", 360, 640, image_path=str(source))
    with Image.open(small) as image:
        assert image.size == (180, 320), image.size
    with Image.open(large) as image:
        assert image.size == (360, 640), image.size
    assert small != large, "dimension-specific cache keys are required"

    narration = "At midnight, the dead phone rang. Byte looked afraid. The screen said: run."
    scenes = [
        {"text": "At midnight, the dead phone rang.", "caption": "The phone woke up",
         "image_path": str(source)},
        {"text": "Byte looked afraid. The screen said: run.", "caption": "The warning said run",
         "image_path": str(source)},
    ]
    output = cfg.output_dir() / "stability-smoke"
    output.mkdir(parents=True, exist_ok=True)
    voice_path = output / "voice.mp3"
    video_path = output / "video.mp4"

    with runtime.RunLock(cfg, stale_after_seconds=60):
        timings = tts.synthesize(cfg, narration, voice_path)
        video.build_video(
            cfg,
            {"title": "Stability smoke test", "narration": narration, "scenes": scenes},
            voice_path,
            timings,
            video_path,
        )

    assert video_path.exists() and video_path.stat().st_size > 10_000
    assert not video_path.with_name("video.part.mp4").exists()
    assert not (cfg.cache_dir() / "pipeline.lock").exists()
    print(f"PASS: {video_path} ({video_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
