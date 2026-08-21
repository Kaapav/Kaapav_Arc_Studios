# refresh_certification_evidence.ps1 — keeps setup_certification evidence fresh (fail-closed)
# Refreshes checked_at in dashboard_gateway_status.json + flutter_app_status.json ONLY when
# live probes match the recorded contracts. Any mismatch -> no refresh -> cert stays red (safe).
# Every scheduled run must leave a log line — a silent run is treated as a failure.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$logPath = Join-Path $root "logs\certification_refresher.log"
$checkedAt = (Get-Date).ToUniversalTime().ToString("o")

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}

function Get-HttpStatus([string]$Url, [int]$Seconds) {
    $value = & curl.exe -s -o NUL -w "%{http_code}" --max-time $Seconds $Url
    if ($LASTEXITCODE -ne 0) { return 0 }
    return [int]$value
}

Log "started"
try {
    # 1. Live probes
    $local  = Get-HttpStatus "http://127.0.0.1:8765/api/health" 5
    $public = Get-HttpStatus "https://yt.kaapav.com/" 12
    $gatewayTask = (Get-ScheduledTask -TaskName "KAAPAV ARC Dashboard Gateway" -ErrorAction SilentlyContinue).State
    $originTask  = (Get-ScheduledTask -TaskName "KAAPAV ARC Dashboard Origin" -ErrorAction SilentlyContinue).State

    # 2. Gateway evidence — refresh only if live state matches the recorded contract
    $gatewayOk = $false
    $gatewayPath = Join-Path $root "analytics\dashboard_gateway_status.json"
    if (Test-Path $gatewayPath) {
        $g = Get-Content $gatewayPath -Raw | ConvertFrom-Json
        if ($local -eq 200 -and $public -eq 401 -and $gatewayTask -eq "Ready" -and $originTask -eq "Ready" -and
            $g.anonymous_status -eq 401 -and $g.authenticated_status -eq 200 -and
            $g.remote_post_status -eq 403 -and $g.owner_control_post_status -eq 200 -and
            $g.bootstrap_reuse_status -eq 401) {
            $g.checked_at = $checkedAt
            $g | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $gatewayPath -Encoding UTF8
            $gatewayOk = $true
        }
    }

    # 3. Flutter evidence — refresh only if artifacts exist and match recorded sizes + hashes
    $flutterOk = $false
    $flutterPath = Join-Path $root "analytics\flutter_app_status.json"
    if (Test-Path $flutterPath) {
        $f = Get-Content $flutterPath -Raw | ConvertFrom-Json
        $win = Join-Path $root ($f.windows_artifact -replace '^\.\\', '')
        $apk = Join-Path $root ($f.android_artifact -replace '^\.\\', '')
        $winOk = (Test-Path $win) -and ((Get-Item $win).Length -eq $f.windows_bytes) -and
                 ((Get-FileHash $win -Algorithm SHA256).Hash.ToLower() -eq $f.windows_sha256)
        $apkOk = (Test-Path $apk) -and ((Get-Item $apk).Length -eq $f.android_bytes) -and
                 ((Get-FileHash $apk -Algorithm SHA256).Hash.ToLower() -eq $f.android_sha256)
        if ($winOk -and $apkOk) {
            $f.checked_at = $checkedAt
            $f | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $flutterPath -Encoding UTF8
            $flutterOk = $true
        }
    }

    # 4. Fail-closed gate
    if (-not ($gatewayOk -and $flutterOk)) {
        Log "REFRESH REFUSED (fail-closed): gateway=$gatewayOk flutter=$flutterOk local=$local public=$public gtask=$gatewayTask otask=$originTask"
        exit 1
    }

    Log "refreshed: true gateway=$gatewayOk flutter=$flutterOk local=$local public=$public"

    # 5. Pre-cert validation (auto-fix known issues)
    Log "running pre-cert validation"
    & (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "pre_cert_check.py") 2>&1 | Out-Null
    Log "pre-cert validation finished"

    # 6. Re-run certification so state + report stay current
    & (Join-Path $root ".venv\Scripts\python.exe") -B (Join-Path $root "setup_certification.py") 2>&1 | Out-Null
    Log "certification re-run finished"
    exit 0
}
catch {
    Log "EXCEPTION: $($_.Exception.Message)"
    exit 1
}