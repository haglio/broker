Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$trayLauncherPath = Join-Path $projectRoot 'launch_broker_tray.vbs'
$taskName = 'OSR2 Broker'

if (-not (Test-Path $trayLauncherPath)) {
    throw "Tray launcher not found: $trayLauncherPath"
}

$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$actionArgs = "`"$trayLauncherPath`""

$action = New-ScheduledTaskAction -Execute $wscript -Argument $actionArgs -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3650) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$userId = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Installed scheduled task: $taskName"
    Write-Host "It will start the broker when you sign in to Windows."
    Write-Host "To start it now: Start-ScheduledTask -TaskName '$taskName'"
    Write-Host "To remove it: Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
}
catch {
    $startupDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    New-Item -ItemType Directory -Path $startupDir -Force | Out-Null

    $startupVbs = Join-Path $startupDir 'OSR2 Broker.vbs'
    $trayScript = Join-Path $projectRoot 'scripts\broker_tray.ps1'
    $vbsContent = "Set shell = CreateObject(""WScript.Shell"")`r`nshell.Run ""powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """"$trayScript"""""", 0, False"
    Set-Content -Path $startupVbs -Value $vbsContent -Encoding ASCII

    Write-Warning "Scheduled Task installation failed (likely permissions)."
    Write-Host "Installed Startup-folder launcher instead: $startupVbs"
    Write-Host "It will start the broker when you sign in to Windows."
    Write-Host "To remove it: Remove-Item '$startupVbs'"
}
