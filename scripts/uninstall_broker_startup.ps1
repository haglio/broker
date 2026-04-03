Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$taskName = 'OSR2 Broker'
$startupVbs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\OSR2 Broker.vbs'

$removedTask = $false
$removedStartup = $false

try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
        $removedTask = $true
    }
}
catch {
    Write-Host "Scheduled Task '$taskName' not found or no permission to query/remove it."
}

if (Test-Path $startupVbs) {
    Remove-Item $startupVbs -Force
    $removedStartup = $true
}

if ($removedTask -or $removedStartup) {
    Write-Host 'Removed broker autostart artifacts:'
    if ($removedTask) {
        Write-Host "- Scheduled Task: $taskName"
    }
    if ($removedStartup) {
        Write-Host "- Startup launcher: $startupVbs"
    }
}
else {
    Write-Host 'No broker autostart artifacts were removed.'
}
