$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$url = "http://127.0.0.1:8765/"
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$server = Join-Path $root "studio_dashboard.py"

if (!(Test-Path -LiteralPath $pythonw) -or !(Test-Path -LiteralPath $server)) {
    throw "KAAPAV dashboard runtime is incomplete."
}

$running = $false
try {
    $health = Invoke-RestMethod -Uri ($url + "api/health") -TimeoutSec 1
    $running = $health.status -eq "ok"
}
catch {
    $running = $false
}

if (!$running) {
    Start-Process -FilePath $pythonw `
        -ArgumentList @("-u", $server) `
        -WorkingDirectory $root `
        -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $health = Invoke-RestMethod -Uri ($url + "api/health") -TimeoutSec 1
            if ($health.status -eq "ok") { $running = $true; break }
        }
        catch { }
    }
}

if (!$running) { throw "Dashboard did not start on $url" }

$publicUrl = "https://yt.kaapav.com/"
$publicReady = $false
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $publicUrl -MaximumRedirection 0 -TimeoutSec 8
    $publicReady = $response.StatusCode -in @(200, 401, 302)
}
catch {
    if ($_.Exception.Response) {
        $publicReady = [int]$_.Exception.Response.StatusCode -eq 401
    }
}

if ($publicReady) {
    $bootstrap = Invoke-RestMethod -Uri ($url + "api/bootstrap") -TimeoutSec 2
    $code = [Uri]::EscapeDataString([string]$bootstrap.code)
    Start-Process ($publicUrl + "auth/bootstrap?code=" + $code)
}
else {
    Start-Process $url
}
