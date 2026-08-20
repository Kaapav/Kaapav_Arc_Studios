$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Legacy entry point redirected to the strict zero-touch supervisor.
& (Join-Path $PSScriptRoot "run_studio_autopilot.ps1")
exit $LASTEXITCODE

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run setup first."
}

$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("daily-{0}.log" -f (Get-Date -Format "yyyyMMdd"))

# Release only evidence-backed cohorts. Weak performance pauses future
# scheduling automatically instead of flooding the channel.
& $python -u (Join-Path $PSScriptRoot "growth_controller.py") `
    --wait-for-render *>&1 |
    Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
