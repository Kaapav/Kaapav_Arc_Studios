param(
    [ValidateRange(1, 12)]
    [int]$IntervalHours = 4
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runner = Join-Path $root "run_studio_autopilot.ps1"
$hiddenRunner = Join-Path $root "run_hidden.vbs"
$wscript = Join-Path $env:WINDIR "System32\wscript.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"

if (!(Test-Path -LiteralPath $python)) {
    throw "Virtual environment missing: $python"
}
if (!(Test-Path -LiteralPath $runner)) {
    throw "Autopilot runner missing: $runner"
}
if (!(Test-Path -LiteralPath $hiddenRunner) -or !(Test-Path -LiteralPath $wscript)) {
    throw "Silent launcher missing: $hiddenRunner"
}

$taskName = "KAAPAV ARC Studio Autopilot"
$action = New-ScheduledTaskAction `
    -Execute $wscript `
    -Argument "//B //NoLogo `"$hiddenRunner`" `"$runner`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(5)) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
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
    -Description "Zero-touch KAAPAV ARC production, strict QC, learning, future scheduling, and recovery." `
    -Force | Out-Null

foreach ($legacy in @("YT-Auto Daily Draft", "YT-Auto Performance Sync")) {
    if (Get-ScheduledTask -TaskName $legacy -ErrorAction SilentlyContinue) {
        Disable-ScheduledTask -TaskName $legacy | Out-Null
    }
}

Write-Host "Installed: $taskName every $IntervalHours hours"
Write-Host "Safety: strict fail-closed audit; private/future-scheduled only; no immediate public release"
Write-Host "Recovery: start-when-available, wake-to-run, three retries, persistent local state"
Write-Host "Desktop: silent background execution; no PowerShell window"
