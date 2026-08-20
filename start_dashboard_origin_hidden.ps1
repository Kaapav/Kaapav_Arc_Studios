$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$dashboard = Join-Path $root "studio_dashboard.py"
$healthUrl = "http://127.0.0.1:8765/api/health"

try {
    if ((Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2).status -eq "ok") { exit 0 }
}
catch { }

Start-Process -FilePath $pythonw -ArgumentList @("-u", $dashboard) -WorkingDirectory $root -WindowStyle Hidden
