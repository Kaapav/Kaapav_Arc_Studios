"""Build the self-contained private Episode 1 Kaggle notebook."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "kaggle_ep001.py"
OUTPUT = HERE / "midnight-platform-episode-1-wan-14b.ipynb"
MARKER = 'INPUT_IMAGES_B64 = "__EMBEDDED_BY_BUILDER__"'


def main() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    if source.count(MARKER) != 1:
        raise RuntimeError("Runner must contain exactly one image marker")
    encoded = []
    for index in range(1, 7):
        reference = HERE / "kaggle_refs" / f"shot_ref_{index:02d}.jpg"
        with Image.open(reference) as image:
            image = image.convert("RGB")
            compressed = io.BytesIO()
            image.save(compressed, format="JPEG", quality=62, optimize=True)
        encoded.append(base64.b64encode(compressed.getvalue()).decode("ascii"))
    source = source.replace(MARKER, f"INPUT_IMAGES_B64 = {encoded!r}")
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# KAAPAV ARC Studios — THE MIDNIGHT PLATFORM Episode 1\n",
                    "Private fail-closed Wan 2.1 I2V 14B render. Six native-motion clips; no tunnel and no YouTube upload.\n",
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
