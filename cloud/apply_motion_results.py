#!/usr/bin/env python3
"""Attach downloaded cloud clips to a local job and prepare a rerender."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("results_zip")
    ap.add_argument("--provider", default="colab-wan")
    args = ap.parse_args()
    job_dir = Path(args.job_dir).resolve()
    results_zip = Path(args.results_zip).resolve()
    script_path = job_dir / "script.json"
    if not script_path.exists() or not results_zip.exists():
        raise SystemExit("Need a valid job directory and downloaded results ZIP.")
    result_dir = job_dir / "cloud_motion" / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(results_zip) as zf:
        for info in zf.infolist():
            name = Path(info.filename)
            if name.name.lower().endswith(".mp4") and name.name.startswith("scene_"):
                target = result_dir / name.name
                with zf.open(info) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
    script = json.loads(script_path.read_text(encoding="utf-8"))
    attached = 0
    for scene_index, scene in enumerate(script.get("scenes", [])):
        clip = result_dir / f"scene_{scene_index + 1:02d}.mp4"
        if clip.exists():
            candidate = {
                "provider": args.provider,
                "path": clip.relative_to(ROOT).as_posix(),
            }
            existing = [item for item in scene.get("video_candidates", []) if not (
                isinstance(item, dict) and item.get("provider") == args.provider
            )]
            scene["video_candidates"] = [candidate] + existing
            attached += 1
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Attached {attached} cloud motion clip(s) to {script_path}")
    print("Rerender the same job with your normal local renderer; upload remains disabled until review.")


if __name__ == "__main__":
    main()
