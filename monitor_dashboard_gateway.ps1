$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$originShortcut = Join-Path $root "KAAPAV Dashboard Origin.lnk"
$gatewayShortcut = Join-Path $root "KAAPAV Dashboard Gateway.lnk"
$statusPath = Join-Path $root "analytics\dashboard_health_monitor.json"
$checkedAt = (Get-Date).ToUniversalTime().ToString("o")

function Get-HttpStatus([string]$Url, [int]$Seconds) {
    $value = & curl.exe -s -o NUL -w "%{http_code}" --max-time $Seconds $Url
    if ($LASTEXITCODE -ne 0) { return 0 }
    return [int]$value
}

$localStatus = Get-HttpStatus "http://127.0.0.1:8765/api/health" 4
$originRestarted = $false
if ($localStatus -ne 200) {
    Start-Process -FilePath $originShortcut
    Start-Sleep -Seconds 3
    $localStatus = Get-HttpStatus "http://127.0.0.1:8765/api/health" 4
    $originRestarted = $true
}

$publicStatus = Get-HttpStatus "https://yt.kaapav.com/" 12
$gatewayRestarted = $false
if ($localStatus -eq 200 -and $publicStatus -notin @(200, 401)) {
    $stale = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "cloudflared.exe" -and $_.CommandLine -like "*dashboard-tunnel.yml*"
    }
    foreach ($process in $stale) { Stop-Process -Id $process.ProcessId -Force }
    Start-Process -FilePath $gatewayShortcut
    Start-Sleep -Seconds 15
    $publicStatus = Get-HttpStatus "https://yt.kaapav.com/" 12
    $gatewayRestarted = $true
}

$payload = [ordered]@{
    schema_version = 1
    checked_at = $checkedAt
    local_status = $localStatus
    public_status = $publicStatus
    origin_restarted = $originRestarted
    gateway_restarted = $gatewayRestarted
    healthy = ($localStatus -eq 200 -and $publicStatus -in @(200, 401))
}
$payload | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
if (!$payload.healthy) { exit 2 }
