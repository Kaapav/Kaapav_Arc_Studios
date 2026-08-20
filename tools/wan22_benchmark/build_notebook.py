"""Build the self-contained Kaggle benchmark notebook deterministically."""

from __future__ import annotations

import base64
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "kaggle_benchmark.py"
INPUT = HERE / "benchmark_input.jpg"
OUTPUT = HERE / "kaapav-wan22-benchmark.ipynb"
MARKER = 'INPUT_IMAGE_B64 = "__EMBEDDED_BY_BUILDER__"'


def main() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    if source.count(MARKER) != 1:
        raise RuntimeError("Runner must contain exactly one image marker")
    encoded = base64.b64encode(INPUT.read_bytes()).decode("ascii")
    source = source.replace(MARKER, f"INPUT_IMAGE_B64 = {encoded!r}")
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# KAAPAV Wan 2.2 TI2V 5B benchmark\n",
                    "Fail-closed 49-frame I2V benchmark. No Cloudflare tunnel and no YouTube upload.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [line + "\n" for line in source.splitlines()],
            },
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUTPUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Built {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
