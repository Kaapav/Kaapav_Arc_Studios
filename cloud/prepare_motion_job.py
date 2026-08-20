#!/usr/bin/env python3
"""Package a small, optional motion-render job for a free cloud GPU."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir", help="A rendered output/<timestamp-topic> directory")
    ap.add_argument("--max-scenes", type=int, default=2,
                    help="Maximum scenes to send to the free GPU (default: 2)")
    args = ap.parse_args()
    job_dir = Path(args.job_dir).resolve()
    script_path = job_dir / "script.json"
    if not script_path.exists():
        raise SystemExit(f"script.json not found in {job_dir}")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = script.get("scenes", [])
    marked = [s for s in scenes if s.get("cloud_motion") is True]
    selected = marked[:args.max_scenes] if marked else scenes[:args.max_scenes]
    package_dir = job_dir / "cloud_motion"
    refs_dir = package_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for scene_index, scene in enumerate(scenes):
        if scene not in selected:
            continue
        task_id = f"scene_{scene_index + 1:02d}"
        prompt = scene.get("motion_prompt") or (
            "cinematic short-form AI film insert, vertical-video safe composition, "
            + scene.get("text", "")
            + ", smooth deliberate camera movement, realistic lighting, no subtitles, "
              "no logos, no watermark, no extra text"
        )
        ref = scene.get("image_path")
        ref_name = None
        if ref:
            ref_path = Path(ref)
            if not ref_path.is_absolute():
                ref_path = ROOT / ref_path
            if ref_path.exists():
                ref_name = f"{task_id}{ref_path.suffix.lower() or '.png'}"
                shutil.copy2(ref_path, refs_dir / ref_name)
        tasks.append({
            "id": task_id,
            "scene_index": scene_index,
            "duration_seconds": 5,
            "prompt": prompt,
            "reference": f"references/{ref_name}" if ref_name else None,
            "output": f"results/{task_id}.mp4",
        })
    if not tasks:
        raise SystemExit("No scenes available for cloud motion generation.")
    manifest = {
        "version": 1,
        "channel": "AI Creative Explorer",
        "job_name": job_dir.name,
        "note": "T2V inserts are optional; local stills remain the fallback.",
        "tasks": tasks,
    }
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    archive = job_dir / "cloud_motion_job.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in package_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(package_dir).as_posix())
    print(f"Prepared {len(tasks)} cloud scene(s): {archive}")
    print("Upload this ZIP to cloud/colab_wan_worker.py in Google Colab, then download the results ZIP.")


if __name__ == "__main__":
    main()
