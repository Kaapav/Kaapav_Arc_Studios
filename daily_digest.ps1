# KAAPAV ARC Studio - Daily Health Digest (new file, no existing files touched)
# Cron-style: runs every morning, pushes one compact status message to ntfy.
# Exit 0 always - this is a report, not a gate.
$ErrorActionPreference = "Continue"
$root = "D:\Apps\YT-Auto"
$topic = "kaapav-arc-alerts"

function Read-JsonFile([string]$path) {
    try { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { return $null }
}

# --- build digest lines ---
$lines = @()
$local = (Get-Date).ToString("dd MMM yyyy, HH:mm")
$lines += "STUDIO DIGEST - $local"

# autopilot
$ap = Read-JsonFile (Join-Path $root "analytics\autopilot_state.json")
if ($ap) {
    $last = if ($ap.last_run_finished_at -or $ap.finished_at) { $ap.last_run_finished_at } else { $ap.finished_at }
    $next = if ($ap.next_run_at) { $ap.next_run_at } else { "unknown" }
    $lines += "Autopilot: $($ap.status) | last: $($ap.started_at) | next: $next"
} else { $lines += "Autopilot: NO STATE FILE" }

# certification
$cert = Read-JsonFile (Join-Path $root "analytics\setup_certification.json")
if ($cert) {
    $certified = 0; $total = 0
    if ($cert.certificates) {
        $certified = @($cert.certificates | Where-Object { $_.status -eq "certified" }).Count
        $total = @($cert.certificates).Count
    }
    $lines += "Cert: $($cert.status) ($certified/$total checks)"
} else { $lines += "Cert: NO STATE FILE" }

# reconciliation
$recon = Read-JsonFile (Join-Path $root "analytics\release_reconciliation.json")
if ($recon) { $lines += "Reconciliation: $($recon.status)" } else { $lines += "Reconciliation: NO STATE FILE" }

# releases - next due
$ytq = Read-JsonFile (Join-Path $root "analytics\youtube_timed_release_queue.json")
$mqq = Read-JsonFile (Join-Path $root "analytics\meta_release_queue.json")
$ytDue = $null; $ytCount = 0
if ($ytq) {
    $items = @($ytq.items)
    if ($items.Count -eq 0) { $items = @($ytq) }
    $ytCount = @($items | Where-Object { $_.status -ne "published" -and $_.status -ne "done" }).Count
    $nextItem = $items | Where-Object { $_.status -ne "published" -and $_.status -ne "done" } | Sort-Object { $_.publish_at } | Select-Object -First 1
    if ($nextItem) { $ytDue = "$($nextItem.publish_at) ($($nextItem.status))" }
}
$mqCount = 0; $mqDue = $null
if ($mqq) {
    $mitems = @($mqq.items)
    if ($mitems.Count -eq 0) { $mitems = @($mqq) }
    $mqCount = @($mitems | Where-Object { $_.status -ne "published" -and $_.status -ne "done" }).Count
    $mnext = $mitems | Where-Object { $_.status -ne "published" -and $_.status -ne "done" } | Sort-Object { $_.publish_at } | Select-Object -First 1
    if ($mnext) { $mqDue = "$($mnext.publish_at)" }
}
$lines += "YT releases: $ytCount queued" + $(if ($ytDue) { " | next: $ytDue" } else { "" })
$lines += "Meta releases: $mqCount queued" + $(if ($mqDue) { " | next: $mqDue" } else { "" })

# origin + tunnel probes
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 5
    $lines += "Origin: $($h.status)"
} catch { $lines += "Origin: DOWN" }
try {
    $r = Invoke-WebRequest -Uri "https://yt.kaapav.com/" -TimeoutSec 15 -UseBasicParsing
    $lines += "Tunnel: unexpected $($r.StatusCode)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) { $lines += "Tunnel: up (gate 401)" } else { $lines += "Tunnel: DOWN (got $code)" }
}

# disk
try {
    $drive = Get-PSDrive -Name D
    $free = [math]::Round($drive.Free / 1GB, 1)
    $flag = if ($free -lt 8) { " - WARNING: below 8 GB blocks production" } else { "" }
    $lines += "Disk D: $free GB free$flag"
} catch { }

# relaunch-day banner (2026-08-20)
$today = (Get-Date).ToString("yyyy-MM-dd")
if ($today -eq "2026-08-20") {
    $lines += "RELAUNCH DAY: Ep1 goes live 03:30Z (09:00 IST) YT+FB+IG"
}

# --- push ---
$message = $lines -join "`n"
try {
    $args = @("-s", "-o", "NUL", "-w", "%{http_code}",
        "-H", "Title: KAAPAV ARC STUDIO", "-H", "Tags: chart_with_upwards_trend",
        "-d", $message, "https://ntfy.sh/$topic")
    $code = & curl.exe @args 2>$null
    Write-Output "ntfy push: $code"
} catch { Write-Output "ntfy push failed" }
exit 0