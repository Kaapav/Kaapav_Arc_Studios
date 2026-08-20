# AI Creative Explorer - Failure-Tolerant Production Design

Verified: 2026-08-02

## The core rule

Free hosted AI is never the foundation. It is an accelerator. The guaranteed
foundation is prepared episode data, protected story images, offline narration,
CPU rendering, local history, and private review.

Every external clip is optional. Every scene must retain a valid local image.
Missing services reduce motion quality but never create random filler, stock
footage, duplicate uploads, or wrong-channel uploads.

## Production fallback ladder

| Stage | Ordered choices | Guaranteed final state |
|---|---|---|
| Story | READY canonical episode | Clean no-op when no episode is ready |
| Script assistance | Gemini -> Groq -> prepared human-reviewed draft | Scheduled rendering never depends on an LLM |
| Motion | Meta AI -> Kaggle Wan/CogVideo -> Colab Wan -> Hugging Face ZeroGPU -> local image motion | Protected story image with camera motion |
| Voice | Piper offline -> Windows SAPI | Hold episode if both local voices fail |
| Render | MoviePy/FFmpeg atomic CPU render | Existing output is never overwritten by a partial file |
| Upload | Channel identity gate -> resumable retry -> local review queue | Episode remains local/private; no duplicate or wrong-channel upload |
| Metrics | YouTube Data API -> local current CSV -> local daily history -> Google Sheets mirror | Last good local history remains available |

## Visual options: honest ranking

### 1. Meta AI / Vibes

Use it for the best hero shots and character moments. It is a manual production
accelerator because no stable, documented India video-generation API is available.
Do not automate the consumer website or bypass limits.

Meta has been generous enough for current creative testing, so it is now tracked
as priority 1 in the Google Sheet `Fallback Matrix`. Treat that generosity as a
variable product allowance, not a lifetime quota or automation SLA. The daily
job therefore never waits for Meta: missing Meta clips fall through to the next
candidate and finally to local image motion.

Official source: https://about.fb.com/news/2025/09/introducing-vibes-ai-videos/

Attach a downloaded clip:

```powershell
.\.venv\Scripts\python.exe tools\ingest_motion.py `
  content\echo100\episodes\ep002.json 1 meta C:\Downloads\scene-01.mp4
```

### 2. Kaggle GPU

Best repeatable free GPU lane. Kaggle documents a weekly GPU quota of around 30
hours or sometimes more depending on demand. It is still a quota, not an SLA.
Use open models only for one or two motion shots per episode.

Official source: https://www.kaggle.com/docs/efficient-gpu-usage

### 3. Google Colab

Useful backup for the included Wan worker. Google explicitly says free GPU
resources are not guaranteed and limits fluctuate. Keep it outside the daily
critical path.

Official source: https://research.google.com/colaboratory/faq.html

### 4. Hugging Face ZeroGPU

Useful emergency/demo lane. Free accounts currently receive five minutes of
daily ZeroGPU quota, with shared queues and compatibility limits. Never depend
on a public community Space as the sole renderer.

Official source: https://huggingface.co/docs/hub/main/en/spaces-zerogpu

### 5. Local image motion

This is the zero-cost permanent floor: custom image, crop, pan, zoom, captions,
voice and sound design. It works without hosted APIs, GPU, credits or login.

## Open model choices

- Wan2.1: Apache 2.0; official repository supports video tasks. The small T2V
  model still needs about 8.19 GB GPU memory, so use free cloud GPU only.
  https://github.com/Wan-Video/Wan2.1
- CogVideoX-2B: model and code are Apache 2.0. The larger 5B family uses a
  different model license, so verify before monetized use.
  https://github.com/zai-org/CogVideo
- HunyuanVideo: high quality but the original model documents roughly 45-60 GB
  GPU requirements. It is not a dependable free-tier default.
  https://github.com/Tencent-Hunyuan/HunyuanVideo
- LTX variants: licensing and hosted pricing vary by release. Do not make them
  a default until the exact model license is reviewed for commercial YouTube use.

## Ordered motion candidates

Each episode scene can contain:

```json
{
  "image_path": "assets/story/echo100/scene.png",
  "video_candidates": [
    {"provider": "meta", "path": "assets/motion/echo100/ep002/meta/scene-01.mp4"},
    {"provider": "kaggle-wan", "path": "assets/motion/echo100/ep002/kaggle-wan/scene-01.mp4"},
    {"provider": "colab-wan", "path": "assets/motion/echo100/ep002/colab-wan/scene-01.mp4"}
  ]
}
```

The renderer tries candidates in order. Missing or corrupt clips are recorded in
`visual_sources.json`; the local image then renders automatically.

## Performance tracker

Daily local source of truth:

- `analytics/current.csv`: latest views, likes, comments and rates.
- `analytics/daily_snapshots.csv`: one deduplicated observation per video/day.
- `analytics/last_refresh.json`: refresh health and destination status.

Google Sheets is only a mirror. Use a service account so unattended access does
not depend on seven-day OAuth testing tokens:

1. Enable Google Sheets API.
2. Create a service account and download its JSON locally.
3. Create a blank Google Sheet and share it with the service-account email.
4. Set `GOOGLE_SHEET_ID` and `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env`.
5. Run `python performance_tracker.py`.

Google documents direct sharing as the way a service account accesses a specific
Sheet: https://developers.google.com/workspace/guides/create-credentials

Standard Sheets API requests are free within published quotas; the tracker uses
batched writes and local replay: https://developers.google.com/workspace/sheets/api/limits

## Forbidden shortcuts

- No scraping or browser-botting Meta AI.
- No rotating fake/free accounts to bypass quotas.
- No unlicensed model or celebrity/franchise imitation.
- No silent Pexels substitution inside ECHO episodes.
- No public auto-publish.
- No upload unless OAuth channel ID matches `UCJDoRu8RqFez_DiG85bco3A`.
