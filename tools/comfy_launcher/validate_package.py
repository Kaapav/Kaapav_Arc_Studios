from __future__ import annotations

import ast
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> None:
    runner = HERE / "kaggle_comfy_server.py"
    notebook_path = HERE / "kaapav-comfy-launcher.ipynb"
    metadata_path = HERE / "kernel-metadata.json"
    launcher = HERE / "Launch-KAAPAV-Comfy.ps1"
    ast.parse(runner.read_text(encoding="utf-8"), filename=str(runner))
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    ast.parse("".join(notebook["cells"][1]["source"]), filename=str(notebook_path))

    failures = []
    if metadata.get("is_private") is not True:
        failures.append("kernel must be private")
    if metadata.get("enable_gpu") is not True or metadata.get("machine_shape") != "NvidiaTeslaT4":
        failures.append("kernel must use Tesla T4")
    if metadata.get("dataset_sources") != ["kaapav/kaapav-models"]:
        failures.append("wrong model dataset")
    if metadata.get("kernel_sources") != ["kaapav/kaapav-comfy"]:
        failures.append("cloudflared source is missing")
    source = runner.read_text(encoding="utf-8")
    if "CF_TUNNEL_TOKEN" not in source or "get_secret" not in source:
        failures.append("Kaggle secret lookup is missing")
    if "--token" not in source:
        failures.append("named tunnel invocation is missing")
    if "10 * 60 * 60" not in source:
        failures.append("server keepalive is missing")
    if "comfy.kaapav.com" not in launcher.read_text(encoding="utf-8"):
        failures.append("local launcher domain is incorrect")
    if failures:
        raise RuntimeError("Launcher validation failed: " + "; ".join(failures))
    print("KAAPAV COMFY LAUNCHER PACKAGE VALID")


if __name__ == "__main__":
    main()
