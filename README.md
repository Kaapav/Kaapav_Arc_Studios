# Faceless YouTube Automation (India-focused)

> **RETIRED DOCUMENT:** The active KAAPAV ARC Studios system is documented in
> [`AUTOPILOT.md`](AUTOPILOT.md). The older generic-topic, daily publishing,
> manual approval and credential-copy instructions below are inactive and must
> not be used. Code-level gates block immediate public release and unaudited uploads.

> **Active production mode (2026-08-02): ECHO//100 story automation.**
> Run `story_main.py`, not the legacy generic-topic command. The daily runners and
> Windows scheduler already use the story engine, upload PRIVATE drafts only, and
> stop cleanly when no quality-controlled episode is marked `ready`.

## ECHO//100 quick operations

```powershell
# verify the permanent setup
.\.venv\Scripts\python.exe setup_check.py

# safe end-to-end preview; never uploads and leaves the episode ready
.\.venv\Scripts\python.exe story_main.py --dry-run --preview

# render/upload exactly one ready episode as a PRIVATE draft
.\.venv\Scripts\python.exe story_main.py

# install or refresh the daily 09:00 Windows trigger
powershell -ExecutionPolicy Bypass -File .\install_scheduler.ps1 -Time 09:00
```

The locked canon lives in `content/echo100/series.json`; production episode files
live in `content/echo100/episodes/`. Each episode must pass schema, canon, caption,
asset-path, and no-stock checks before it can run. `main.py`, `topics.txt`, and the
generic Pexels pipeline remain available only for manual experiments outside the
channel's scheduled story series.

## Performance tracking and motion fallbacks

```powershell
# refresh the correct channel's views, likes, comments, and daily history
.\.venv\Scripts\python.exe performance_tracker.py --no-google

# validate and attach a downloaded Meta/Kaggle/Colab/HF scene clip
.\.venv\Scripts\python.exe tools\ingest_motion.py `
  content\echo100\episodes\ep002.json 1 meta C:\Downloads\scene-01.mp4
```

Local analytics are always written first to `analytics/current.csv` and
`analytics/daily_snapshots.csv`. An optional Google Sheets service-account mirror
replays this local history after outages. Motion clips are attempted in episode
priority order; missing/corrupt clips fall back to protected local image motion.
See `FALLBACKS.md` for the verified provider and licensing matrix.

A complete, hands-off pipeline that turns a topic into a published YouTube video every day:

```
topic → script (LLM) → voiceover (TTS) → stock visuals → video + captions → thumbnail → auto-upload → repeat daily
```

Built for the Indian market: native **Hindi / Indian-English / Hinglish** voices, burned captions for retention, and vertical **Shorts** by default. Designed to run cheaply — the free tier needs **no paid API at all** (free `edge-tts` voice + generated backgrounds). Add keys to level up.

---

## What runs, and what costs money

| Stage | Default (free) | Upgrade (optional) |
|-------|----------------|--------------------|
| Script | Built-in template | OpenAI-compatible LLM (`OPENAI_API_KEY`) → natural, viral scripts |
| Voiceover | `edge-tts` (free, great hi-IN voices) | ElevenLabs (`ELEVENLABS_API_KEY`) |
| Visuals | Generated gradient backgrounds | Pexels stock photos (`PEXELS_API_KEY`, free) |
| Upload | — | YouTube Data API (OAuth, free) |

You can run the whole thing with **zero keys** to see a video render, then add keys one at a time.

---

## Quick start (5 minutes)

```bash
# 1. install ffmpeg (needed for video encoding)
#    macOS:  brew install ffmpeg
#    Ubuntu: sudo apt install ffmpeg fonts-noto
#    Windows: https://www.gyan.dev/ffmpeg/builds/  (add to PATH)

# 2. set up python
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Windows daily runner (PowerShell / Task Scheduler):
.\run_daily.ps1

# 3. configure
cp .env.example .env          # optional: add keys later
#    edit config.yaml -> channel name, niche, language, voice

