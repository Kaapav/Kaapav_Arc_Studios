$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$dashboard = Join-Path $root "studio_dashboard.py"
$healthUrl = "http://127.0.0.1:8765/api/health"

foreach ($required in @($pythonw, $dashboard)) {
    if (!(Test-Path -LiteralPath $required)) { throw "Dashboard origin dependency missing: $required" }
}

try {
    if ((Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2).status -eq "ok") { exit 0 }
}
catch { }

Start-Process -FilePath $pythonw -ArgumentList @("-u", $dashboard) -WorkingDirectory $root -WindowStyle Hidden
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        if ((Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1).status -eq "ok") { exit 0 }
    }
    catch { }
}
throw "Dashboard origin did not become healthy."
