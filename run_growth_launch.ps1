$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run setup first."
}

$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("growth-launch-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$env:PYTHONDONTWRITEBYTECODE = "1"

& $python -u (Join-Path $PSScriptRoot "growth_controller.py") `
    --wait-for-render *>&1 |
    Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

# Build the first enhanced widescreen chapter locally. It is not uploaded until
# the adaptive gate has validated the Shorts audience.
& $python -u (Join-Path $PSScriptRoot "chapter_main.py") `
    --chapter 1 *>&1 |
    Tee-Object -FilePath $logFile -Append
exit $LASTEXITCODE
