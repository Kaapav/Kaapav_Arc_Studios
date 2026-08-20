"""Fail-closed Wan 2.1 I2V benchmark for a Kaggle T4 session.

This file is embedded into the generated Kaggle notebook by build_notebook.py.
It intentionally uses ComfyUI only on localhost and produces no public tunnel.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import urlencode


COMFY_RELEASE = "v0.26.0"
COMFY_COMMIT = "f6c162d"
API = "http://127.0.0.1:8188"
WORK = Path("/kaggle/working")
COMFY = WORK / "ComfyUI-wan-benchmark"
INPUT_IMAGE = WORK / "kaapav_wan_benchmark_input.jpg"
FRAMES_DIR = WORK / "wan_benchmark_frames"
FINAL_OUTPUT = WORK / "kaapav_wan_benchmark.mp4"
REPORT_PATH = WORK / "benchmark_report.json"
COMFY_LOG = WORK / "comfy_wan_benchmark.log"

MODEL_FILES = {
    "diffusion_models": ("wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors", 15_000_000_000),
    "text_encoders": ("umt5_xxl_fp8_e4m3fn_scaled.safetensors", 6_000_000_000),
    "vae": ("wan_2.1_vae.safetensors", 200_000_000),
    "clip_vision": ("clip_vision_h.safetensors", 1_000_000_000),
}

POSITIVE_PROMPT = (
    "Original cinematic stylized 3D animated science-fiction scene. Kavi slowly raises "
    "the glowing phone toward his face and his eyes widen with fear. Byte, the small round "
    "robot beside him, hovers gently and turns toward the red light. Subtle breathing and "
    "cloth motion, wet arcade reflections shimmer, slow cinematic camera push-in, coherent "
    "anatomy, stable face, stable clothing, stable robot design, dramatic red and blue lighting."
)
NEGATIVE_PROMPT = (
    "text, subtitles, watermark, logo, frozen frame, static image, low quality, blurry face, "
    "deformed hands, extra fingers, fused fingers, duplicate person, duplicate robot, changing "
    "clothes, changing face, changing glasses, morphing, melting, warped body, camera shake"
)

# Replaced mechanically by build_notebook.py. Never commit a user credential here.
INPUT_IMAGE_B64 = "__EMBEDDED_BY_BUILDER__"

REPORT: dict = {
    "version": 2,
    "status": "starting",
    "comfy_release": COMFY_RELEASE,
    "comfy_commit": COMFY_COMMIT,
    "settings": {
        "width": 512,
        "height": 512,
        "frames": 33,
        "fps": 16,
        "steps": 20,
        "cfg": 6.0,
        "seed": 817263,
    },
    "stages": [],
}


def atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def stage(name: str, **details) -> None:
    print(f"\n=== {name.upper()} ===", flush=True)
    REPORT["stages"].append({"name": name, "at": time.time(), **details})
    REPORT["status"] = name
    atomic_json(REPORT_PATH, REPORT)


def run(command: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> str:
    print("+", " ".join(str(part) for part in command), flush=True)
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if completed.stdout:
        print(completed.stdout[-4000:], flush=True)
    if completed.returncode:
        if completed.stderr:
            print(completed.stderr[-4000:], file=sys.stderr, flush=True)
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")
    return completed.stdout


def find_model_dataset() -> Path:
    preferred = [
        Path("/kaggle/input/datasets/kaapav/kaapav-models"),
        Path("/kaggle/input/kaapav-models"),
    ]
    for candidate in preferred:
        if candidate.exists():
            return candidate
    filename = MODEL_FILES["diffusion_models"][0]
    matches = list(Path("/kaggle/input").rglob(filename))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {filename} under /kaggle/input; found {len(matches)}")
    return matches[0].parent.parent


def validate_environment() -> tuple[Path, str]:
    if not Path("/kaggle").exists():
        raise RuntimeError("This benchmark must run inside Kaggle")
    gpu = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version",
            "--format=csv,noheader",
        ]
    ).strip()
    if "T4" not in gpu:
        raise RuntimeError(f"Benchmark requires a Tesla T4 allocation; received: {gpu}")

    models = find_model_dataset()
    verified = {}
    for folder, (filename, minimum_bytes) in MODEL_FILES.items():
        path = models / folder / filename
        if not path.exists():
            raise FileNotFoundError(f"Required model missing: {path}")
        size = path.stat().st_size
        if size < minimum_bytes:
            raise RuntimeError(f"Model is incomplete: {path} ({size} bytes)")
        verified[folder] = {"path": str(path), "bytes": size}
    REPORT["gpu"] = gpu.splitlines()
    REPORT["models"] = verified
    atomic_json(REPORT_PATH, REPORT)
    return models, gpu


def prepare_comfy(models: Path) -> None:
    if COMFY.exists():
        shutil.rmtree(COMFY)
    run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            COMFY_RELEASE,
            "https://github.com/Comfy-Org/ComfyUI.git",
            str(COMFY),
        ],
        timeout=300,
    )
    commit = run(["git", "rev-parse", "--short", "HEAD"], cwd=COMFY).strip()
    if not commit.startswith(COMFY_COMMIT):
        raise RuntimeError(f"Unexpected ComfyUI commit {commit}; expected {COMFY_COMMIT}")

    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "-r",
            str(COMFY / "requirements.txt"),
        ],
        timeout=900,
    )

    for folder in MODEL_FILES:
        source = models / folder
        target = COMFY / "models" / folder
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        target.symlink_to(source, target_is_directory=True)


def wait_for_api(process: subprocess.Popen, timeout_seconds: int = 360) -> None:
    import requests

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = COMFY_LOG.read_text(encoding="utf-8", errors="replace")[-8000:]
            raise RuntimeError(f"ComfyUI exited with {process.returncode}:\n{tail}")
        try:
            response = requests.get(f"{API}/system_stats", timeout=3)
            if response.ok:
                REPORT["system_stats"] = response.json()
                atomic_json(REPORT_PATH, REPORT)
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError("ComfyUI API did not become ready within six minutes")


def validate_nodes() -> None:
    import requests

    required = {
        "UNETLoader",
        "CLIPLoader",
        "VAELoader",
        "CLIPVisionLoader",
        "CLIPVisionEncode",
        "LoadImage",
        "CLIPTextEncode",
        "WanImageToVideo",
        "ModelSamplingSD3",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
    response = requests.get(f"{API}/object_info", timeout=30)
    response.raise_for_status()
    available = set(response.json())
    missing = sorted(required - available)
    if missing:
        raise RuntimeError(f"Required native ComfyUI nodes missing: {missing}")
    REPORT["required_nodes"] = sorted(required)
    atomic_json(REPORT_PATH, REPORT)


def write_input_image() -> None:
    if INPUT_IMAGE_B64 == "__EMBEDDED_BY_BUILDER__":
        raise RuntimeError("Benchmark image was not embedded by build_notebook.py")
    INPUT_IMAGE.write_bytes(base64.b64decode(INPUT_IMAGE_B64))
    if INPUT_IMAGE.stat().st_size < 20_000:
        raise RuntimeError("Embedded benchmark image is implausibly small")


def upload_input() -> str:
    import requests

    with INPUT_IMAGE.open("rb") as handle:
        response = requests.post(
            f"{API}/upload/image",
            files={"image": (INPUT_IMAGE.name, handle, "image/jpeg")},
            data={"overwrite": "true", "type": "input"},
            timeout=120,
        )
    response.raise_for_status()
    payload = response.json()
    return payload.get("name") or INPUT_IMAGE.name


def workflow(image_name: str) -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": MODEL_FILES["diffusion_models"][0],
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": MODEL_FILES["text_encoders"][0],
                "type": "wan",
                "device": "default",
            },
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": MODEL_FILES["vae"][0]},
        },
        "4": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": MODEL_FILES["clip_vision"][0]},
        },
        "5": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        "6": {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["4", 0], "image": ["5", 0], "crop": "none"},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": POSITIVE_PROMPT},
        },
        "8": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": NEGATIVE_PROMPT},
        },
        "9": {
            "class_type": "WanImageToVideo",
            "inputs": {
                "positive": ["7", 0],
                "negative": ["8", 0],
                "vae": ["3", 0],
                "clip_vision_output": ["6", 0],
                "start_image": ["5", 0],
                "width": 512,
                "height": 512,
                "length": 33,
                "batch_size": 1,
            },
        },
        "10": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["1", 0], "shift": 8.0},
        },
        "11": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["10", 0],
                "positive": ["9", 0],
                "negative": ["9", 1],
                "latent_image": ["9", 2],
                "seed": 817263,
                "steps": 20,
                "cfg": 6.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "12": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["11", 0], "vae": ["3", 0]},
        },
        "13": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["12", 0],
                "filename_prefix": "wan_benchmark/kaapav_wan",
            },
        },
    }


def execute_workflow(graph: dict, timeout_seconds: int = 10_800) -> dict:
    import requests

    client_id = str(uuid.uuid4())
    submitted = requests.post(
        f"{API}/prompt",
        json={"prompt": graph, "client_id": client_id},
        timeout=60,
    )
    if not submitted.ok:
        raise RuntimeError(f"Prompt rejected ({submitted.status_code}): {submitted.text[:4000]}")
    prompt_id = submitted.json()["prompt_id"]
    REPORT["prompt_id"] = prompt_id
    atomic_json(REPORT_PATH, REPORT)

    started = time.monotonic()
    last_report = 0.0
    while time.monotonic() - started < timeout_seconds:
        response = requests.get(f"{API}/history/{prompt_id}", timeout=30)
        response.raise_for_status()
        history = response.json()
        if prompt_id in history:
            result = history[prompt_id]
            status = result.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution failed: {json.dumps(status, ensure_ascii=False)[:6000]}")
            if status.get("completed"):
                REPORT["generation_seconds"] = round(time.monotonic() - started, 2)
                atomic_json(REPORT_PATH, REPORT)
                return result
        elapsed = time.monotonic() - started
        if elapsed - last_report >= 30:
            print(f"Generation running: {elapsed / 60:.1f} minutes", flush=True)
            last_report = elapsed
        time.sleep(5)
    raise TimeoutError("Wan generation exceeded three hours")


def find_output_descriptors(result: dict) -> list[dict]:
    descriptors = []
    for node_output in (result.get("outputs") or {}).values():
        for key in ("images", "gifs", "videos"):
            for item in node_output.get(key, []) or []:
                if isinstance(item, dict) and item.get("filename"):
                    descriptors.append(item)
    if len(descriptors) < 30:
        raise RuntimeError(
            f"Expected at least 30 generated frames; found {len(descriptors)}: "
            f"{json.dumps(result)[:5000]}"
        )
    return descriptors


def download_frames(descriptors: list[dict]) -> list[Path]:
    import requests

    if FRAMES_DIR.exists():
        shutil.rmtree(FRAMES_DIR)
    FRAMES_DIR.mkdir(parents=True)
    paths = []
    for index, descriptor in enumerate(descriptors):
        query = urlencode(
            {
                "filename": descriptor["filename"],
                "subfolder": descriptor.get("subfolder", ""),
                "type": descriptor.get("type", "output"),
            }
        )
        response = requests.get(f"{API}/view?{query}", timeout=300)
        response.raise_for_status()
        path = FRAMES_DIR / f"frame_{index:05d}.png"
        path.write_bytes(response.content)
        if path.stat().st_size < 10_000:
            raise RuntimeError(f"Generated frame is implausibly small: {path} ({path.stat().st_size} bytes)")
        paths.append(path)
    return paths


def convert_and_validate(frame_paths: list[Path]) -> None:
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "16",
            "-i",
            str(FRAMES_DIR / "frame_%05d.png"),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "16",
            "-movflags",
            "+faststart",
            str(FINAL_OUTPUT),
        ],
        timeout=600,
    )
    probe = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,nb_read_frames:format=duration,size",
            "-of",
            "json",
            str(FINAL_OUTPUT),
        ]
    )
    payload = json.loads(probe)
    stream = payload["streams"][0]
    frames = int(stream.get("nb_read_frames") or 0)
    duration = float(payload["format"]["duration"])
    size = int(payload["format"]["size"])
    if stream["width"] != 512 or stream["height"] != 512:
        raise RuntimeError(f"Unexpected output size: {stream['width']}x{stream['height']}")
    if frames < 30 or not 1.5 <= duration <= 3.0 or size < 100_000:
        raise RuntimeError(f"Invalid output: frames={frames}, duration={duration}, bytes={size}")

    from PIL import Image, ImageChops, ImageStat

    first = Image.open(frame_paths[0]).convert("RGB")
    last = Image.open(frame_paths[-1]).convert("RGB")
    difference = ImageChops.difference(first, last)
    motion_score = sum(ImageStat.Stat(difference).mean) / 3.0
    first.save(WORK / "benchmark_first.jpg", quality=92)
    last.save(WORK / "benchmark_last.jpg", quality=92)
    if len(frame_paths) < 30 or motion_score < 0.25:
        raise RuntimeError(
            f"Output lacks verified motion: frames={len(frame_paths)}, score={motion_score:.4f}"
        )

    REPORT["output"] = {
        "path": str(FINAL_OUTPUT),
        "bytes": size,
        "frames": frames,
        "duration_seconds": duration,
        "width": stream["width"],
        "height": stream["height"],
        "motion_score": round(motion_score, 4),
    }
    REPORT["gpu_after"] = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader",
        ]
    ).strip().splitlines()


def main() -> None:
    process = None
    log_handle = None
    overall_start = time.monotonic()
    try:
        stage("validating_environment")
        models, _gpu = validate_environment()
        write_input_image()

        stage("preparing_comfy")
        prepare_comfy(models)

        stage("starting_comfy")
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = "0"
        log_handle = COMFY_LOG.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                "main.py",
                "--listen",
                "127.0.0.1",
                "--port",
                "8188",
                "--lowvram",
            ],
            cwd=str(COMFY),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        wait_for_api(process)
        validate_nodes()

        stage("generating")
        image_name = upload_input()
        result = execute_workflow(workflow(image_name))

        stage("validating_output")
        descriptors = find_output_descriptors(result)
        REPORT["comfy_output"] = {
            "frame_count": len(descriptors),
            "first": descriptors[0],
            "last": descriptors[-1],
        }
        frame_paths = download_frames(descriptors)
        convert_and_validate(frame_paths)
        shutil.rmtree(FRAMES_DIR)

        REPORT["status"] = "passed"
        REPORT["total_seconds"] = round(time.monotonic() - overall_start, 2)
        atomic_json(REPORT_PATH, REPORT)
        print(f"\nBENCHMARK PASSED: {FINAL_OUTPUT}", flush=True)
    except Exception as exc:
        REPORT["status"] = "failed"
        REPORT["error"] = str(exc)
        REPORT["traceback"] = traceback.format_exc()[-12_000:]
        REPORT["total_seconds"] = round(time.monotonic() - overall_start, 2)
        if COMFY_LOG.exists():
            REPORT["comfy_log_tail"] = COMFY_LOG.read_text(
                encoding="utf-8", errors="replace"
            )[-12_000:]
        atomic_json(REPORT_PATH, REPORT)
        print(REPORT["traceback"], file=sys.stderr, flush=True)
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
        if log_handle:
            log_handle.close()
        # Kaggle snapshots all of /kaggle/working. The cloned runtime is reproducible
        # and should never inflate the benchmark output archive or hide diagnostics
        # behind API pagination.
        if COMFY.exists():
            shutil.rmtree(COMFY, ignore_errors=True)


if __name__ == "__main__":
    main()
