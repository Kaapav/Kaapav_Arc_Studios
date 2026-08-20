"""Create the minimal private Wan 2.2 Kaggle dataset with nested paths."""

from __future__ import annotations

import hashlib
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi


HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset"
EXPECTED = {
    "README_KAAPAV_WAN22.txt": 319,
    "diffusion_models/wan2.2_ti2v_5B_fp16.safetensors": 9_999_658_848,
    "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors": 6_735_906_897,
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


def validate() -> None:
    actual = {
        path.relative_to(DATASET).as_posix(): path.stat().st_size
        for path in DATASET.rglob("*")
        if path.is_file() and path.name != "dataset-metadata.json"
    }
    if actual != EXPECTED:
        raise RuntimeError(f"Wan 2.2 dataset manifest mismatch: {actual}")
    for name, expected_hash in EXPECTED_SHA256.items():
        actual_hash = sha256(DATASET / Path(name))
        if actual_hash != expected_hash:
            raise RuntimeError(f"SHA-256 mismatch for {name}: {actual_hash}")
    print(f"WAN22 DATASET VALID: {len(actual)} files, {sum(actual.values())} bytes", flush=True)


class RecursiveKaggleApi(KaggleApi):
    def upload_files(self, request, resources, folder, blob_type, upload_context, quiet=False, dir_mode="skip"):
        root = Path(folder)
        excluded = {
            self.DATASET_METADATA_FILE,
            self.OLD_DATASET_METADATA_FILE,
            self.KERNEL_METADATA_FILE,
            self.MODEL_METADATA_FILE,
            self.MODEL_INSTANCE_METADATA_FILE,
        }
        for path in sorted(path for path in root.rglob("*") if path.is_file() and path.name not in excluded):
            relative = path.relative_to(root).as_posix()
            uploaded = self._upload_file(relative, str(path), blob_type, upload_context, quiet, resources)
            if uploaded is not None and request.files is not None:
                request.files.append(self._new_file(uploaded))


def main() -> None:
    validate()
    api = RecursiveKaggleApi(enable_oauth=True)
    api.authenticate()
    response = api.dataset_create_new(str(DATASET), public=False, quiet=False)
    print(
        f"DATASET CREATE RESPONSE: status={response.status} url={response.url} error={response.error}",
        flush=True,
    )
    if str(response.status).lower() not in {"ok", "pending"} or response.error:
        raise RuntimeError(f"Kaggle dataset creation failed: {response.error or response.status}")


if __name__ == "__main__":
    main()
