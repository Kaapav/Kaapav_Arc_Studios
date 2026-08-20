# KAAPAV ARC Studio Control Room

Open `KAAPAV Studio Dashboard.lnk` or run `KAAPAV_Studio_Dashboard.cmd`.

The shortcut opens the secured public dashboard at `https://yt.kaapav.com/`. It requests a local-only, single-use 60-second bootstrap code and exchanges it for a signed, seven-day, `HttpOnly`, `Secure`, `SameSite=Strict` browser session. A copied or reused bootstrap link is rejected. Direct anonymous visits fail closed with HTTP `401`.

The authenticated owner dashboard includes one real production control: **Enable automation / Disable automation**. Enable removes the authoritative pause gate and starts the supervised Windows autopilot task. Disable atomically restores the pause gate and stops the scheduled task. Both actions require an explicit browser confirmation, a signed owner session and a confirmation header, and are recorded in `analytics/dashboard_control_events.jsonl`. If the scheduler cannot start, the server automatically re-closes the gate. All other remote POST actions remain blocked with HTTP `403`, including YouTube OAuth controls.

The dedicated Cloudflare tunnel is `kaapav-yt-dashboard` (`d109d7ae-2781-44fd-adb9-6270f85a80e9`). Its ingress forces an internal origin host and has a final `http_status:404` catch-all. Windows task `KAAPAV ARC Dashboard Origin` launches the local server in the signed-in desktop and checks it every five minutes; independent task `KAAPAV ARC Dashboard Gateway` uses HTTP/2, IPv4 and extended bounded retries. `KAAPAV ARC Dashboard Health Monitor` probes localhost and the public hostname every minute and restarts a stale connector automatically.

## Flutter app

The Android and Windows Flutter source is in `flutter/kaapav_control_room`. It uses a colourful neumorphism theme and the same five information tabs. Windows reads localhost. Android uses the secured public gateway and pairs once with `KAAPAV Pair Dashboard App.lnk`; the 12-character code expires in 60 seconds and can be used only once.

## Five tabs

1. **Overview** — whether the studio is working, paused, waiting or unhealthy; next exact action; buffer and universe totals.
2. **Production** — all ten series, the complete 300-episode searchable pipeline, episode name/number, exact state, blockers, queue, failures and recent events.
3. **Releases** — remote YouTube privacy/schedule state, reconciliation, views, likes and comments.
4. **Performance** — episode-wise tags, packaging traits, views, engaged views, retention, engagement rates, evidence windows, learning eligibility and honest tag-performance confidence.
5. **System** — scheduler, supervisor, certification, backup and fail-closed safeguards.

## YouTube retention permission

Google requires one owner consent for `yt-analytics.readonly`; service accounts cannot replace channel-owner OAuth for this API. Click **Enable Retention Analytics** inside the Performance tab or open `KAAPAV Enable Retention Analytics.lnk`.

OAuth buttons remain deliberately disabled in the public view. Use the localhost dashboard or the dedicated authorization shortcut for owner consent.

The authorization upgrader:

- preserves the current working upload token until the new grant is verified;
- rejects a wrong YouTube channel;
- requests upload, channel-management and Analytics read scopes together;
- opens the exact Google Cloud API page if the YouTube Analytics API is disabled;
- stores no secrets in the dashboard or status reports;
- becomes unattended after the one-time Google consent.

Retention data is never estimated. Until permission and sufficient YouTube data exist, the dashboard shows it as unavailable.
