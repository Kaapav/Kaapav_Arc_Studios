# KAAPAV Wan 2.1 I2V benchmark

Purpose: prove the existing Wan 2.1 I2V model stack on a Kaggle Tesla T4 before
connecting it to the production YouTube pipeline.

The benchmark is deliberately isolated:

- one existing ECHO image is embedded in the private notebook;
- ComfyUI is pinned to release `v0.26.0` / commit `f6c162d`;
- ComfyUI listens only on `127.0.0.1`;
- no Cloudflare tunnel is started;
- no YouTube code is imported or called;
- all four Wan components are size-validated before inference;
- the native ComfyUI Wan workflow produces 33 frames at 512x512;
- the animated WebP is converted to H.264 MP4 and motion-checked;
- failure writes `benchmark_report.json` and stops publication work.

Expected Kaggle outputs:

- `kaapav_wan_benchmark.mp4`
- `kaapav_wan_benchmark.webp`
- `benchmark_first.jpg`
- `benchmark_last.jpg`
- `benchmark_report.json`
- `comfy_wan_benchmark.log`

Local package validation:

```powershell
.\.venv\Scripts\python.exe tools\wan_benchmark\build_notebook.py
.\.venv\Scripts\python.exe tools\wan_benchmark\validate_package.py
```

One-click submission after Kaggle CLI authentication:

```powershell
.\tools\wan_benchmark\run_wan_benchmark.ps1
```
