# KAAPAV ARC Studios — Zero-Touch Autopilot

This document is the operational source of truth. Older generic-channel and manual-review instructions are retired.

## Local control-room dashboard

Double-click `KAAPAV Studio Dashboard.lnk` for the local five-tab glassmorphism dashboard. It shows the live pause/running state, complete 300-episode pipeline, series and episode names, blockers, releases, episode/tag performance, retention permission, scheduler health and backups. See `DASHBOARD.md`.

## Active system

- Supervisor: `studio_supervisor.py`
- Production controller: `studio_autopilot.py`
- Windows runner: `run_studio_autopilot.ps1`
- Windows task: `KAAPAV ARC Studio Autopilot`, every four hours
- Windows task behavior: start when available, wake to run, continue on battery, retry three times at 15-minute intervals, and ignore overlapping starts.
- Creative heartbeat: `KAAPAV Zero-Touch Studio`, every four hours
- Runtime policy: `config.story.yaml` under `autopilot`
- Release plan: `content/studio_master_release_plan.json`

Normal manual actions are zero. The system creates, renders, audits, learns, recovers and future-schedules. A failed or unverifiable stage remains local and queued.

## Release contract

1. Locked multi-angle identities exist before story images.
2. Every story frame is unique, causal and visually accepted in `image_qc.json`.
3. Video contains narration, music/SFX, burned captions and purposeful motion.
4. Full decode, stream probe and contact sheet pass.
5. Rights/provenance manifest has no unresolved asset.
6. Title, description, tags, series and episode identity match the rendered script.
7. Exact video, thumbnail and script hashes are frozen in a fresh audit.
8. Authenticated channel equals `UCylPn80btY6lpivJ_N-cXGQ`.
9. Custom thumbnail is confirmed.
10. Upload is private or assigned a future policy-compliant slot. Immediate public release is blocked.

## Cadence and inventory

- Shorts: every two days at 10:00 IST, beginning with Episode 11.
- Buffer: seven fully audited or scheduled Shorts, equal to fourteen days.
- The buffer is a rolling cap, not a mass-scheduling target; later episodes wait for organic evidence and no episode can schedule across an unresolved earlier chapter.
- Compilations: each five-episode block, weekend at 10:00 IST.
- Series: sequential; no second series starts while the active series is unfinished.

## Performance learning

- Owner-confirmed Episode 1–10 traffic is excluded and treated as zero organic evidence.
- Organic learning starts with Episode 11.
- Evaluation windows: 24 hours, 72 hours and 168 hours.
- The closest daily snapshot for every matured window is preserved, so later learning cannot erase the earlier 24-hour or 72-hour result.
- The learner tracks title framing, opening hook, thumbnail focus and story engine.
- Results below twenty views remain insufficient samples.
- Zero views is recorded as no observed distribution, not falsely blamed on tags or metadata.
- Published videos are not deleted or reuploaded merely for low traffic.
- YouTube Analytics retention metrics are optional; Data API views and engagement remain the fail-safe evidence source.

## Evergreen creation

The studio maintains a rolling slate. Whenever only two unreleased series remain, `src/story_factory.py` queues exactly ten fresh original 30-episode series. The active `KAAPAV Zero-Touch Studio` heartbeat executes those tasks, validates each complete package and appends only passing series to the sequential master plan. When that expanded slate again reaches two unreleased series, the same ten-series refill repeats. Candidate series must pass originality, causal-story, anti-slop and continuity validation before turnarounds or story images begin.

## Facebook and Instagram

- Facebook and Instagram have independent dashboard switches, queue counts, health, failures and performance evidence.
- `KAAPAV ARC Meta Publisher` runs silently every minute with no overlapping instances and persistent crash checkpoints.
- The current owner-authorized relaunch begins with Episode 1 across all three platforms. Existing YouTube IDs are preserved and only explicitly queued, freshly audited episodes may enter this relaunch; unrelated old content is never blindly backfilled.
- Every due Meta release re-hashes the exact video, thumbnail, script and controlled metadata against its persisted strict audit before publication.
- A Facebook or Instagram failure is isolated to that platform. YouTube and the other Meta platform continue when their own gates remain healthy.
- Meta analytics and 24h/72h/168h learning are evidence-only. Missing watch metrics remain unknown, and small samples cannot declare a winner.

## Recovery and safety

- Double-click `KAAPAV Studio Recovery.lnk` for a bounded manual recovery. It clears stale supervisor state without rendering or uploading, checks all three platform connections, processes only due strictly audited releases, restarts the five silent workers and writes `analytics/manual_recovery_status.json`. It never removes the global pause or publishes early.
- One controller lock prevents overlapping uploads.
- Failed stages use exponential backoff and persistent recovery state.
- Renders run in isolated worker processes with a 60-minute watchdog; a dead encoder is terminated as a tree and retried from accepted assets.
- Future MoviePy workers are pinned to the installed FFmpeg 8.x binary instead of ImageIO's obsolete bundled FFmpeg 4.2.2; a compatibility render is part of the verified setup.
- Duplicate video hashes and episode IDs are blocked by `analytics/release_ledger.json`.
- Remote YouTube state is reconciled in `analytics/release_reconciliation.json`.
- Less than 8 GB free disk blocks production safely.
- An emergency pause file at `analytics/PAUSE_AUTOPILOT` stops all production and release activity.
- A verified daily control-plane snapshot protects story canon, manifests, code, configuration and operating state in `backups/control-plane`; credentials and bulky regenerable media are excluded.
- The daily snapshot is refreshed again when protected source files change, and unattended logs older than 30 days are pruned.
- Local snapshots protect against file corruption and accidental edits. They do not replace a future off-device backup for physical disk failure.
- Credentials, OAuth tokens, client secrets and service-account keys are never copied into logs, reports, bundles or prompts.

## Verification commands

```powershell
.\.venv\Scripts\python.exe studio_autopilot.py --dry-run --no-network
.\.venv\Scripts\python.exe -m unittest tests.test_release_audit tests.test_studio_automation -v
.\.venv\Scripts\python.exe audit_studio_universe.py
```

Current health is mirrored locally and in the Google Sheet tabs: Dashboard, Videos, Daily Snapshots, Learning, Inventory, Audit Log, Autopilot Health, Fallback Matrix, Platform Health, Meta Performance and Meta History.

The Dashboard tracks both current YouTube Partner Program paths: early access at 500 subscribers plus three public uploads and either 3,000 long-form watch hours or 3 million valid Shorts views; ad revenue at 1,000 subscribers and either 4,000 long-form watch hours or 10 million valid Shorts views. Time windows are shown in the Sheet and must be revalidated against official YouTube Help when policy changes.
