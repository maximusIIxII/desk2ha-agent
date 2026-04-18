#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Deploy desk2ha-agent: install package, manage NSSM service, verify version.

.DESCRIPTION
    Self-healing deployment script that:
    1. Detects source version from pyproject.toml
    2. Installs package (editable or regular) into the CORRECT Python environment
    3. Stops/starts NSSM service
    4. Verifies running agent reports the expected version
    5. Auto-diagnoses and fixes common problems (stale service, wrong Python, permission issues)
    6. Records deploy history and learns from past failures

.PARAMETER Mode
    "editable" (default) = pip install -e . (dev workflow)
    "release"            = pip install .    (clean install for releases)

.PARAMETER ServiceName
    NSSM service name. Default: Desk2HAAgent

.PARAMETER SkipVerify
    Skip post-deploy version verification.

.PARAMETER History
    Show deploy history summary and exit.

.EXAMPLE
    .\tools\deploy-agent.ps1
    .\tools\deploy-agent.ps1 -Mode release
    .\tools\deploy-agent.ps1 -Mode editable -ServiceName Desk2HAAgent
    .\tools\deploy-agent.ps1 -History
#>

param(
    [ValidateSet("editable", "release")]
    [string]$Mode = "editable",
    [string]$ServiceName = "Desk2HAAgent",
    [switch]$SkipVerify,
    [switch]$History
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ── Helpers ──────────────────────────────────────────────────────

function Write-Step($msg) { Write-Host "  [*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }

function Get-SourceVersion {
    $pyproject = Join-Path $PSScriptRoot "..\pyproject.toml"
    $content = Get-Content $pyproject -Raw
    if ($content -match 'version\s*=\s*"([^"]+)"') {
        return $Matches[1]
    }
    throw "Cannot parse version from pyproject.toml"
}

function Get-ServicePython {
    try {
        $app = nssm get $ServiceName Application 2>$null
        return $app.Trim()
    } catch {
        return $null
    }
}

function Get-AgentPort {
    $configPath = Join-Path $PSScriptRoot "..\config.toml"
    if (Test-Path $configPath) {
        $content = Get-Content $configPath -Raw
        if ($content -match '\[http\][\s\S]*?port\s*=\s*(\d+)') {
            return [int]$Matches[1]
        }
    }
    return 9693  # default
}

function Get-AgentToken {
    $configPath = Join-Path $PSScriptRoot "..\config.toml"
    if (Test-Path $configPath) {
        $content = Get-Content $configPath -Raw
        if ($content -match 'auth_token\s*=\s*"([^"]+)"') {
            return $Matches[1]
        }
    }
    return $null
}

function Test-AgentVersion {
    param([string]$ExpectedVersion, [int]$Port, [string]$Token)

    $headers = @{}
    if ($Token) { $headers["Authorization"] = "Bearer $Token" }

    try {
        $response = Invoke-RestMethod -Uri "http://localhost:$Port/v1/health" -Headers $headers -TimeoutSec 10
        return @{
            Running  = $true
            Version  = $response.agent_version
            Status   = $response.status
            Uptime   = $response.uptime_seconds
            Match    = ($response.agent_version -eq $ExpectedVersion)
        }
    } catch {
        return @{
            Running = $false
            Version = $null
            Status  = "unreachable"
            Uptime  = 0
            Match   = $false
        }
    }
}

# ── Deploy history (self-learning) ──────────────────────────────

$script:DeployHistoryFile = Join-Path $PSScriptRoot ".deploy-history.json"
$script:DeployStartTime = Get-Date

function Get-DeployHistory {
    if (Test-Path $script:DeployHistoryFile) {
        try {
            $raw = Get-Content $script:DeployHistoryFile -Raw -ErrorAction Stop
            if ($raw) {
                return @(ConvertFrom-Json $raw)
            }
        } catch {
            # Corrupted file — start fresh
        }
    }
    return @()
}

function Save-DeployHistory($entries) {
    # Keep last 100 entries
    if ($entries.Count -gt 100) {
        $entries = @($entries | Select-Object -Last 100)
    }
    $entries | ConvertTo-Json -Depth 10 | Set-Content $script:DeployHistoryFile -Encoding UTF8
}

function Add-DeployHistoryEntry {
    param(
        [string]$SourceVersion,
        [string]$Result,
        [string]$FailureReason = "",
        [string]$FixApplied = ""
    )
    $elapsed = ((Get-Date) - $script:DeployStartTime).TotalSeconds
    $entry = [PSCustomObject]@{
        timestamp        = (Get-Date).ToString("o")
        source_version   = $SourceVersion
        result           = $Result
        failure_reason   = $FailureReason
        fix_applied      = $FixApplied
        duration_seconds = [math]::Round($elapsed, 1)
    }
    $history = @(Get-DeployHistory)
    $history += $entry
    Save-DeployHistory $history
}

function Get-LearnedPatterns {
    <#
    .SYNOPSIS
        Analyze deploy history for recurring failure patterns and return
        pre-emptive fixes to apply.
    #>
    $history = @(Get-DeployHistory)
    if ($history.Count -eq 0) { return @() }

    $patterns = @()
    $failures = @($history | Where-Object { $_.result -eq "fail" })

    # Pattern: orphaned process failures
    $orphanCount = @($failures | Where-Object { $_.failure_reason -like "*orphan*" }).Count
    if ($orphanCount -ge 1) {
        $patterns += [PSCustomObject]@{
            pattern = "orphaned_process"
            count   = $orphanCount
            action  = "kill_all_desk2ha"
            reason  = "History shows $orphanCount orphaned-process failure(s)"
        }
    }

    # Pattern: port in use failures
    $portCount = @($failures | Where-Object { $_.failure_reason -like "*port*in*use*" -or $_.failure_reason -like "*port*" }).Count
    if ($portCount -ge 1) {
        $patterns += [PSCustomObject]@{
            pattern = "port_in_use"
            count   = $portCount
            action  = "extended_port_wait"
            reason  = "History shows $portCount port-in-use failure(s)"
        }
    }

    # Pattern: corrupted pip failures
    $pipCount = @($failures | Where-Object { $_.failure_reason -like "*corrupt*" -or $_.failure_reason -like "*pip*" }).Count
    if ($pipCount -ge 1) {
        $patterns += [PSCustomObject]@{
            pattern = "corrupted_pip"
            count   = $pipCount
            action  = "clean_pip_remnants"
            reason  = "History shows $pipCount corrupted-pip failure(s)"
        }
    }

    return $patterns
}

function Apply-LearnedFixes {
    param($Patterns, [string]$PythonExe, [int]$Port)

    $fixesApplied = @()

    foreach ($p in $Patterns) {
        switch ($p.action) {
            "kill_all_desk2ha" {
                Write-Step "  [LEARNED] $($p.reason) -> pre-emptively killing all desk2ha processes"
                $ErrorActionPreference = "Continue"
                Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
                    Where-Object { $_.CommandLine -like "*desk2ha*" } |
                    ForEach-Object {
                        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                    }
                $ErrorActionPreference = "Stop"
                Start-Sleep -Seconds 2
                $fixesApplied += "killed orphaned processes"
            }
            "extended_port_wait" {
                Write-Step "  [LEARNED] $($p.reason) -> extended port cleanup"
                $portHolder = netstat -ano 2>$null | Select-String ":$Port\s" | Select-String "LISTENING"
                if ($portHolder) {
                    # Extract PID and kill the port holder
                    foreach ($line in $portHolder) {
                        if ($line -match '\s(\d+)\s*$') {
                            $pid = [int]$Matches[1]
                            Write-Warn "    Killing port $Port holder PID $pid"
                            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                        }
                    }
                    Start-Sleep -Seconds 5
                }
                $fixesApplied += "extended port wait/cleanup"
            }
            "clean_pip_remnants" {
                Write-Step "  [LEARNED] $($p.reason) -> aggressive pip cleanup"
                if ($PythonExe) {
                    $sp = & $PythonExe -c "import site; print(site.getsitepackages()[0])" 2>$null
                    if ($sp -and (Test-Path $sp)) {
                        $corrupted = Get-ChildItem $sp -Directory -Filter "~*desk2ha*" -ErrorAction SilentlyContinue
                        foreach ($c in $corrupted) {
                            Remove-Item $c.FullName -Recurse -Force -ErrorAction SilentlyContinue
                        }
                        # Also clean __pycache__ and .egg-info remnants
                        Get-ChildItem $sp -Directory -Filter "*desk2ha*egg*" -ErrorAction SilentlyContinue |
                            ForEach-Object {
                                Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
                            }
                    }
                }
                $fixesApplied += "cleaned pip remnants"
            }
        }
    }

    return $fixesApplied
}

function Show-DeployHistory {
    $history = @(Get-DeployHistory)

    Write-Host ""
    Write-Host "  ========================================" -ForegroundColor White
    Write-Host "  DEPLOY HISTORY" -ForegroundColor White
    Write-Host "  ========================================" -ForegroundColor White
    Write-Host ""

    if ($history.Count -eq 0) {
        Write-Host "  No deploy history recorded yet." -ForegroundColor Gray
        Write-Host ""
        return
    }

    $successes = @($history | Where-Object { $_.result -eq "success" }).Count
    $failures  = @($history | Where-Object { $_.result -eq "fail" }).Count
    $total     = $history.Count

    Write-Host "  Total deploys: $total  (success: $successes, fail: $failures)" -ForegroundColor White

    if ($total -gt 0) {
        $avgDuration = ($history | Measure-Object -Property duration_seconds -Average).Average
        Write-Host "  Avg duration:  $([math]::Round($avgDuration, 1))s" -ForegroundColor White
    }

    # Show failure patterns
    $failEntries = @($history | Where-Object { $_.result -eq "fail" })
    if ($failEntries.Count -gt 0) {
        Write-Host ""
        Write-Host "  Failure patterns:" -ForegroundColor Yellow
        $reasons = @{}
        foreach ($f in $failEntries) {
            $r = if ($f.failure_reason) { $f.failure_reason } else { "unknown" }
            if ($reasons.ContainsKey($r)) { $reasons[$r]++ } else { $reasons[$r] = 1 }
        }
        foreach ($kv in $reasons.GetEnumerator() | Sort-Object -Property Value -Descending) {
            Write-Host "    $($kv.Value)x  $($kv.Key)" -ForegroundColor Yellow
        }
    }

    # Show recent deploys (last 10)
    Write-Host ""
    Write-Host "  Recent deploys (last 10):" -ForegroundColor White
    $recent = @($history | Select-Object -Last 10)
    foreach ($entry in $recent) {
        $icon = if ($entry.result -eq "success") { "[OK]" } else { "[!!]" }
        $color = if ($entry.result -eq "success") { "Green" } else { "Red" }
        $ts = if ($entry.timestamp) { $entry.timestamp.Substring(0, 19) } else { "?" }
        $dur = if ($entry.duration_seconds) { "$($entry.duration_seconds)s" } else { "?" }
        Write-Host "    $icon $ts  v$($entry.source_version)  $($entry.result)  ($dur)" -ForegroundColor $color
        if ($entry.failure_reason) {
            Write-Host "        Reason: $($entry.failure_reason)" -ForegroundColor Gray
        }
        if ($entry.fix_applied) {
            Write-Host "        Fix: $($entry.fix_applied)" -ForegroundColor Gray
        }
    }

    # Show learned patterns
    $patterns = Get-LearnedPatterns
    if ($patterns.Count -gt 0) {
        Write-Host ""
        Write-Host "  Learned pre-emptive fixes:" -ForegroundColor Cyan
        foreach ($p in $patterns) {
            Write-Host "    - $($p.reason) -> $($p.action)" -ForegroundColor Cyan
        }
    }

    Write-Host ""
}

# ── Handle --History flag ──────────────────────────────────────

if ($History) {
    Show-DeployHistory
    exit 0
}

# ── Main ─────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ========================================" -ForegroundColor White
Write-Host "  DESK2HA AGENT DEPLOY" -ForegroundColor White
Write-Host "  ========================================" -ForegroundColor White
Write-Host ""

$sourceVersion = Get-SourceVersion
$pythonExe = Get-ServicePython
$agentPort = Get-AgentPort
$agentToken = Get-AgentToken
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Step "Source version: v$sourceVersion"
Write-Step "Python exe: $pythonExe"
Write-Step "Agent port: $agentPort"
Write-Step "Deploy mode: $Mode"
Write-Step "Repo: $repoRoot"

# ── Self-learning: analyze history and apply learned fixes ──────

$deployHistory = @(Get-DeployHistory)
$learnedPatterns = @(Get-LearnedPatterns)

if ($deployHistory.Count -gt 0) {
    Write-Step "Learned from $($deployHistory.Count) previous deploy(s)"
}

$preFixesApplied = @()
if ($learnedPatterns.Count -gt 0) {
    Write-Step "Applying $($learnedPatterns.Count) learned pre-emptive fix(es)..."
    $preFixesApplied = @(Apply-LearnedFixes -Patterns $learnedPatterns -PythonExe $pythonExe -Port $agentPort)
}

# ── Pre-flight checks ───────────────────────────────────────────

# Clean up corrupted pip remnants (~ prefix directories)
$sitePackages = & $pythonExe -c "import site; print(site.getsitepackages()[0])" 2>$null
if ($sitePackages -and (Test-Path $sitePackages)) {
    $corrupted = Get-ChildItem $sitePackages -Directory -Filter "~*desk2ha*" -ErrorAction SilentlyContinue
    if ($corrupted) {
        Write-Warn "Cleaning corrupted pip remnants..."
        foreach ($c in $corrupted) {
            Write-Host "    Removing: $($c.Name)" -ForegroundColor Yellow
            Remove-Item $c.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not $pythonExe) {
    Write-Fail "NSSM service '$ServiceName' not found. Create it first:"
    Write-Host "    nssm install $ServiceName `"<python.exe>`" `"-m desk2ha_agent -c <config.toml>`""
    Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "fail" -FailureReason "nssm service not found" -FixApplied ($preFixesApplied -join "; ")
    exit 1
}

if (-not (Test-Path $pythonExe)) {
    Write-Fail "Python not found at: $pythonExe"
    Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "fail" -FailureReason "python exe not found: $pythonExe" -FixApplied ($preFixesApplied -join "; ")
    exit 1
}

# Check current state before deploy
Write-Step "Checking current agent state..."
$before = Test-AgentVersion -ExpectedVersion $sourceVersion -Port $agentPort -Token $agentToken
if ($before.Running) {
    if ($before.Match) {
        Write-Ok "Agent already running v$sourceVersion (uptime: $($before.Uptime)s)"
        if (-not $SkipVerify) {
            Write-Host "  Nothing to deploy. Use -Mode release to force reinstall." -ForegroundColor Gray
            Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "success" -FailureReason "" -FixApplied "already running"
            exit 0
        }
    } else {
        Write-Warn "Agent running v$($before.Version) but source is v$sourceVersion -> deploying update"
    }
} else {
    Write-Warn "Agent not responding -> will install and start"
}

# ── Step 1: Stop service ────────────────────────────────────────

Write-Step "Stopping service '$ServiceName'..."
try {
    $status = nssm status $ServiceName 2>$null
    if ($status -match "SERVICE_RUNNING|SERVICE_START_PENDING|SERVICE_STOP_PENDING") {
        nssm stop $ServiceName 2>$null | Out-Null
        Start-Sleep -Seconds 3
    }

    # Always kill ALL desk2ha python processes regardless of service status
    # This catches orphaned processes that nssm lost track of
    Write-Step "Killing any orphaned desk2ha processes..."
    $killed = 0
    $ErrorActionPreference = "Continue"
    Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*desk2ha*" } |
        ForEach-Object {
            Write-Host "    Killing PID $($_.ProcessId): $($_.CommandLine.Substring(0, [Math]::Min(80, $_.CommandLine.Length)))..." -ForegroundColor Gray
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
        }
    $ErrorActionPreference = "Stop"

    if ($killed -gt 0) {
        Write-Warn "Killed $killed orphaned process(es)"
        Start-Sleep -Seconds 3
    }

    # Verify port is free (use extended wait if learned from history)
    $portWaitSeconds = 3
    if ($preFixesApplied -contains "extended port wait/cleanup") {
        $portWaitSeconds = 8
    }
    $portInUse = netstat -ano 2>$null | Select-String ":$agentPort\s" | Select-String "LISTENING|ABH"
    if ($portInUse) {
        Write-Warn "Port $agentPort still in use after cleanup:"
        Write-Host "    $portInUse" -ForegroundColor Gray
        Start-Sleep -Seconds $portWaitSeconds
    }

    Write-Ok "Service stopped and processes cleaned up"
} catch {
    Write-Warn "Could not stop service: $_"
}

# ── Step 2: Install package ─────────────────────────────────────

Write-Step "Installing desk2ha-agent ($Mode)..."

$pipArgs = @("-m", "pip", "install", "--no-cache-dir")
if ($Mode -eq "editable") {
    $pipArgs += @("-e", $repoRoot)
} else {
    $pipArgs += $repoRoot
}

$ErrorActionPreference = "Continue"
$pipResult = & $pythonExe @pipArgs 2>&1
$pipExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($pipExitCode -ne 0) {
    Write-Fail "pip install failed (exit $pipExitCode):"
    $pipResult | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    $failReason = "pip install failed (exit $pipExitCode)"
    # Check if it looks like a corruption issue
    $pipOutput = ($pipResult | Out-String)
    if ($pipOutput -like "*corrupt*" -or $pipOutput -like "*~desk2ha*") {
        $failReason = "corrupted pip install (exit $pipExitCode)"
    }
    Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "fail" -FailureReason $failReason -FixApplied ($preFixesApplied -join "; ")
    exit 1
}
# Show warnings but don't fail on them
$pipResult | ForEach-Object {
    $line = $_.ToString()
    if ($line -match "WARNING") { Write-Warn $line }
}
Write-Ok "Package installed"

# ── Step 3: Verify installed version matches source ─────────────

Write-Step "Verifying installed version..."
$installedVersion = & $pythonExe -c "from desk2ha_agent import __version__; print(__version__)" 2>$null
if ($installedVersion -ne $sourceVersion) {
    Write-Warn "Installed version '$installedVersion' != source '$sourceVersion'"
    Write-Step "Attempting pip install with --force-reinstall..."
    & $pythonExe -m pip install --force-reinstall --no-cache-dir -e $repoRoot 2>&1 | Out-Null
    $installedVersion = & $pythonExe -c "from desk2ha_agent import __version__; print(__version__)" 2>$null
    if ($installedVersion -ne $sourceVersion) {
        Write-Fail "Version mismatch persists after force reinstall: $installedVersion != $sourceVersion"
        Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "fail" -FailureReason "version mismatch after force reinstall: installed=$installedVersion" -FixApplied ($preFixesApplied -join "; ")
        exit 1
    }
}
Write-Ok "Installed version: v$installedVersion"

# ── Step 4: Start service ───────────────────────────────────────

Write-Step "Starting service '$ServiceName'..."
nssm start $ServiceName 2>$null | Out-Null
Start-Sleep -Seconds 5

$status = nssm status $ServiceName 2>$null
if ($status -notmatch "SERVICE_RUNNING") {
    Write-Fail "Service failed to start. Status: $status"
    Write-Step "Checking service logs..."
    nssm get $ServiceName AppStdout 2>$null
    nssm get $ServiceName AppStderr 2>$null
    Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "fail" -FailureReason "service failed to start: $status" -FixApplied ($preFixesApplied -join "; ")
    exit 1
}
Write-Ok "Service running"

# ── Step 5: Verify running version ──────────────────────────────

if (-not $SkipVerify) {
    Write-Step "Waiting for agent to be ready..."

    $maxRetries = 6
    $retryDelay = 5
    $verified = $false

    for ($i = 1; $i -le $maxRetries; $i++) {
        $after = Test-AgentVersion -ExpectedVersion $sourceVersion -Port $agentPort -Token $agentToken
        if ($after.Running -and $after.Match) {
            $verified = $true
            break
        }
        if ($after.Running -and -not $after.Match) {
            Write-Warn "Attempt $i/$maxRetries : agent reports v$($after.Version), expected v$sourceVersion"
        } else {
            Write-Warn "Attempt $i/$maxRetries : agent not responding yet..."
        }
        Start-Sleep -Seconds $retryDelay
    }

    if ($verified) {
        Write-Ok "Agent running v$sourceVersion (uptime: $($after.Uptime)s)"

        # Show collector summary
        try {
            $headers = @{}
            if ($agentToken) { $headers["Authorization"] = "Bearer $agentToken" }
            $info = Invoke-RestMethod -Uri "http://localhost:$agentPort/v1/info" -Headers $headers -TimeoutSec 10
            $collectorCount = ($info.collectors | Measure-Object).Count
            $healthyCount = ($info.collectors | Where-Object { $_.healthy -eq $true } | Measure-Object).Count
            Write-Ok "Collectors: $healthyCount/$collectorCount healthy"
            $info.collectors | ForEach-Object {
                $icon = if ($_.healthy) { "+" } else { "!" }
                $color = if ($_.healthy) { "Green" } else { "Yellow" }
                Write-Host "    [$icon] $($_.name) ($($_.tier))" -ForegroundColor $color
            }
        } catch {
            Write-Warn "Could not fetch collector info: $_"
        }

        # Record success
        Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "success" -FixApplied ($preFixesApplied -join "; ")

    } else {
        Write-Fail "Agent did not reach expected version v$sourceVersion after $($maxRetries * $retryDelay)s"

        # Determine failure reason for history
        $historyFailReason = "agent not responding after start"
        if ($after -and $after.Running -and -not $after.Match) {
            $historyFailReason = "version mismatch: running=$($after.Version) expected=$sourceVersion"
        }

        # Check for orphaned processes to refine failure reason
        $orphans = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like "*desk2ha*" }
        if (-not $orphans) {
            $historyFailReason = "orphaned process / service crash after start"
        }

        # Check port
        $portCheck = netstat -ano 2>$null | Select-String ":$agentPort\s" | Select-String "LISTENING"
        if (-not $portCheck) {
            $historyFailReason = "port $agentPort not listening after start"
        }

        Write-Step "Self-diagnosis:"

        # Self-diagnosis: comprehensive check
        Write-Step "Running comprehensive self-diagnosis..."

        # 1. Check all running desk2ha processes
        $procs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like "*desk2ha*" }
        if ($procs) {
            foreach ($p in $procs) {
                Write-Host "    Process PID $($p.ProcessId): $($p.CommandLine)" -ForegroundColor Gray
            }
        } else {
            Write-Fail "    No desk2ha_agent process found - service may have crashed"
        }

        # 2. Check who owns the port
        $portInfo = netstat -ano 2>$null | Select-String ":$agentPort\s" | Select-String "LISTENING|ABH"
        if ($portInfo) {
            Write-Host "    Port $agentPort owner: $portInfo" -ForegroundColor Gray
            if ($historyFailReason -notlike "*port*") {
                $historyFailReason = "port $agentPort in use by another process"
            }
        }

        # 3. Check for multiple Python installations with desk2ha
        Write-Step "Scanning for desk2ha in all Python envs..."
        $pythonPaths = @(
            "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe",
            "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe",
            "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe"
        )
        foreach ($py in $pythonPaths) {
            if (Test-Path $py) {
                $ErrorActionPreference = "Continue"
                $ver = & $py -c "from desk2ha_agent import __version__; print(__version__)" 2>$null
                $ErrorActionPreference = "Stop"
                if ($ver) {
                    Write-Host "    $py -> v$ver" -ForegroundColor Gray
                }
            }
        }

        # 4. Check for corrupted pip installations
        $sitePackages = & $pythonExe -c "import site; print(site.getsitepackages()[0])" 2>$null
        if ($sitePackages) {
            $corrupted = Get-ChildItem $sitePackages -Directory -Filter "~*desk2ha*" -ErrorAction SilentlyContinue
            if ($corrupted) {
                Write-Warn "    Corrupted pip remnants found:"
                foreach ($c in $corrupted) {
                    Write-Host "      $($c.FullName)" -ForegroundColor Yellow
                    Write-Step "    Auto-removing corrupted directory..."
                    Remove-Item $c.FullName -Recurse -Force -ErrorAction SilentlyContinue
                }
                Write-Ok "    Cleaned up corrupted remnants. Re-run deploy."
                $historyFailReason = "corrupted pip remnants found"
            }
        }

        # 5. Check permissions
        $testFile = Join-Path $repoRoot "pyproject.toml"
        $acl = Get-Acl $testFile -ErrorAction SilentlyContinue
        if ($acl) {
            $systemAccess = $acl.Access | Where-Object { $_.IdentityReference -match "SYSTEM" }
            if (-not $systemAccess) {
                Write-Warn "    LocalSystem may not have read access to $repoRoot"
                Write-Step "    Auto-fixing permissions..."
                icacls $repoRoot /grant "SYSTEM:(OI)(CI)RX" /T /Q 2>$null
                Write-Ok "    Permissions fixed. Re-run deploy."
            }
        }

        # 6. Check NSSM service logs
        $stderr = nssm get $ServiceName AppStderr 2>$null
        if ($stderr -and (Test-Path $stderr)) {
            $lastLines = Get-Content $stderr -Tail 10 -ErrorAction SilentlyContinue
            if ($lastLines) {
                Write-Step "Last 10 lines from service stderr:"
                $lastLines | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
            }
        }

        # Record failure
        Add-DeployHistoryEntry -SourceVersion $sourceVersion -Result "fail" -FailureReason $historyFailReason -FixApplied ($preFixesApplied -join "; ")

        exit 1
    }
}

# ── Done ─────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  DEPLOY COMPLETE: v$sourceVersion" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""
