# Desk2HA Elevated Helper — NSSM Service Installation
# Run as Administrator!
#
# The helper runs with admin privileges and exposes Dell DCM WMI metrics
# (and other elevated-only data) via localhost HTTP on port 9694.
# The main agent queries the helper instead of accessing WMI directly.

$ErrorActionPreference = "Stop"

# Adjust these paths to your environment
$python = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
$appDir = "$PSScriptRoot\.."
$logDir = "$PSScriptRoot\..\logs"

# Ensure log directory exists
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

Write-Host "Installing Desk2HA Helper service..." -ForegroundColor Cyan

nssm install Desk2HAHelper $python "-m desk2ha_agent.helper --port 9694 --log-dir `"$logDir`""
nssm set Desk2HAHelper AppDirectory $appDir
nssm set Desk2HAHelper DisplayName "Desk2HA Elevated Helper"
nssm set Desk2HAHelper Description "Privileged metric collector for Desk2HA (DCM WMI, thermals, fans)"
nssm set Desk2HAHelper AppRestartDelay 5000
nssm set Desk2HAHelper AppStdout "$logDir\helper-stdout.log"
nssm set Desk2HAHelper AppStderr "$logDir\helper-stderr.log"
nssm set Desk2HAHelper AppRotateFiles 1
nssm set Desk2HAHelper AppRotateBytes 2097152

Write-Host "Starting service..." -ForegroundColor Cyan
nssm start Desk2HAHelper

Write-Host "Done! Check status with: nssm status Desk2HAHelper" -ForegroundColor Green
Write-Host "Test with: curl http://127.0.0.1:9694/health" -ForegroundColor Yellow
