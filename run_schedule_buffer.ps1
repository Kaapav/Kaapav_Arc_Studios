param(
    [ValidateRange(1, 100)]
    [int]$Target = 15,
    [switch]$AllEpisodes
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run setup first."
}
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("schedule-buffer-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$env:PYTHONDONTWRITEBYTECODE = "1"
$scheduleArgs = @((Join-Path $PSScriptRoot "maintain_schedule.py"), "--time", "09:00", "--wait-for-render")
if ($AllEpisodes) {
    $scheduleArgs += "--all-episodes"
} else {
    $scheduleArgs += @("--target", $Target)
}
& $python -u @scheduleArgs *>&1 |
    Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
