Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$configPath = Join-Path $projectRoot 'osr2_broker_config.json'
if (-not (Test-Path $configPath)) {
    throw "Config not found: $configPath"
}

$config = Get-Content -Path $configPath -Raw | ConvertFrom-Json
$stateDir = [string]$config.state_dir
if ([string]::IsNullOrWhiteSpace($stateDir)) {
    $stateDir = Join-Path $projectRoot 'state'
}

$pythonExe = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$pythonConsoleExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path $pythonConsoleExe) {
    $pythonExe = $pythonConsoleExe
}

$launcherLog = Join-Path $stateDir 'broker_service_launcher.log'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

if (-not (Test-Path $pythonExe)) {
    "$(Get-Date -Format s) WARN venv python not found: $pythonExe. Falling back to py -3." | Add-Content -Path $launcherLog -Encoding UTF8
    & py -3 -m osr2_broker.app --config $configPath 1>> $launcherLog 2>&1
    exit $LASTEXITCODE
}

"$(Get-Date -Format s) INFO Starting broker with $pythonExe" | Add-Content -Path $launcherLog -Encoding UTF8
& $pythonExe -m osr2_broker.app --config $configPath 1>> $launcherLog 2>&1
if (Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue) {
    exit $global:LASTEXITCODE
}
exit 0
