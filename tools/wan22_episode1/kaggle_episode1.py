"""Render ECHO//100 Episode 1 as eight real Wan 2.2 motion clips on Kaggle.

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
COMFY = WORK / "ComfyUI-echo100-episode1"
INPUT_DIR = WORK / "echo100_episode1_inputs"
FRAMES_ROOT = WORK / "echo100_episode1_frames"
FINAL_OUTPUT = WORK / "echo100_episode1_silent.mp4"
REPORT_PATH = WORK / "echo100_episode1_report.json"
COMFY_LOG = WORK / "comfy_echo100_episode1.log"

MODEL_FILES = {
    "diffusion_models": ("wan2.2_ti2v_5B_fp16.safetensors", 9_000_000_000),
    "text_encoders": ("umt5_xxl_fp8_e4m3fn_scaled.safetensors", 6_000_000_000),
    "vae": ("wan2.2_vae.safetensors", 1_000_000_000),
}

SHOTS = [
    {
        "seed": 817263,
        "prompt": "Macro-to-medium cinematic shot. Kavi remains in the same pose holding the phone steadily at chest height. The powerless phone suddenly ignites with a cyan waveform; Kavi makes one subtle blink and his eyes widen slightly while Byte turns toward the ring. Slow rack focus from phone to Kavi, subtle breathing and antenna motion.",
    },
    {
        "seed": 817264,
        "prompt": "Kavi keeps his body and hands steady as the phone's cyan light changes to warning red. His eyes glance toward Byte without a large head turn. Byte's cyan eyes dim nearly black and his hover stutters once. Deliberate slow push toward Byte; a red light sweep crosses the dark arcade.",
    },
    {
        "seed": 817265,
        "prompt": "Low-angle reaction shot. Kavi stays planted with his arms unchanged. Byte drops a few inches, recovers with one small mechanical jerk, and hovers back slightly. Kavi's frightened eyes track him. Gentle lateral camera drift, purposeful robot motion, tense red and blue arcade light.",
    },
    {
        "seed": 817266,
        "prompt": "Mira remains in position as her cyan hologram flickers and scan lines travel across her tablet. She makes a small controlled head turn toward Kavi. Kavi and Byte hold their poses while the camera drifts laterally to reveal the red doorway. Hologram particles and doorway light move coherently.",
    },
    {
        "seed": 817267,
        "prompt": "The characters keep stable poses while every arcade screen turns red in sequence. Null's two red eyes brighten inside black-purple digital static and the corrupted silhouette leans forward only slightly. Mira's hologram flickers and Byte lowers a little. Smooth controlled camera retreat and one restrained glitch pulse.",
    },
    {
        "seed": 817268,
        "prompt": "Kavi and Mira keep their bodies and hands stable while the impossible red door burns brighter. Byte floats a short distance toward it as if pulled by memory. Controlled dolly toward the doorway; red light ripples across the wet floor and Mira's hologram particles drift.",
    },
    {
        "seed": 817269,
        "prompt": "Present Kavi and Future Kavi preserve their exact poses and hands. Kavi's phone vibrates with a cyan pulse; the door opens slightly wider from the other side and warm golden light intensifies. Future Kavi's raised warning hand makes one small urgent motion. Gentle camera arc and floating sparks.",
    },
    {
        "seed": 817270,
        "prompt": "Both Kavis and Byte remain recognizably stable. Future Kavi holds his warning gesture while golden sparks accelerate. Behind present Kavi, Null advances one small controlled step and purple corruption spreads across the floor. Smooth accelerating camera pullback ending on Null's bright red eyes.",
    },
]
STYLE_PREFIX = (
    "Original premium stylized 3D animated science-fiction thriller, cinematic feature-animation quality, "
    "restrained motion, stable character identity, unchanged round glasses, unchanged face and costume, "
    "coherent anatomy, dramatic red cyan and golden lighting, blank screens with no writing. "
)
NEGATIVE_PROMPT = (
    "text anywhere, letters, numbers, symbols, signs, subtitles, watermark, logo, frozen frame, static image, "
    "slideshow, low quality, blurry face, large limb motion, deformed hands, extra fingers, fused fingers, "
    "duplicate person, duplicate robot, changing clothes, changing face, missing glasses, changing glasses, "
    "morphing, melting, warped body, extra limbs, wrong costume, wrong robot, random new character, "
    "uncontrolled camera shake, zoom distortion, dialogue, lip sync"
)

# Replaced mechanically by build_notebook.py. Never commit a user credential here.
INPUT_IMAGES_B64 = "__EMBEDDED_BY_BUILDER__"

REPORT: dict = {
    "version": 1,
    "production": "ECHO//100 Episode 1",
    "model_family": "Wan2.2-TI2V-5B",
    "status": "starting",
    "comfy_release": COMFY_RELEASE,
    "comfy_commit": COMFY_COMMIT,
    "settings": {
        "width": 480,
        "height": 832,
        "generated_frames_per_shot": 49,
        "used_frames_per_shot": 41,
        "shots": 8,
        "fps": 16,
        "steps": 20,
        "cfg": 5.0,
        "seeds": [shot["seed"] for shot in SHOTS],
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


def find_model_files() -> dict[str, Path]:
    resolved = {}
    input_root = Path("/kaggle/input")
    for folder, (filename, _minimum_bytes) in MODEL_FILES.items():
        matches = list(input_root.rglob(filename))
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected exactly one {filename} under /kaggle/input; "
                f"found {len(matches)}: {[str(path) for path in matches]}"
            )
        resolved[folder] = matches[0]
    return resolved


def validate_environment() -> tuple[dict[str, Path], str]:
    if not Path("/kaggle").exists():
        raise RuntimeError("This render must run inside Kaggle")
    gpu = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version",
            "--format=csv,noheader",
        ]
    ).strip()
    if "T4" not in gpu:
        raise RuntimeError(f"Episode render requires a Tesla T4 allocation; received: {gpu}")

    models = find_model_files()
    verified = {}
    for folder, (filename, minimum_bytes) in MODEL_FILES.items():
        path = models[folder]
        size = path.stat().st_size
        if size < minimum_bytes:
            raise RuntimeError(f"Model is incomplete: {path} ({size} bytes)")
        verified[folder] = {"path": str(path), "bytes": size}
    REPORT["gpu"] = gpu.splitlines()
    REPORT["models"] = verified
    atomic_json(REPORT_PATH, REPORT)
    return models, gpu


def prepare_comfy(models: dict[str, Path]) -> None:
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

    for folder, source in models.items():
        target = COMFY / "models" / folder
        target.mkdir(parents=True, exist_ok=True)
        link = target / source.name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(source)


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
        "LoadImage",
        "CLIPTextEncode",
        "Wan22ImageToVideoLatent",
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


def write_input_images() -> list[Path]:
    if INPUT_IMAGES_B64 == "__EMBEDDED_BY_BUILDER__":
        raise RuntimeError("Episode reference images were not embedded by build_notebook.py")
    if not isinstance(INPUT_IMAGES_B64, list) or len(INPUT_IMAGES_B64) != len(SHOTS):
        raise RuntimeError(f"Expected {len(SHOTS)} embedded references")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, encoded in enumerate(INPUT_IMAGES_B64, 1):
        path = INPUT_DIR / f"shot_ref_{index:02d}.jpg"
        path.write_bytes(base64.b64decode(encoded))
        from PIL import Image

        with Image.open(path) as image:
            dimensions = image.size
            image.verify()
        if dimensions != (480, 832) or path.stat().st_size < 40_000:
            raise RuntimeError(
                f"Embedded reference {index} failed validation: "
                f"dimensions={dimensions}, bytes={path.stat().st_size}"
            )
        paths.append(path)
    return paths


def upload_input(path: Path) -> str:
    import requests

    with path.open("rb") as handle:
        response = requests.post(
            f"{API}/upload/image",
            files={"image": (path.name, handle, "image/jpeg")},
            data={"overwrite": "true", "type": "input"},
            timeout=120,
        )
    response.raise_for_status()
    payload = response.json()
    return payload.get("name") or path.name


def workflow(image_name: str, shot: dict, shot_number: int) -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": MODEL_FILES["diffusion_models"][0],
                "weight_dtype": "fp8_e4m3fn_fast",
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
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": STYLE_PREFIX + shot["prompt"]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": NEGATIVE_PROMPT},
        },
        "7": {
            "class_type": "Wan22ImageToVideoLatent",
            "inputs": {
                "vae": ["3", 0],
                "start_image": ["4", 0],
                "width": 480,
                "height": 832,
                "length": 49,
                "batch_size": 1,
            },
        },
        "8": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["1", 0], "shift": 8.0},
        },
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["8", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
                "seed": shot["seed"],
                "steps": 20,
                "cfg": 5.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "10": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["9", 0], "vae": ["3", 0]},
        },
        "11": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["10", 0],
                "filename_prefix": f"echo100_ep001_shot_{shot_number:02d}/frame",
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
    if len(descriptors) < 49:
        raise RuntimeError(
            f"Expected 49 generated frames; found {len(descriptors)}: "
            f"{json.dumps(result)[:5000]}"
        )
    return descriptors


def download_frames(descriptors: list[dict], shot_number: int) -> tuple[Path, list[Path]]:
    import requests

    frames_dir = FRAMES_ROOT / f"shot_{shot_number:02d}"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
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
        path = frames_dir / f"frame_{index:05d}.png"
        path.write_bytes(response.content)
        if path.stat().st_size < 10_000:
            raise RuntimeError(f"Generated frame is implausibly small: {path} ({path.stat().st_size} bytes)")
        paths.append(path)
    return frames_dir, paths


def convert_and_validate(frames_dir: Path, frame_paths: list[Path], shot_number: int) -> dict:
    output_path = WORK / f"echo100_ep001_shot_{shot_number:02d}.mp4"
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
            str(frames_dir / "frame_%05d.png"),
            "-frames:v",
            "41",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "16",
            "-movflags",
            "+faststart",
            str(output_path),
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
            str(output_path),
        ]
    )
    payload = json.loads(probe)
    stream = payload["streams"][0]
    frames = int(stream.get("nb_read_frames") or 0)
    duration = float(payload["format"]["duration"])
    size = int(payload["format"]["size"])
    if stream["width"] != 480 or stream["height"] != 832:
        raise RuntimeError(f"Unexpected output size: {stream['width']}x{stream['height']}")
    if frames != 41 or not 2.4 <= duration <= 2.8 or size < 100_000:
        raise RuntimeError(f"Invalid output: frames={frames}, duration={duration}, bytes={size}")

    from PIL import Image, ImageChops, ImageStat

    first = Image.open(frame_paths[0]).convert("RGB")
    last = Image.open(frame_paths[40]).convert("RGB")
    difference = ImageChops.difference(first, last)
    motion_score = sum(ImageStat.Stat(difference).mean) / 3.0
    first.save(WORK / f"shot_{shot_number:02d}_first.jpg", quality=92)
    last.save(WORK / f"shot_{shot_number:02d}_last.jpg", quality=92)
    if len(frame_paths) < 49 or motion_score < 0.35:
        raise RuntimeError(
            f"Output lacks verified motion: frames={len(frame_paths)}, score={motion_score:.4f}"
        )

    return {
        "shot": shot_number,
        "path": str(output_path),
        "bytes": size,
        "frames": frames,
        "duration_seconds": duration,
        "width": stream["width"],
        "height": stream["height"],
        "motion_score": round(motion_score, 4),
    }


def concatenate_shots(outputs: list[dict]) -> None:
    concat_file = WORK / "episode1_concat.txt"
    concat_file.write_text(
        "".join(f"file '{Path(item['path']).as_posix()}'\n" for item in outputs),
        encoding="utf-8",
    )
    run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-an", "-c", "copy", "-movflags", "+faststart", str(FINAL_OUTPUT),
        ],
        timeout=600,
    )
    payload = json.loads(run([
        "ffprobe", "-v", "error", "-show_entries", "stream=width,height:format=duration,size",
        "-of", "json", str(FINAL_OUTPUT),
    ]))
    duration = float(payload["format"]["duration"])
    if not 20.0 <= duration <= 21.0:
        raise RuntimeError(f"Unexpected silent episode duration: {duration}")
    REPORT["silent_episode"] = {
        "path": str(FINAL_OUTPUT),
        "duration_seconds": duration,
        "bytes": int(payload["format"]["size"]),
        "width": int(payload["streams"][0]["width"]),
        "height": int(payload["streams"][0]["height"]),
    }


def record_gpu_after() -> None:
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
        input_paths = write_input_images()

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

        stage("generating_episode")
        outputs = []
        for shot_number, (path, shot) in enumerate(zip(input_paths, SHOTS), 1):
            print(f"\n--- SHOT {shot_number:02d}/08 ---", flush=True)
            REPORT["current_shot"] = shot_number
            atomic_json(REPORT_PATH, REPORT)
            image_name = upload_input(path)
            shot_started = time.monotonic()
            result = execute_workflow(workflow(image_name, shot, shot_number))
            descriptors = find_output_descriptors(result)
            frames_dir, frame_paths = download_frames(descriptors, shot_number)
            output = convert_and_validate(frames_dir, frame_paths, shot_number)
            output["generation_seconds"] = round(time.monotonic() - shot_started, 2)
            output["prompt"] = shot["prompt"]
            outputs.append(output)
            REPORT["shots"] = outputs
            atomic_json(REPORT_PATH, REPORT)
            shutil.rmtree(frames_dir)

        stage("assembling_silent_episode")
        concatenate_shots(outputs)
        record_gpu_after()

        REPORT["status"] = "passed"
        REPORT["total_seconds"] = round(time.monotonic() - overall_start, 2)
        atomic_json(REPORT_PATH, REPORT)
        print(f"\nEPISODE 1 MOTION RENDER PASSED: {FINAL_OUTPUT}", flush=True)
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
        if INPUT_DIR.exists():
            shutil.rmtree(INPUT_DIR, ignore_errors=True)
        if FRAMES_ROOT.exists():
            shutil.rmtree(FRAMES_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
