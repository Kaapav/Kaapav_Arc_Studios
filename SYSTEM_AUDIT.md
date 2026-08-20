# AI Creative Explorer - Production Status

Verified: 2026-08-02

## Current status

- Setup doctor: **10/11 checks passed (91%)**
- Blocking owner action: **OAuth currently targets AI Verse Explorer, not AI Creative Explorer**
- Canon: **ECHO//100 locked**
- Daily trigger: **Windows Task Scheduler, 09:00 Asia/Kolkata**
- Performance trigger: **Windows Task Scheduler, 21:00 Asia/Kolkata**
- Publishing safety: **private YouTube drafts only**
- Episode policy: **one READY episode per run; clean no-op when none is ready**
- Stock footage: **blocked for story episodes**
- GPU: **not required**

## Production chain

1. Claim the next validated READY episode atomically.
2. Run the safety screen.
3. Generate narration offline with Piper.
4. Render protected episode artwork, motion, captions, and audio on CPU.
5. Build the story thumbnail.
6. Upload privately when YouTube is available; otherwise preserve a local draft.
7. Add the complete metadata to the review queue.
8. Mark the episode queued so it cannot be rendered twice.

Generic topic invention and Pexels stock clips are not fallback paths for ECHO//100. Missing content pauses safely instead of lowering quality.

## Reliability layers

- Script-provider chain: Gemini -> Groq. Invalid or paid-only providers were removed from the active chain.
- Voice chain: Piper offline -> Edge TTS -> Windows SAPI.
- Rendering: MoviePy + FFmpeg, atomic output, run lock, stage checkpoints.
- Publishing: expected-channel identity gate, YouTube OAuth, private override, synthetic-media disclosure, persistent review metadata.
- Scheduler: StartWhenAvailable, IgnoreNew overlap policy, three-hour execution limit.
- Analytics: YouTube Data API -> atomic local current/history CSV -> optional Google Sheets service-account mirror.
- Motion: ordered Meta/Kaggle/Colab/Hugging Face clips -> protected local image-motion fallback, with per-scene source telemetry.

## Verified evidence

- Full story dry-run passed at preview resolution in 80 seconds.
- Output: `output/story/20260802-152325-echo100-s01e001/video.mp4`
- Duration: 38.73 seconds; vertical 9:16; narration and captions present.
- Episode 1 returned to READY after dry-run.
- Wrong-channel test stopped before Episode 1 was claimed or uploaded.
- Correct channel analytics collected: 149 subscribers, 46 videos, 38,388 channel views as of 2026-08-02.
- Scheduler next run: 2026-08-03 09:00 IST.
- Performance tracker next run: 2026-08-02 21:00 IST.

## Owner actions outside the codebase

1. Run `python authorize_youtube.py --switch-channel` and select **AI Creative Explorer**. Until then, production fails closed before rendering/uploading.
2. Move the Google OAuth consent app from Testing to Production. Testing-mode refresh tokens for these scopes may expire after seven days.
3. Optional Google Sheets mirror: create/share a blank Sheet with a service account and set `GOOGLE_SHEET_ID` plus `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env`. Local tracking is already active.

## Commands

```powershell
.\.venv\Scripts\python.exe setup_check.py
.\.venv\Scripts\python.exe story_main.py --dry-run --preview
.\.venv\Scripts\python.exe story_main.py
powershell -ExecutionPolicy Bypass -File .\install_scheduler.ps1 -Time 09:00
.\.venv\Scripts\python.exe performance_tracker.py
```
