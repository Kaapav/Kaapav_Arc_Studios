# KAAPAV ARC Studio - Failure Alert Monitor (new file, no existing files touched)
# Reads analytics state files + live probes. On failure: pushes to ntfy.sh topic.
# Cooldown 45 min per issue key. Exit 0 always (monitor, not a gate).
$ErrorActionPreference = "Continue"
$root = "D:\Apps\YT-Auto"
$cooldownPath = Join-Path $root "analytics\alert_cooldown.json"
$topic = "kaapav-arc-alerts"
$cooldownSeconds = 45 * 60
$now = (Get-Date).ToUniversalTime()

function Read-JsonFile([string]$path) {
    try { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { return $null }
}

function Send-Alert([string]$message) {
    try {
        $title = "KAAPAV ARC ALERT"
        $tag = "rotating_light"
        $priority = "4"
        $args = @("-s", "-o", "NUL", "-w", "%{http_code}",
            "-H", "Title: $title", "-H", "Priority: $priority", "-H", "Tags: $tag",
            "-d", $message, "https://ntfy.sh/$topic")
        $code = & curl.exe @args 2>$null
        return ($code -eq "200")
    } catch { return $false }
}

# --- collect issues ---
$issues = @()

$supervisor = Read-JsonFile (Join-Path $root "analytics\supervisor_state.json")
if ($supervisor -and $supervisor.status -ne "healthy") { $issues += "SUPERVISOR: $($supervisor.status)" }

$autopilot = Read-JsonFile (Join-Path $root "analytics\autopilot_state.json")
if ($autopilot -and $autopilot.status -ne "healthy") { $issues += "AUTOPILOT: $($autopilot.status)" }

$cert = Read-JsonFile (Join-Path $root "analytics\setup_certification.json")
if ($cert -and $cert.status -ne "certified_active" -and $cert.status -ne "certified_paused") { $issues += "CERTIFICATION: $($cert.status)" }

$recon = Read-JsonFile (Join-Path $root "analytics\release_reconciliation.json")
if ($recon -and $recon.status -ne "passed") { $issues += "RECONCILIATION: $($recon.status)" }

# origin live probe
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 5
    if ($h.status -ne "ok") { $issues += "ORIGIN: unhealthy" }
} catch { $issues += "ORIGIN: down" }

# tunnel live probe (expect HTTP 401 = gate working; anything else = tunnel problem)
try {
    $r = Invoke-WebRequest -Uri "https://yt.kaapav.com/api/health" -TimeoutSec 15 -UseBasicParsing
    $issues += "TUNNEL: unexpected $($r.StatusCode)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -ne 401) { $issues += "TUNNEL: down (got $code)" }
}

# disk free (D: < 8 GB blocks production)
try {
    $drive = Get-PSDrive -Name D
    if (($drive.Free / 1GB) -lt 8) { $issues += "DISK D: only $([math]::Round($drive.Free / 1GB, 1)) GB free (< 8 GB blocks production)" }
} catch { }

if ($issues.Count -eq 0) { exit 0 }

# --- cooldown gate ---
$lastSent = 0
try { $cd = Read-JsonFile $cooldownPath; $lastSent = [long]$cd.last_sent } catch { }
if (($now.ToFileTimeUtc() / 10000000) -lt ($lastSent + $cooldownSeconds)) { exit 0 }

$message = ($issues -join "`n")
if (Send-Alert $message) {
    $stamp = [long]($now.ToFileTimeUtc() / 10000000)
    @{ last_sent = $stamp } | ConvertTo-Json | Set-Content -LiteralPath $cooldownPath -Encoding UTF8
}