$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$hiddenRunner = Join-Path $root "run_hidden.vbs"
$wscript = Join-Path $env:WINDIR "System32\wscript.exe"
$originLauncher = Join-Path $root "start_dashboard_origin_hidden.ps1"
$originShortcut = Join-Path $root "KAAPAV Dashboard Origin.lnk"
$gatewayLauncher = Join-Path $root "run_dashboard_gateway.ps1"
$gatewayShortcut = Join-Path $root "KAAPAV Dashboard Gateway.lnk"
$monitorShortcut = Join-Path $root "KAAPAV Dashboard Health Monitor.lnk"
$cloudflared = Join-Path $env:USERPROFILE ".cloudflared\cloudflared.exe"
$config = Join-Path $root "cloudflare\dashboard-tunnel.yml"
$log = Join-Path $root "logs\dashboard_tunnel.log"
$monitor = Join-Path $root "monitor_dashboard_gateway.ps1"
$dashboardLauncher = Join-Path $root "launch_studio_dashboard.ps1"
$dashboardShortcut = Join-Path $root "KAAPAV Studio Dashboard.lnk"
$originTaskName = "KAAPAV ARC Dashboard Origin"
$gatewayTaskName = "KAAPAV ARC Dashboard Gateway"
$monitorTaskName = "KAAPAV ARC Dashboard Health Monitor"

foreach ($required in @($hiddenRunner, $wscript, $originLauncher, $gatewayLauncher, $cloudflared, $config, $monitor, $dashboardLauncher)) {
    if (!(Test-Path -LiteralPath $required)) { throw "Gateway dependency missing: $required" }
}

$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($originShortcut)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "//B //NoLogo `"$hiddenRunner`" `"$originLauncher`""
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = "KAAPAV dashboard origin watchdog launcher"
$shortcut.Save()

$shortcut = $shortcutShell.CreateShortcut($gatewayShortcut)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "//B //NoLogo `"$hiddenRunner`" `"$gatewayLauncher`""
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = "KAAPAV dashboard tunnel launcher"
$shortcut.Save()

$shortcut = $shortcutShell.CreateShortcut($monitorShortcut)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "//B //NoLogo `"$hiddenRunner`" `"$monitor`""
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = "KAAPAV dashboard live health monitor"
$shortcut.Save()

$shortcut = $shortcutShell.CreateShortcut($dashboardShortcut)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "//B //NoLogo `"$hiddenRunner`" `"$dashboardLauncher`""
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = "Open the secured KAAPAV Studio Dashboard without a console window"
$shortcut.Save()

$originAction = New-ScheduledTaskAction `
    -Execute "explorer.exe" `
    -Argument "`"$originShortcut`"" `
    -WorkingDirectory $root
$tunnelAction = New-ScheduledTaskAction `
    -Execute "explorer.exe" `
    -Argument "`"$gatewayShortcut`"" `
    -WorkingDirectory $root
$monitorAction = New-ScheduledTaskAction `
    -Execute "explorer.exe" `
    -Argument "`"$monitorShortcut`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$watchTrigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$monitorTrigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $originTaskName -Action $originAction -Trigger @($trigger, $watchTrigger) -Settings $settings `
    -Principal $principal -Description "Interactive local-only KAAPAV dashboard origin watchdog." `
    -Force | Out-Null
Register-ScheduledTask `
    -TaskName $gatewayTaskName -Action $tunnelAction -Trigger @($trigger, $watchTrigger) -Settings $settings `
    -Principal $principal -Description "Interactive secure read-only yt.kaapav.com tunnel launcher." `
    -Force | Out-Null
Register-ScheduledTask `
    -TaskName $monitorTaskName -Action $monitorAction -Trigger @($trigger, $monitorTrigger) -Settings $settings `
    -Principal $principal -Description "Restarts stale KAAPAV dashboard origin or tunnel after live health failure." `
    -Force | Out-Null
Write-Host "Installed: $originTaskName"
Write-Host "Installed: $gatewayTaskName"
Write-Host "Installed: $monitorTaskName"
Write-Host "Desktop: silent background execution; no PowerShell windows"
