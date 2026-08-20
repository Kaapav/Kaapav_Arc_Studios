"""Static fail-closed validation for the private Episode 1 render package."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from PIL import Image


HERE = Path(__file__).resolve().parent


def main() -> None:
    runner = HERE / "kaggle_episode1.py"
    notebook_path = HERE / "kaapav-echo100-episode1.ipynb"
    metadata = json.loads((HERE / "kernel-metadata.json").read_text(encoding="utf-8"))
    ast.parse(runner.read_text(encoding="utf-8"), filename=str(runner))
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "".join(notebook["cells"][1]["source"])
    ast.parse(code, filename=str(notebook_path))

    failures = []
    if 'INPUT_IMAGES_B64 = "__EMBEDDED_BY_BUILDER__"' in code:
        failures.append("reference image marker was not replaced")
    if "cloudflared" in code.lower() or "comfy.kaapav.com" in code.lower():
        failures.append("render must not expose a public tunnel")
    if "youtube" in code.lower():
        failures.append("render must not contain YouTube integration")
    if metadata.get("is_private") is not True or metadata.get("enable_gpu") is not True:
        failures.append("kernel is not private with GPU enabled")
    if metadata.get("dataset_sources") != ["kaapav/kaapav-wan22-models"]:
        failures.append("model dataset source is incorrect")
    if "for shot_number" not in code or "zip(input_paths, SHOTS)" not in code:
        failures.append("eight-shot loop is missing")
    for token in ("Wan22ImageToVideoLatent", '"width": 480', '"height": 832', '"length": 49', '"41"'):
        if token not in code:
            failures.append(f"required render setting missing: {token}")
    if "ken_burns" in code.lower() or "stock_video" in code.lower():
        failures.append("slideshow or stock fallback leaked into motion renderer")
    references = list(HERE.glob("shot_ref_*.jpg"))
    if len(references) != 8:
        failures.append("exactly eight shot references are required")
    for reference in references:
        with Image.open(reference) as image:
            if image.size != (480, 832):
                failures.append(f"invalid reference dimensions: {reference.name}={image.size}")
            image.verify()

    if failures:
        raise RuntimeError("Package validation failed: " + "; ".join(failures))
    print("ECHO//100 EPISODE 1 WAN 2.2 PACKAGE VALID")


if __name__ == "__main__":
    main()
