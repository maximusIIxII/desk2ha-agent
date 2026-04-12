# Desk2HA Agent — NSSM Service Installation
# Run as Administrator!

$ErrorActionPreference = "Stop"

# Adjust these paths to your environment
$python = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
$config = "$PSScriptRoot\..\config.toml"
$appDir = "$PSScriptRoot\.."
$logDir = "$PSScriptRoot\..\logs"

# Ensure log directory exists
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

Write-Host "Installing Desk2HA Agent service..." -ForegroundColor Cyan

nssm install Desk2HAAgent $python "-m desk2ha_agent --config `"$config`" --service"
nssm set Desk2HAAgent AppDirectory $appDir
# Set MQTT password via environment variable (change to your password)
nssm set Desk2HAAgent AppEnvironmentExtra "DESK2HA_MQTT_PASS=$env:DESK2HA_MQTT_PASS"
nssm set Desk2HAAgent DisplayName "Desk2HA Agent"
nssm set Desk2HAAgent Description "Multi-vendor desktop telemetry agent for Home Assistant"
nssm set Desk2HAAgent AppRestartDelay 5000
nssm set Desk2HAAgent AppStdout "$logDir\service-stdout.log"
nssm set Desk2HAAgent AppStderr "$logDir\service-stderr.log"
nssm set Desk2HAAgent AppRotateFiles 1
nssm set Desk2HAAgent AppRotateBytes 5242880

Write-Host "Starting service..." -ForegroundColor Cyan
nssm start Desk2HAAgent

Write-Host "Done! Check status with: nssm status Desk2HAAgent" -ForegroundColor Green
