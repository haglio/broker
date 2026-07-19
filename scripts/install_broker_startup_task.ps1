Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Registering a scheduled task needs elevation. Re-launch self elevated (UAC)
# so this can be run from an ordinary shell.
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Elevation required — accept the UAC prompt to install the task...'
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath
    )
    exit
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$trayLauncherPath = Join-Path $projectRoot 'launch_broker_tray.vbs'
$taskName = 'OSR2 Broker'
$legacyVbs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\OSR2 Broker.vbs'

if (-not (Test-Path $trayLauncherPath)) {
    throw "Tray launcher not found: $trayLauncherPath"
}

$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$actionArgs = "`"$trayLauncherPath`""

$action = New-ScheduledTaskAction -Execute $wscript -Argument $actionArgs -WorkingDirectory $projectRoot

# Two triggers:
#  - AtLogOn launches the tray immediately when you sign in.
#  - A repeating trigger re-fires every 2 minutes so a killed tray (the
#    broker's only supervisor) is revived mid-session instead of staying dead
#    until the next sign-in. The tray's single-instance mutex makes each
#    relaunch a no-op while it is already alive.
$atLogonTrigger = New-ScheduledTaskTrigger -AtLogOn
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3650) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$userId = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $atLogonTrigger, $repeatTrigger -Settings $settings -Principal $principal -Force | Out-Null

    # Migrate off the old login-only Startup-folder launcher so the tray is not
    # started by two mechanisms.
    if (Test-Path $legacyVbs) {
        Remove-Item $legacyVbs -Force
        Write-Host "Removed old Startup-folder launcher: $legacyVbs"
    }

    Start-ScheduledTask -TaskName $taskName

    Write-Host "Installed and started scheduled task: $taskName"
    Write-Host "It launches the broker at sign-in and revives it within ~2 min if the tray is killed."
    Write-Host "To remove it: Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
}
catch {
    $startupDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    New-Item -ItemType Directory -Path $startupDir -Force | Out-Null

    $vbsContent = "Set shell = CreateObject(""WScript.Shell"")`r`nshell.Run ""wscript.exe """"$trayLauncherPath"""""", 0, False"
    Set-Content -Path $legacyVbs -Value $vbsContent -Encoding ASCII

    Write-Warning "Scheduled Task registration failed: $($_.Exception.Message)"
    Write-Host "Installed a login-only Startup-folder launcher instead: $legacyVbs"
    Write-Host "This restarts the broker at sign-in but NOT mid-session. Re-run this"
    Write-Host "installer from an elevated PowerShell to get the ~2-min watchdog."
}
