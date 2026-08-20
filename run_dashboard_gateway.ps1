$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$dashboard = Join-Path $root "studio_dashboard.py"
$cloudflared = Join-Path $env:USERPROFILE ".cloudflared\cloudflared.exe"
$config = Join-Path $root "cloudflare\dashboard-tunnel.yml"
$log = Join-Path $root "logs\dashboard_tunnel.log"
$healthUrl = "http://127.0.0.1:8765/api/health"

foreach ($required in @($pythonw, $dashboard, $cloudflared, $config)) {
    if (!(Test-Path -LiteralPath $required)) { throw "Dashboard gateway dependency missing: $required" }
}

$healthy = $false
try { $healthy = (Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1).status -eq "ok" } catch { }
if (!$healthy) {
    Start-Process -FilePath $pythonw -ArgumentList @("-u", $dashboard) -WorkingDirectory $root -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            if ((Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1).status -eq "ok") { $healthy = $true; break }
        }
        catch { }
    }
}
if (!$healthy) { throw "Dashboard origin did not become healthy." }

$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq "cloudflared.exe" -and $_.CommandLine -like "*dashboard-tunnel.yml*"
}
if ($existing) { exit 0 }

$process = Start-Process `
    -FilePath $cloudflared `
    -ArgumentList @(
        "--config", $config, "--protocol", "http2", "--edge-ip-version", "4",
        "--retries", "20", "--logfile", $log, "--loglevel", "info", "tunnel", "run"
    ) `
    -NoNewWindow -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "Dashboard tunnel exited with code $($process.ExitCode)" }
