param(
    [ValidateRange(1, 30)]
    [int]$Count = 13
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run setup first."
}

$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("vault-buffer-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

$env:PYTHONDONTWRITEBYTECODE = "1"
& $python -u (Join-Path $PSScriptRoot "render_vault.py") --count $Count *>&1 |
    Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
