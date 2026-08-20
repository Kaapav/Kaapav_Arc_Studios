$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$worker = Join-Path $root "meta_scheduler.py"
$logRoot = Join-Path $root "logs\meta"

New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
Get-ChildItem -LiteralPath $logRoot -Filter "*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTimeUtc -lt (Get-Date).ToUniversalTime().AddDays(-30) } |
    Remove-Item -Force
$log = Join-Path $logRoot ((Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $worker)) {
    throw "KAAPAV Meta scheduler runtime is incomplete."
}

Push-Location $root
try {
    & $python -B -u $worker --limit 4 *>> $log
    if ($LASTEXITCODE -ne 0) {
        throw "Meta scheduler failed closed with exit code $LASTEXITCODE. See $log"
    }
}
finally {
    Pop-Location
}
