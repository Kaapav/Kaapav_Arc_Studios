param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Time = "09:00",
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$TrackerTime = "21:00"
)

# Compatibility wrapper: the legacy daily-draft scheduler is permanently
# retired. Any old shortcut now installs the strict studio supervisor instead.
& (Join-Path $PSScriptRoot "install_autopilot_scheduler.ps1") -IntervalHours 4
return

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runner = Join-Path $root "run_daily.ps1"
$trackerRunner = Join-Path $root "run_tracker.ps1"
$python = Join-Path $root ".venv\Scripts\python.exe"

if (!(Test-Path -LiteralPath $python)) {
    throw "Virtual environment missing: $python"
}
if (!(Test-Path -LiteralPath $runner)) {
    throw "Daily runner missing: $runner"
}
if (!(Test-Path -LiteralPath $trackerRunner)) {
    throw "Tracker runner missing: $trackerRunner"
}

$taskName = "YT-Auto Daily Draft"
$at = [datetime]::Today.Add([timespan]::Parse($Time))
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Run the evidence-gated ECHO//100 growth controller daily." `
    -Force | Out-Null

$trackerTaskName = "YT-Auto Performance Sync"
$trackerAt = [datetime]::Today.Add([timespan]::Parse($TrackerTime))
$trackerAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$trackerRunner`"" `
    -WorkingDirectory $root
$trackerTrigger = New-ScheduledTaskTrigger -Daily -At $trackerAt
Register-ScheduledTask `
    -TaskName $trackerTaskName `
    -Action $trackerAction `
    -Trigger $trackerTrigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Refresh AI Creative Explorer views, likes, comments, and tracker data." `
    -Force | Out-Null

Write-Host "Installed: $taskName at $Time daily"
Write-Host "Mode: adaptive cohorts; weak performance pauses future publication"
Write-Host "Installed: $trackerTaskName at $TrackerTime daily"
Write-Host "Mode: local CSV first, optional Google Sheets mirror"
