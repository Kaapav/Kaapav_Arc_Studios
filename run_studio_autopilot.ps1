$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$controller = Join-Path $root "studio_supervisor.py"
$logRoot = Join-Path $root "logs\autopilot"

New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
Get-ChildItem -LiteralPath $logRoot -Filter "*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTimeUtc -lt (Get-Date).ToUniversalTime().AddDays(-30) } |
    Remove-Item -Force
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logRoot "$stamp.log"

if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $controller)) {
    throw "KAAPAV autopilot runtime is incomplete."
}

Push-Location $root
try {
    & $python -B -u $controller --render-limit 1 --upload-limit 4 *>> $log
    if ($LASTEXITCODE -ne 0) {
        throw "Autopilot failed closed with exit code $LASTEXITCODE. See $log"
    }
}
finally {
    Pop-Location
}
