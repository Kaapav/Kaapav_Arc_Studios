"""Render THE MIDNIGHT PLATFORM Episode 1 through the private ComfyUI API.

The workflow is deliberately fail-closed: one native Wan I2V generation per
shot, no looping, no temporal stretching, deterministic seeds, resumable local
downloads, and a report beside the episode assets.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

import requests


STORY_ROOT = Path(__file__).resolve().parents[1]
EPISODE_ROOT = STORY_ROOT / "episodes" / "ep001"
EPISODE_PATH = EPISODE_ROOT / "episode.json"
MOTION_ROOT = EPISODE_ROOT / "motion"
REPORT_PATH = EPISODE_ROOT / "qc" / "motion_generation_report.json"
API = "https://comfy.kaapav.com"

MODEL_FILES = {
    "diffusion": "wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors",
    "text_encoder": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
    "clip_vision": "clip_vision_h.safetensors",
}

WIDTH = 480
HEIGHT = 832
GENERATED_FRAMES = 81
GENERATED_FPS = 16
DELIVERY_FPS = 24

STYLE_PREFIX = (
    "Original premium cinematic stylized 3D feature-animation shot. "
    "Purposeful character acting, physically coherent movement, stable identity, "
    "believable weight, wet midnight railway atmosphere, detailed fabric, brass, "
    "glass and enamel, restrained camera movement, professional lighting. "
)

NEGATIVE = (
    "text, letters, words, captions, subtitles, logo, watermark, signature, pseudo-text, "
    "identity drift, face change, age change, costume change, duplicate character, extra person, "
    "extra fingers, missing fingers, fused fingers, deformed hands, broken anatomy, merged bodies, "
    "melted face, asymmetrical eyes, morphing, jitter, flicker, teleportation, frame tearing, "
    "static frozen pose, camera-only motion, excessive camera shake, rubber limbs, foot sliding, "
    "plastic skin, flat illustration, photorealistic live action, low detail, blur, compression artifacts"
)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def health() -> dict:
    response = requests.get(f"{API}/system_stats", timeout=30)
    response.raise_for_status()
    return response.json()


def upload_image(path: Path) -> str:
    with path.open("rb") as handle:
        response = requests.post(
            f"{API}/upload/image",
            files={"image": (path.name, handle, "image/png")},
            data={"overwrite": "true", "type": "input"},
            timeout=180,
        )
    response.raise_for_status()
    payload = response.json()
    return payload.get("name") or path.name


def workflow(image_name: str, prompt: str, seed: int, prefix: str) -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": MODEL_FILES["diffusion"], "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": MODEL_FILES["text_encoder"], "type": "wan", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": MODEL_FILES["vae"]}},
        "4": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": MODEL_FILES["clip_vision"]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["4", 0], "image": ["5", 0], "crop": "none"},
        },
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": STYLE_PREFIX + prompt}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEGATIVE}},
        "9": {
            "class_type": "WanImageToVideo",
            "inputs": {
                "positive": ["7", 0],
                "negative": ["8", 0],
                "vae": ["3", 0],
                "clip_vision_output": ["6", 0],
                "start_image": ["5", 0],
                "width": WIDTH,
                "height": HEIGHT,
                "length": GENERATED_FRAMES,
                "batch_size": 1,
            },
        },
        "10": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "11": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["10", 0],
                "positive": ["9", 0],
                "negative": ["9", 1],
                "latent_image": ["9", 2],
                "seed": seed,
                "steps": 24,
                "cfg": 6.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {
            "class_type": "SaveAnimatedWEBP",
            "inputs": {
                "images": ["12", 0],
                "filename_prefix": prefix,
                "fps": float(GENERATED_FPS),
                "lossless": False,
                "quality": 90,
                "method": "default",
            },
        },
    }


def execute(graph: dict, timeout_seconds: int = 7200) -> tuple[str, dict, float]:
    client_id = str(uuid.uuid4())
    response = requests.post(
        f"{API}/prompt", json={"prompt": graph, "client_id": client_id}, timeout=90
    )
    if not response.ok:
        raise RuntimeError(f"Prompt rejected ({response.status_code}): {response.text[:5000]}")
    prompt_id = response.json()["prompt_id"]
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        history_response = requests.get(f"{API}/history/{prompt_id}", timeout=30)
        history_response.raise_for_status()
        history = history_response.json()
        if prompt_id in history:
            result = history[prompt_id]
            status = result.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False)[:8000])
            if status.get("completed"):
                return prompt_id, result, time.monotonic() - started
        time.sleep(10)
    raise TimeoutError(f"ComfyUI generation timed out after {timeout_seconds}s: {prompt_id}")


def output_files(result: dict) -> list[dict]:
    found: list[dict] = []
    for node in (result.get("outputs") or {}).values():
        for value in node.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and item.get("filename"):
                    found.append(item)
    if not found:
        raise RuntimeError("ComfyUI completed but returned no downloadable output")
    return found


def download(item: dict, destination: Path) -> None:
    response = requests.get(
        f"{API}/view",
        params={
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        },
        timeout=300,
    )
    response.raise_for_status()
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.write_bytes(response.content)
    if temp.stat().st_size < 100_000:
        raise RuntimeError(f"Downloaded output is implausibly small: {temp.stat().st_size}")
    temp.replace(destination)


def convert_webp(source: Path, destination: Path) -> None:
    temp = destination.with_suffix(".part.mp4")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vf", (
            f"minterpolate=fps={DELIVERY_FPS}:mi_mode=mci:mc_mode=aobmc:"
            "me_mode=bidir:vsbmc=1,format=yuv420p"
        ),
        "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-movflags", "+faststart", str(temp),
    ]
    subprocess.run(command, check=True)
    if temp.stat().st_size < 500_000:
        raise RuntimeError(f"Converted clip is implausibly small: {temp.stat().st_size}")
    temp.replace(destination)


def probe(path: Path) -> dict:
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,nb_frames:format=duration,size",
        "-of", "json", str(path),
    ]
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="regenerate clips that already exist")
    args = parser.parse_args()

    episode = json.loads(EPISODE_PATH.read_text(encoding="utf-8"))
    MOTION_ROOT.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "status": "running",
        "api": API,
        "model": MODEL_FILES["diffusion"],
        "generated_resolution": [WIDTH, HEIGHT],
        "generated_frames": GENERATED_FRAMES,
        "generated_fps": GENERATED_FPS,
        "delivery_fps": DELIVERY_FPS,
        "temporal_policy": {"looped": False, "stretched": False, "interpolated_to_delivery_fps": True},
        "health": health(),
        "shots": [],
    }
    atomic_json(REPORT_PATH, report)

    for index, shot in enumerate(episode["shots"], 1):
        shot_id = shot["id"]
        final_path = MOTION_ROOT / f"{shot_id}.mp4"
        webp_path = MOTION_ROOT / f"{shot_id}.webp"
        if final_path.exists() and not args.force:
            report["shots"].append({"id": shot_id, "status": "reused", "video": str(final_path), "probe": probe(final_path)})
            atomic_json(REPORT_PATH, report)
            continue

        image_path = EPISODE_ROOT / shot["image"]
        if not image_path.exists():
            raise FileNotFoundError(image_path)
        image_name = upload_image(image_path)
        seed = 8675300 + index * 1009
        graph = workflow(image_name, shot["motion_prompt"], seed, f"midnight_platform/ep001/{shot_id}")
        prompt_id, result, elapsed = execute(graph)
        files = output_files(result)
        webp = next((item for item in files if str(item["filename"]).lower().endswith(".webp")), None)
        if webp is None:
            raise RuntimeError(f"Expected animated WEBP output for {shot_id}; received {files}")
        download(webp, webp_path)
        convert_webp(webp_path, final_path)
        entry = {
            "id": shot_id,
            "status": "generated",
            "seed": seed,
            "prompt_id": prompt_id,
            "generation_seconds": round(elapsed, 2),
            "image": str(image_path),
            "source_webp": str(webp_path),
            "video": str(final_path),
            "probe": probe(final_path),
        }
        report["shots"].append(entry)
        atomic_json(REPORT_PATH, report)
        print(json.dumps({"completed": shot_id, "seconds": round(elapsed, 2)}, ensure_ascii=False), flush=True)

    report["status"] = "complete"
    report["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    atomic_json(REPORT_PATH, report)
    print(REPORT_PATH)


if __name__ == "__main__":
    main()
