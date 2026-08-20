$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run setup first."
}

$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("tracker-{0}.log" -f (Get-Date -Format "yyyyMMdd"))

& $python -u (Join-Path $PSScriptRoot "performance_tracker.py") *>&1 |
    Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
