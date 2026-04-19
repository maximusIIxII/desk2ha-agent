# Desk2HA Elevated Helper — Scheduled Task installer
#
# Installs `Desk2HAHelper` as a Windows Scheduled Task running in the user's
# interactive session at logon, with Highest run level. An interactive session
# is required because DDC/CI (monitorcontrol / WMI Monitor PnP) does not work
# under LocalSystem / Session 0.
#
# The helper reads its bearer token from [helper].secret in config.toml via
# the `--config` flag, so no environment-variable bootstrapping is needed.
#
# Run as Administrator.

[CmdletBinding()]
param(
    [string] $Python     = $null,
    [string] $ConfigPath = $null,
    [string] $LogDir     = $null,
    [string] $TaskName   = "Desk2HAHelper"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $ConfigPath) { $ConfigPath = Join-Path $repoRoot "config.toml" }
if (-not $LogDir)     { $LogDir     = Join-Path $repoRoot "logs" }

if (-not $Python) {
    $candidate = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $candidate) {
        throw "python.exe not found on PATH — pass -Python <path> explicitly."
    }
    $Python = $candidate
}

if (-not (Test-Path $ConfigPath)) {
    throw "Config file not found at $ConfigPath — create it (see examples/full-config.toml) or pass -ConfigPath."
}
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$arguments = "-m desk2ha_agent.helper --config `"$ConfigPath`" --log-dir `"$LogDir`""

Write-Host "Installing Scheduled Task '$TaskName'" -ForegroundColor Cyan
Write-Host "  Execute    : $Python"
Write-Host "  Arguments  : $arguments"
Write-Host "  WorkingDir : $repoRoot"
Write-Host "  Config     : $ConfigPath"
Write-Host "  LogDir     : $LogDir"

$action    = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $repoRoot
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Updating existing task..." -ForegroundColor Yellow
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
}

Write-Host "Starting task..." -ForegroundColor Cyan
Stop-ScheduledTask  -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

Write-Host "Status:" -ForegroundColor Cyan
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime, LastTaskResult, NextRunTime

Write-Host "Listening on 9694?" -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort 9694 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table

Write-Host "Done. Test with:" -ForegroundColor Green
Write-Host "  curl -H 'Authorization: Bearer <helper-secret>' http://127.0.0.1:9694/health"
