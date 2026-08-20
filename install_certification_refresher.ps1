# install_certification_refresher.ps1 — one-time installer (idempotent, safe to re-run)
# Registers scheduled task 'KAAPAV Certification Refresher' using the studio's
# existing hidden-wscript launcher pattern.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $root "refresh_certification_evidence.ps1"
$vbsPath = Join-Path $root "run_hidden.vbs"

if (-not (Test-Path $scriptPath)) { throw "Missing: $scriptPath" }
if (-not (Test-Path $vbsPath))    { throw "Missing: $vbsPath" }

$taskName = "KAAPAV Certification Refresher"

$action = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "//B //NoLogo `"$vbsPath`" `"$scriptPath`"" `
    -WorkingDirectory $root

$triggerLogon = New-ScheduledTaskTrigger -AtLogOn

$durationDays = 365
$triggerRepeat = $null
try {
    $triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Hours 2) `
        -RepetitionDuration (New-TimeSpan -Days $durationDays)
} catch {
    $triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Hours 2) `
        -RepetitionDuration (New-TimeSpan -Days 31)
    Write-Output "Note: repetition duration capped at 31 days."
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger $triggerLogon, $triggerRepeat -Settings $settings `
    -Description "Refreshes certification evidence (gateway + flutter) every 2h so setup_certification stays green" `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Output "Installed: $taskName | State: $($task.State) | NextRun: $($info.NextRunTime)"