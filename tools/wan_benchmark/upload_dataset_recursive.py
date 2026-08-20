"""Create a Kaggle dataset version while preserving nested model paths.

The stock Kaggle CLI skips directories unless it archives them. ComfyUI needs
real paths such as diffusion_models/model.safetensors, so this uploader walks
the staging tree and sends POSIX relative names through Kaggle's official API.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi


EXPECTED = {
    "README_KAAPAV_MODELS.txt": 574,
    "checkpoints/cyberrealisticXL_v80.safetensors": 6_938_040_866,
    "clip_vision/clip_vision_h.safetensors": 1_264_219_396,
    "diffusion_models/wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors": 16_397_245_448,
    "diffusion_models/wan2.2_ti2v_5B_fp16.safetensors": 9_999_658_848,
    "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors": 6_735_906_897,
    "vae/wan_2.1_vae.safetensors": 253_815_318,
    "vae/wan2.2_vae.safetensors": 1_409_400_960,
}

EXPECTED_SHA256 = {
    "diffusion_models/wan2.2_ti2v_5B_fp16.safetensors": "456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e",
    "vae/wan2.2_vae.safetensors": "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(folder: Path) -> None:
    actual = {
        path.relative_to(folder).as_posix(): path.stat().st_size
        for path in folder.rglob("*")
        if path.is_file() and path.name != "dataset-metadata.json"
    }
    if actual != EXPECTED:
        missing = sorted(set(EXPECTED) - set(actual))
        extra = sorted(set(actual) - set(EXPECTED))
        wrong = sorted(name for name in set(actual) & set(EXPECTED) if actual[name] != EXPECTED[name])
        raise RuntimeError(f"Dataset staging mismatch: missing={missing}, extra={extra}, wrong_sizes={wrong}")
    for name, expected in EXPECTED_SHA256.items():
        actual_hash = sha256(folder / Path(name))
        if actual_hash != expected:
            raise RuntimeError(f"SHA-256 mismatch for {name}: {actual_hash}")
    print(f"STAGING VALID: {len(actual)} files, {sum(actual.values())} bytes", flush=True)


class RecursiveKaggleApi(KaggleApi):
    def upload_files(self, request, resources, folder, blob_type, upload_context, quiet=False, dir_mode="skip"):
        root = Path(folder)
        paths = sorted(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.name
            not in {
                self.DATASET_METADATA_FILE,
                self.OLD_DATASET_METADATA_FILE,
                self.KERNEL_METADATA_FILE,
                self.MODEL_METADATA_FILE,
                self.MODEL_INSTANCE_METADATA_FILE,
            }
        )
        for path in paths:
            relative = path.relative_to(root).as_posix()
            uploaded = self._upload_file(
                relative,
                str(path),
                blob_type,
                upload_context,
                quiet,
                resources,
            )
            if uploaded is not None and request.files is not None:
                request.files.append(self._new_file(uploaded))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    folder = args.folder.resolve()
    validate(folder)
    # Match the working Kaggle CLI authentication path. A bare KaggleApi()
    # instance defaults to legacy credentials even when OAuth is configured.
    api = RecursiveKaggleApi(enable_oauth=True)
    api.authenticate()
    response = api.dataset_create_version(str(folder), args.message, quiet=False)
    print(f"DATASET VERSION RESPONSE: status={response.status} url={response.url} error={response.error}")
    if str(response.status).lower() not in {"ok", "pending"} or response.error:
        raise RuntimeError(f"Kaggle dataset version failed: {response.error or response.status}")


if __name__ == "__main__":
    main()
