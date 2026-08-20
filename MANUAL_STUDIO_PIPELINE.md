# KAAPAV ARC Studios — Quota-Safe Manual Pipeline

This workflow covers all ten planned story series. It uses manual image generation plus the existing local narration, captions, motion, music, SFX, thumbnail and video renderer.

It does **not** call Kaggle, ComfyUI, Gemini, a paid image API, or YouTube upload.

## One-time setup

```powershell
.\.venv\Scripts\python.exe studio_manual_pipeline.py setup
```

## Create an episode package

```powershell
.\.venv\Scripts\python.exe studio_manual_pipeline.py new-episode echo30 10
```

Edit the created `episode.json`. Write exactly eight visual prompts and eight narration beats. Character turnaround sheets must be locked before story images.

## Export prompts for manual image generation

```powershell
.\.venv\Scripts\python.exe studio_manual_pipeline.py prompts PATH\TO\episode.json
```

The command creates `IMAGE_PROMPTS.md` beside the manifest.

## Import each downloaded image

```powershell
.\.venv\Scripts\python.exe studio_manual_pipeline.py import-image PATH\TO\episode.json 1 F:\Downloads\shot1.png
```

Add `--force` only when intentionally replacing an existing shot.

## Validate before spending render time

```powershell
.\.venv\Scripts\python.exe studio_manual_pipeline.py validate PATH\TO\episode.json --require-prompts
```

The gate checks metadata limits, narration density, missing or duplicated frames, source-image integrity, portrait orientation and scene effects.

## Render video and technical QC

```powershell
.\.venv\Scripts\python.exe studio_manual_pipeline.py render PATH\TO\episode.json
```

Output is written under `output\story\<output_slug>\` with:

- `video.mp4`
- `thumbnail.jpg`
- `metadata.json`
- `qc_contact.jpg`
- `qc_report.json`

The output remains local and is never uploaded by this script.

## Upload an approved video through the safe shortcut

Double-click `KAAPAV Upload Video.lnk` in the project folder. The uploader:

- lists only unuploaded packages with passing `qc_report.json`;
- verifies the OAuth channel is KAAPAV ARC Studios;
- permits only private or future scheduled uploads;
- requires the exact video title as confirmation;
- applies the local custom thumbnail;
- waits for successful YouTube processing;
- downloads YouTube's served thumbnail for verification;
- records `upload_result.json` to prevent duplicate uploads.

The uploader runs independently, so video uploading/processing can continue while another episode is being prepared.

## Check all ten series

```powershell
.\.venv\Scripts\python.exe studio_manual_pipeline.py status
```
