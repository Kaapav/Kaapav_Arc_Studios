param(
    [ValidateRange(1, 30)]
    [int]$IntervalMinutes = 1
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runner = Join-Path $root "run_meta_scheduler.ps1"
$hiddenRunner = Join-Path $root "run_hidden.vbs"
$wscript = Join-Path $env:WINDIR "System32\wscript.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"

foreach ($required in @($runner, $hiddenRunner, $wscript, $python)) {
    if (!(Test-Path -LiteralPath $required)) { throw "Required Meta scheduler file missing: $required" }
}

$taskName = "KAAPAV ARC Meta Publisher"
$action = New-ScheduledTaskAction `
    -Execute $wscript `
    -Argument "//B //NoLogo `"$hiddenRunner`" `"$runner`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
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
    -Description "Fail-closed Facebook and Instagram publishing, recovery, and analytics for KAAPAV ARC Studios." `
    -Force | Out-Null

Write-Host "Installed: $taskName every $IntervalMinutes minute(s)"
Write-Host "Desktop: silent background execution; strict QC and platform controls enforced"
