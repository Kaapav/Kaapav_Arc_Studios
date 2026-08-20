"""Long-running private Kaggle ComfyUI server for KAAPAV ARC Studios."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path


COMFY_RELEASE = "v0.26.0"
COMFY_COMMIT = "f6c162d"
WORK = Path("/kaggle/working")
COMFY = WORK / "ComfyUI-kaapav"
COMFY_LOG = WORK / "kaapav_comfy.log"
TUNNEL_LOG = WORK / "kaapav_tunnel.log"
REPORT = WORK / "kaapav_comfy_status.json"
DOMAIN = "https://comfy.kaapav.com"

MODEL_FILES = {
    "diffusion_models": "wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors",
    "text_encoders": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
    "clip_vision": "clip_vision_h.safetensors",
}


def write_report(status: str, **extra) -> None:
    payload = {
        "status": status,
        "domain": DOMAIN,
        "comfy_release": COMFY_RELEASE,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **extra,
    }
    temp = REPORT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(REPORT)


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
        print(completed.stdout[-3000:], flush=True)
    if completed.returncode:
        if completed.stderr:
            print(completed.stderr[-3000:], file=sys.stderr, flush=True)
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")
    return completed.stdout


def find_models() -> dict[str, Path]:
    """Resolve every required file instead of assuming Kaggle keeps folders.

    Kaggle flattens this private dataset during version upload, so a local
    `diffusion_models/foo.safetensors` becomes `/kaggle/input/.../foo.safetensors`.
    Matching exact filenames keeps the launcher valid for either layout.
    """
    roots = [
        candidate
        for candidate in (
            Path("/kaggle/input/datasets/kaapav/kaapav-models"),
            Path("/kaggle/input/kaapav-models"),
            Path("/kaggle/input"),
        )
        if candidate.exists()
    ]
    resolved: dict[str, Path] = {}
    for folder, filename in MODEL_FILES.items():
        matches: list[Path] = []
        for root in roots:
            matches.extend(path for path in root.rglob(filename) if path.is_file())
        unique = sorted({path.resolve() for path in matches})
        if len(unique) != 1:
            raise RuntimeError(
                f"Expected exactly one {filename} in Kaggle inputs; found {len(unique)}: {unique}"
            )
        resolved[folder] = unique[0]
    return resolved


def find_cloudflared() -> Path:
    matches = [
        path
        for path in Path("/kaggle/input").rglob("cloudflared")
        if path.is_file() and path.stat().st_size > 10_000_000
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one cloudflared binary from kaapav-comfy; found {len(matches)}")
    target = WORK / "cloudflared"
    shutil.copy2(matches[0], target)
    target.chmod(0o755)
    return target


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
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(COMFY / "requirements.txt")],
        timeout=900,
    )
    for folder, filename in MODEL_FILES.items():
        expected = models[folder]
        if expected.name != filename or not expected.exists():
            raise FileNotFoundError(f"Required model missing: {expected}")
        target = COMFY / "models" / folder
        if target.exists() or target.is_symlink():
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        (target / filename).symlink_to(expected)


def wait_local(process: subprocess.Popen, timeout_seconds: int = 360) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = COMFY_LOG.read_text(encoding="utf-8", errors="replace")[-8000:]
            raise RuntimeError(f"ComfyUI exited with {process.returncode}:\n{tail}")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise TimeoutError("ComfyUI did not become healthy within six minutes")


def wait_tunnel(process: subprocess.Popen, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = TUNNEL_LOG.read_text(encoding="utf-8", errors="replace")[-8000:]
            raise RuntimeError(f"Cloudflare tunnel exited with {process.returncode}:\n{tail}")
        try:
            request = urllib.request.Request(f"{DOMAIN}/system_stats", headers={"User-Agent": "KAAPAV-Healthcheck/1.0"})
            with urllib.request.urlopen(request, timeout=8) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(3)
    tail = TUNNEL_LOG.read_text(encoding="utf-8", errors="replace")[-8000:]
    raise TimeoutError(f"Named tunnel did not become healthy within three minutes:\n{tail}")


def main() -> None:
    comfy_process = None
    tunnel_process = None
    comfy_handle = None
    tunnel_handle = None
    try:
        write_report("starting")
        if not Path("/kaggle").exists():
            raise RuntimeError("This launcher must run inside Kaggle")
        gpu = run(["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader"]).strip()
        if "T4" not in gpu:
            raise RuntimeError(f"Tesla T4 allocation required; received: {gpu}")
        models = find_models()
        cloudflared = find_cloudflared()
        prepare_comfy(models)

        from kaggle_secrets import UserSecretsClient

        token = UserSecretsClient().get_secret("CF_TUNNEL_TOKEN").strip()
        if not token:
            raise RuntimeError("Kaggle secret CF_TUNNEL_TOKEN is unavailable")

        comfy_handle = COMFY_LOG.open("w", encoding="utf-8")
        comfy_process = subprocess.Popen(
            [sys.executable, "main.py", "--listen", "0.0.0.0", "--port", "8188", "--lowvram"],
            cwd=str(COMFY),
            stdout=comfy_handle,
            stderr=subprocess.STDOUT,
        )
        wait_local(comfy_process)

        tunnel_handle = TUNNEL_LOG.open("w", encoding="utf-8")
        tunnel_process = subprocess.Popen(
            [str(cloudflared), "tunnel", "--no-autoupdate", "run", "--token", token],
            stdout=tunnel_handle,
            stderr=subprocess.STDOUT,
        )
        wait_tunnel(tunnel_process)
        write_report("ready", gpu=gpu.splitlines())
        print(f"KAAPAV COMFYUI READY: {DOMAIN}", flush=True)

        # Keep the batch session alive. Kaggle enforces the final session limit.
        started = time.monotonic()
        while time.monotonic() - started < 10 * 60 * 60:
            if comfy_process.poll() is not None:
                raise RuntimeError(f"ComfyUI exited unexpectedly with {comfy_process.returncode}")
            if tunnel_process.poll() is not None:
                raise RuntimeError(f"Cloudflare tunnel exited unexpectedly with {tunnel_process.returncode}")
            time.sleep(30)
        write_report("session_limit_reached")
    except Exception as exc:
        write_report("failed", error=str(exc), traceback=traceback.format_exc()[-12000:])
        raise
    finally:
        for process in (tunnel_process, comfy_process):
            if process and process.poll() is None:
                process.terminate()
        for handle in (tunnel_handle, comfy_handle):
            if handle:
                handle.close()


if __name__ == "__main__":
    main()
