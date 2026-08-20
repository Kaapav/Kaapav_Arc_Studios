"""Build the self-contained private Episode 1 Kaggle notebook."""

from __future__ import annotations

import base64
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "kaggle_episode1.py"
OUTPUT = HERE / "kaapav-echo100-episode1.ipynb"
MARKER = 'INPUT_IMAGES_B64 = "__EMBEDDED_BY_BUILDER__"'


def main() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    if source.count(MARKER) != 1:
        raise RuntimeError("Runner must contain exactly one image marker")
    encoded = [
        base64.b64encode((HERE / f"shot_ref_{index:02d}.jpg").read_bytes()).decode("ascii")
        for index in range(1, 9)
    ]
    source = source.replace(MARKER, f"INPUT_IMAGES_B64 = {encoded!r}")
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# KAAPAV ARC Studios — ECHO//100 Episode 1\n",
                    "Private fail-closed Wan 2.2 TI2V 5B render. Produces eight motion clips only; no tunnel and no YouTube upload.\n",
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
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUTPUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Built {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
