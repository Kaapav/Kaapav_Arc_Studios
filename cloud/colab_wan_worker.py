"""Run this file in a Google Colab GPU runtime.

The script asks for the local cloud_motion_job.zip, renders the requested
cutaway clips with Wan2.1 T2V-1.3B, then downloads cloud_motion_results.zip.
It intentionally does not read or upload .env, OAuth tokens, or YouTube data.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import zipfile

from google.colab import files  # type: ignore


def run() -> None:
    uploaded = files.upload()
    job_zip = next(iter(uploaded))
    job_root = Path("/content/job")
    shutil.rmtree(job_root, ignore_errors=True)
    job_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(job_zip) as zf:
        zf.extractall(job_root)
    manifest = json.loads((job_root / "manifest.json").read_text(encoding="utf-8"))
    print(f"Queued {len(manifest['tasks'])} motion scene(s)")

    subprocess.run(["git", "clone", "--depth", "1", "https://github.com/Wan-Video/Wan2.1.git", "/content/Wan2.1"], check=True)
    subprocess.run(["pip", "-q", "install", "-r", "/content/Wan2.1/requirements.txt"], check=True)
    subprocess.run(["pip", "-q", "install", "huggingface_hub"], check=True)
    subprocess.run([
        "huggingface-cli", "download", "Wan-AI/Wan2.1-T2V-1.3B",
        "--local-dir", "/content/Wan2.1-T2V-1.3B",
    ], check=True)

    results = Path("/content/results")
    results.mkdir(exist_ok=True)
    for task in manifest["tasks"]:
        output = results / f"{task['id']}.mp4"
        command = [
            "python", "/content/Wan2.1/generate.py",
            "--task", "t2v-1.3B", "--size", "832*480", "--frame_num", "81",
            "--ckpt_dir", "/content/Wan2.1-T2V-1.3B",
            "--offload_model", "True", "--t5_cpu",
            "--sample_shift", "8", "--sample_guide_scale", "6",
            "--save_file", str(output), "--prompt", task["prompt"],
        ]
        print(f"Rendering {task['id']}...")
        subprocess.run(command, check=True)

    result_zip = "/content/cloud_motion_results.zip"
    with zipfile.ZipFile(result_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in results.glob("scene_*.mp4"):
            zf.write(path, path.name)
    files.download(result_zip)


if __name__ == "__main__":
    run()
