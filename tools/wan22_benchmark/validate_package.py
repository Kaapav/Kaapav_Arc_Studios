"""Static validation for the generated Kaggle benchmark package."""

from __future__ import annotations

import ast
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> None:
    runner = HERE / "kaggle_benchmark.py"
    notebook_path = HERE / "kaapav-wan22-benchmark.ipynb"
    metadata_path = HERE / "kernel-metadata.json"
    input_path = HERE / "benchmark_input.jpg"

    ast.parse(runner.read_text(encoding="utf-8"), filename=str(runner))
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    code = "".join(notebook["cells"][1]["source"])
    ast.parse(code, filename=str(notebook_path))

    failures = []
    if notebook["nbformat"] != 4 or len(notebook["cells"]) != 2:
        failures.append("unexpected notebook structure")
    if 'INPUT_IMAGE_B64 = "__EMBEDDED_BY_BUILDER__"' in code:
        failures.append("benchmark image marker was not replaced")
    if "cloudflared" in code.lower() or "comfy.kaapav.com" in code.lower():
        failures.append("benchmark must not expose a public tunnel")
    if "youtube" in code.lower():
        failures.append("benchmark must not contain YouTube integration")
    if "CF_TUNNEL_TOKEN" in code or "KAGGLE_API_TOKEN" in code:
        failures.append("benchmark contains a credential reference")
    if metadata.get("enable_gpu") is not True:
        failures.append("GPU is not enabled")
    if metadata.get("enable_internet") is not True:
        failures.append("internet is required to fetch pinned ComfyUI")
    if metadata.get("machine_shape") != "NvidiaTeslaT4":
        failures.append("benchmark is not pinned to Tesla T4")
    if metadata.get("dataset_sources") != ["kaapav/kaapav-wan22-models"]:
        failures.append("model dataset source is incorrect")
    if metadata.get("is_private") is not True:
        failures.append("benchmark kernel must remain private")
    if not input_path.exists() or input_path.stat().st_size < 20_000:
        failures.append("benchmark input is missing or implausibly small")
    if "Wan22ImageToVideoLatent" not in code or "wan2.2_ti2v_5B_fp16.safetensors" not in code:
        failures.append("Wan 2.2 5B native workflow is missing")
    if "WanImageToVideo" in code or "clip_vision_h.safetensors" in code:
        failures.append("Wan 2.1 workflow leaked into Wan 2.2 benchmark")

    if failures:
        raise RuntimeError("Package validation failed: " + "; ".join(failures))
    print("WAN 2.2 5B BENCHMARK PACKAGE VALID")


if __name__ == "__main__":
    main()