# 4. render your FIRST video without uploading
python main.py --no-upload
```

The finished `video.mp4`, `thumbnail.jpg`, `voice.mp3`, and metadata land in `output/<timestamp-topic>/`.

---

## Going fully automatic

### A. Get good scripts (recommended, free)
Create a Gemini API key at <https://aistudio.google.com/apikey> and put it in `.env`:
```
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash-lite
```
The adapter also supports any OpenAI-compatible provider if you prefer:
```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```
Without an LLM key you get test-only template scripts; they are blocked from approval/upload because they are not publishable content.

### B. Get real footage (recommended, free)
Grab a free key at <https://www.pexels.com/api/> and put it in `.env` as `PEXELS_API_KEY`.

### C. YouTube upload setup (one-time)
1. Go to <https://console.cloud.google.com/> → create a project.
2. Enable **YouTube Data API v3**.
3. **APIs & Services → Credentials → Create OAuth client ID → Desktop app**. Download the JSON.
4. Save it as `credentials/client_secret.json`.
5. Add yourself as a **Test user** under the OAuth consent screen (keeps you out of Google's review queue).
6. Run once locally to authorize without uploading anything:
   ```bash
   python authorize_youtube.py  # opens a browser, sign in, allow → caches credentials/token.json
   ```
Videos **always upload as private drafts** and enter a review queue. Your daily routine (2 minutes):
```bash
python review.py list             # see today's draft + safety verdict
python review.py approve <id>     # publish it (private -> public)
python review.py approve-safe     # or: publish everything the safety gate passed
python review.py reject <id>      # decline — stays private forever
```
Anything the safety gate flags is **HELD** and can't be published without `--force`. Details in `SAFETY.md`. When publishing, toggle **"Altered or synthetic content"** in YouTube Studio (required for AI content; zero effect on reach).

### D. Schedule it (pick one)

**Local machine / VPS (cron):**
```bash
chmod +x run_daily.sh
crontab -e
# post daily at 6:30am:
30 6 * * * /full/path/to/yt-auto/run_daily.sh >> /full/path/to/yt-auto/cron.log 2>&1
```

**GitHub Actions (no server needed):** `.github/workflows/daily.yml` is included. After authorizing locally once, add three repo secrets (Settings → Secrets → Actions):
```bash
base64 -w0 .env                      # -> secret ENV_FILE_B64
base64 -w0 credentials/token.json    # -> secret YT_TOKEN_B64
base64 -w0 credentials/client_secret.json  # -> secret YT_CLIENT_SECRET_B64
```
It then renders and uploads a video every day at 06:30 IST, free.

---

## Tuning your channel — everything is in `config.yaml`

- **`channel.language`** — `hindi`, `english`, or `hinglish` (Hinglish tends to travel furthest on Indian Shorts).
- **`voice.edge_voice`** — try `hi-IN-MadhurNeural` (m), `hi-IN-SwaraNeural` (f), `en-IN-NeerjaNeural` (f). List all: `edge-tts --list-voices | grep -i "-IN-"`.
- **`video.format`** — `shorts` (1080×1920) or `long` (set width/height to 1920×1080).
- **`script.target_words`** — ~130 words ≈ 50s. Keep Shorts under 60s.
- **`youtube.category_id`** — 27 Education, 24 Entertainment, 28 Science & Tech.

### Your content queue
`topics.txt` is the idea queue — one per line, top-down, never repeated (used ones are logged in `.cache/used_topics.txt`). Add hundreds and you have months of content. When it runs dry, if an LLM key is set the pipeline invents fresh topics automatically.

### Hindi captions
For Devanagari subtitles, install a Noto Devanagari font (Ubuntu: `sudo apt install fonts-noto`; the GitHub workflow already does this). The renderer auto-detects it. Hinglish/English need no extra fonts.

### Background music
Drop a royalty-free `assets/music.mp3` (see `assets/README.txt`) and it's mixed under the narration automatically.

---

## Project layout

```
yt-auto/
├── main.py                # orchestrator — one run = one video
├── config.yaml            # all your settings
├── topics.txt             # your idea queue
├── requirements.txt
├── .env.example           # copy to .env, add keys
├── run_daily.sh           # cron runner
├── review.py              # human review CLI: list / approve / reject drafts
├── GROWTH.md              # virality + loyal-fanbase playbook
├── MONETIZATION.md        # YPP rules + how to stay monetizable
├── SAFETY.md              # 3-layer content-safety system explained
├── .github/workflows/daily.yml   # scheduled cloud runs
├── assets/                # optional music.mp3
└── src/
    ├── config.py          # loads yaml + env
    ├── ideas.py           # next topic from queue / LLM
    ├── llm.py             # OpenAI-compatible wrapper + moderation (optional)
    ├── script_writer.py   # topic -> viral, on-brand script (LLM or template)
    ├── safety.py          # content-safety gate (rules + LLM moderation)
    ├── review.py          # review queue (drafts stay private until approved)
    ├── tts.py             # edge-tts voiceover + word timings
    ├── media.py           # Pexels footage / gradient fallback
    ├── captions.py        # word-synced burned subtitles (Pillow)
    ├── video.py           # moviepy assembly (Ken Burns + captions + music)
    ├── thumbnail.py       # bold thumbnail generator
    └── upload.py          # YouTube Data API v3 upload
```

---

## Command reference

```bash
python main.py                    # full run: pick topic -> render -> upload private draft
python main.py --no-upload        # render only (testing)
python main.py --topic "I let AI design my whole brand"   # force a topic
python review.py list             # review queue: today's drafts + safety verdicts
python review.py approve-safe     # publish all safe pending drafts
```

---

## Playing it safe (so the channel survives)

- **Nothing goes public without you.** Drafts upload private; `review.py` is the only path to public, and safety-flagged items additionally require `--force`. Full details: `SAFETY.md`.
- Every script passes a 3-layer safety gate: safe-by-prompt rules, keyword/intent screening + your `custom_blocklist`, and (with an LLM key) OpenAI's moderation model.
- Keep facts accurate — an LLM can hallucinate; spot-check surprising claims before approving.
- Respect YouTube's inauthentic-content policy: vary topics/series, use the LLM (not the bare template), and add your own takes. See `MONETIZATION.md`.
- Disclose AI: the pipeline appends an AI note to descriptions; you toggle "Altered or synthetic content" in Studio when publishing.
- Only use footage you're licensed for (Pexels is free-to-use; check attribution rules).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No module named moviepy` | `pip install -r requirements.txt` inside your venv |
| ffmpeg / codec errors | install ffmpeg system-wide (see Quick start) |
| Captions show boxes for Hindi | install a Noto Devanagari font |
| `edge-tts` connection error | needs internet to Microsoft's TTS endpoint; retry or switch voice |
| Upload 403 / not authorized | add yourself as a Test user on the OAuth consent screen |
| Topics exhausted | add lines to `topics.txt`, or set an LLM key for auto-generation |
```
