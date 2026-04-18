#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Create a Windows Scheduled Task for Desk2HAHelper (replaces NSSM service).
    Runs under the user's interactive session so DDC/CI has desktop access.
#>

$python = "C:\Users\Precision 5770\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$helperArgs = "-m desk2ha_agent.helper -c C:\dev\desk2ha\desk2ha-agent\config.toml --log-dir C:\dev\desk2ha\desk2ha-agent\logs"
$workDir = "C:\dev\desk2ha\desk2ha-agent"
$taskName = "Desk2HAHelper"

# Remove existing task if any
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create task components
$action = New-ScheduledTaskAction -Execute $python -Argument $helperArgs -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "Precision 5770"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Description "Desk2HA Helper - DDC/CI and elevated metrics collector (runs in user session)"

Write-Host "Task '$taskName' registered. Starting now..."
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $taskName
Write-Host "Task state: $($task.State)"
