#!/usr/bin/env python3
"""Desk2HA Agent Self-Healing Watchdog.

Monitors the running agent service and auto-fixes common problems:
- Version mismatch (installed != running)
- Service crashed / not responding
- Collector activation failures
- Permission issues (LocalSystem vs user context)

Can run as:
  1. One-shot: python tools/service-health.py --once
  2. Continuous: python tools/service-health.py --interval 300
  3. Scheduled Task: create via --install-task
  4. Auto-fix: python tools/service-health.py --auto-fix

Self-learning: records findings in tools/.health-history.json and reads
tools/.deploy-history.json for cross-correlation. Escalates severity for
recurring issues and tracks time-to-detect after deploys.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CONFIG_FILE = REPO_ROOT / "config.toml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
HISTORY_FILE = Path(__file__).parent / ".health-history.json"
DEPLOY_HISTORY_FILE = Path(__file__).parent / ".deploy-history.json"
SERVICE_NAME = "Desk2HAAgent"


# ── Config parsing ──────────────────────────────────────────────


def get_source_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"(.+?)"', text, re.MULTILINE)
    return m.group(1) if m else "unknown"


def get_config() -> dict:
    """Parse config.toml for port and token."""
    config: dict = {"port": 9693, "token": None}
    if not CONFIG_FILE.exists():
        return config
    text = CONFIG_FILE.read_text(encoding="utf-8")
    m = re.search(r"port\s*=\s*(\d+)", text)
    if m:
        config["port"] = int(m.group(1))
    m = re.search(r'auth_token\s*=\s*"(.+?)"', text)
    if m:
        config["token"] = m.group(1)
    return config


# ── Agent API ───────────────────────────────────────────────────


def agent_request(path: str, port: int, token: str | None) -> dict | None:
    """Make a request to the agent HTTP API."""
    url = f"http://localhost:{port}{path}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def get_nssm_status() -> str:
    """Get NSSM service status."""
    try:
        result = subprocess.run(
            ["nssm", "status", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def get_nssm_python() -> str | None:
    """Get Python path configured in NSSM."""
    try:
        result = subprocess.run(
            ["nssm", "get", SERVICE_NAME, "Application"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def get_installed_version(python_exe: str) -> str:
    """Check what version is installed in the Python env."""
    try:
        result = subprocess.run(
            [python_exe, "-c", "from desk2ha_agent import __version__; print(__version__)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ── Health history (self-learning) ──────────────────────────────


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_history(history: list[dict]) -> None:
    # Keep last 100 entries
    history = history[-100:]
    HISTORY_FILE.write_text(
        json.dumps(history, indent=2, default=str),
        encoding="utf-8",
    )


def record_finding(finding: dict) -> None:
    history = load_history()
    finding["timestamp"] = datetime.now(UTC).isoformat()
    history.append(finding)
    save_history(history)


def get_recurring_issues() -> dict[str, int]:
    """Analyze history for patterns that keep recurring."""
    history = load_history()
    counts: dict[str, int] = {}
    for entry in history:
        key = entry.get("issue", "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {k: v for k, v in counts.items() if v >= 2}


# ── Deploy history cross-correlation ────────────────────────────


def load_deploy_history() -> list[dict]:
    """Load deploy history for cross-correlation with health checks."""
    if DEPLOY_HISTORY_FILE.exists():
        try:
            return json.loads(DEPLOY_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def get_last_deploy() -> dict | None:
    """Return the most recent deploy entry, or None."""
    history = load_deploy_history()
    return history[-1] if history else None


def get_deploy_failure_patterns() -> dict[str, int]:
    """Analyze deploy history for recurring failure reasons."""
    history = load_deploy_history()
    counts: dict[str, int] = {}
    for entry in history:
        if entry.get("result") == "fail":
            reason = entry.get("failure_reason", "unknown")
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def calc_time_to_detect(health_ts_str: str) -> float | None:
    """Calculate seconds between last deploy and a health issue detection.

    Returns None if no deploy history or timestamp parsing fails.
    """
    last_deploy = get_last_deploy()
    if not last_deploy:
        return None
    deploy_ts_str = last_deploy.get("timestamp")
    if not deploy_ts_str:
        return None
    try:
        # Handle both timezone-aware and naive ISO timestamps
        deploy_ts = datetime.fromisoformat(deploy_ts_str.replace("Z", "+00:00"))
        health_ts = datetime.fromisoformat(health_ts_str.replace("Z", "+00:00"))
        # If one is naive and the other aware, make both naive for comparison
        if deploy_ts.tzinfo is None and health_ts.tzinfo is not None:
            health_ts = health_ts.replace(tzinfo=None)
        elif deploy_ts.tzinfo is not None and health_ts.tzinfo is None:
            deploy_ts = deploy_ts.replace(tzinfo=None)
        delta = (health_ts - deploy_ts).total_seconds()
        return delta if delta >= 0 else None
    except Exception:
        return None


def get_issue_severity(issue: str, health_history: list[dict]) -> str:
    """Determine severity based on recurrence in both health and deploy history.

    Returns: "critical", "high", "medium", or "low".
    """
    # Count occurrences in health history
    health_count = sum(1 for e in health_history if e.get("issue") == issue)

    # Count related failures in deploy history
    deploy_failures = get_deploy_failure_patterns()
    deploy_related = 0
    for reason, count in deploy_failures.items():
        # Check if the health issue correlates with deploy failures
        if _issues_correlate(issue, reason):
            deploy_related += count

    total = health_count + deploy_related

    if total >= 10:
        return "critical"
    if total >= 5:
        return "high"
    if total >= 2:
        return "medium"
    return "low"


def _issues_correlate(health_issue: str, deploy_reason: str) -> bool:
    """Check if a health issue and deploy failure reason are related."""
    # Normalize both strings for comparison
    h = health_issue.lower()
    d = deploy_reason.lower()

    correlations = [
        (["service", "crash", "not running"], ["service", "crash", "orphan"]),
        (["version", "mismatch", "stale"], ["version", "mismatch"]),
        (["port", "listen", "respond"], ["port", "in use", "listening"]),
        (["permission", "access"], ["permission", "access"]),
        (["pip", "install", "corrupt"], ["pip", "corrupt"]),
    ]

    for health_keywords, deploy_keywords in correlations:
        h_match = any(kw in h for kw in health_keywords)
        d_match = any(kw in d for kw in deploy_keywords)
        if h_match and d_match:
            return True
    return False


# ── Escalation and aggressive fixes ─────────────────────────────

# Confidence thresholds for auto-fix aggressiveness
CONFIDENCE_LOW = 0.3
CONFIDENCE_MEDIUM = 0.6
CONFIDENCE_HIGH = 0.8


def get_fix_confidence(issue: str) -> float:
    """Calculate confidence score for auto-fixing an issue based on history.

    Returns a float between 0.0 and 1.0.
    """
    health_history = load_history()
    issue_entries = [e for e in health_history if e.get("issue") == issue]
    if not issue_entries:
        return 0.0

    total_count = len(issue_entries)
    # Check if previous fixes for this issue were successful
    # (issue stopped appearing for a while after a fix)
    fixed_entries = [e for e in issue_entries if e.get("fix_applied")]

    # Base confidence from frequency
    confidence = min(total_count / 10.0, 0.5)

    # Boost from past successful fixes
    if fixed_entries:
        confidence += 0.3

    # Boost from deploy history correlation
    deploy_failures = get_deploy_failure_patterns()
    for reason in deploy_failures:
        if _issues_correlate(issue, reason):
            confidence += 0.1
            break

    return min(confidence, 1.0)


def get_escalated_fix(check_result: dict, severity: str) -> str | None:
    """Return more aggressive fix suggestions for high-severity issues."""
    issue = check_result.get("issue", check_result.get("check", "unknown"))
    base_fix = check_result.get("fix")

    if severity == "critical":
        if "service" in issue or "running" in issue:
            return (
                "CRITICAL: Service repeatedly failing. "
                "Kill all desk2ha processes, clean pip, force reinstall, restart service. "
                "Run: .\\tools\\deploy-agent.ps1 -Mode release"
            )
        if "version" in issue:
            return (
                "CRITICAL: Persistent version mismatch. "
                "Force reinstall with clean pip cache: "
                "pip install --force-reinstall --no-cache-dir -e . && nssm restart Desk2HAAgent"
            )
        if "permission" in issue:
            return (
                "CRITICAL: Recurring permission failures. "
                "Grant SYSTEM full control: "
                'icacls "<repo>" /grant "SYSTEM:(OI)(CI)F" /T'
            )
        return (
            f"CRITICAL: Recurring issue ({issue}). "
            f"Manual investigation required. Base fix: {base_fix}"
        )

    if severity == "high":
        if "service" in issue or "running" in issue:
            return (
                "HIGH: Service keeps failing. "
                "Try full redeploy: .\\tools\\deploy-agent.ps1 -Mode release"
            )
        if "version" in issue:
            return (
                "HIGH: Version mismatch recurring. "
                "Force reinstall: pip install --force-reinstall --no-cache-dir -e ."
            )
        return f"HIGH: Recurring issue. {base_fix}"

    return base_fix


# ── Health checks ───────────────────────────────────────────────


def check_service_running() -> dict:
    """Check if NSSM service is running."""
    status = get_nssm_status()
    running = "SERVICE_RUNNING" in status
    return {
        "check": "service_running",
        "ok": running,
        "status": status,
        "fix": "nssm start Desk2HAAgent" if not running else None,
    }


def check_agent_responding(port: int, token: str | None) -> dict:
    """Check if agent HTTP API is responding."""
    health = agent_request("/v1/health", port, token)
    if health:
        return {
            "check": "agent_responding",
            "ok": True,
            "version": health.get("agent_version"),
            "uptime": health.get("uptime_seconds"),
            "status": health.get("status"),
        }
    return {
        "check": "agent_responding",
        "ok": False,
        "fix": "Service may be starting or crashed. Check nssm logs.",
    }


def check_version_match(port: int, token: str | None) -> dict:
    """Check if running version matches source version."""
    source = get_source_version()
    health = agent_request("/v1/health", port, token)
    running = health.get("agent_version") if health else None

    python_exe = get_nssm_python()
    installed = get_installed_version(python_exe) if python_exe else "unknown"

    match = running == source
    result: dict = {
        "check": "version_match",
        "ok": match,
        "source": source,
        "installed": installed,
        "running": running,
    }

    if not match:
        if installed != source:
            result["issue"] = "installed_stale"
            result["fix"] = (
                f"Run: .\\tools\\deploy-agent.ps1 (installed={installed}, source={source})"
            )
        elif running != installed:
            result["issue"] = "running_stale"
            result["fix"] = f"Service restart needed (running={running}, installed={installed})"
        else:
            result["issue"] = "version_unknown"
            result["fix"] = "Agent not responding, cannot verify version"

    return result


def check_collectors(port: int, token: str | None) -> dict:
    """Check collector health and detect missing collectors."""
    info = agent_request("/v1/info", port, token)
    if not info:
        return {"check": "collectors", "ok": False, "fix": "Agent not responding"}

    collectors = info.get("collectors", [])
    unhealthy = [c for c in collectors if not c.get("healthy")]
    total = len(collectors)
    healthy = total - len(unhealthy)

    # Self-learning: check which collectors SHOULD be active
    # by reading plugin_registry.py
    expected_collectors = _discover_expected_collectors()
    active_names = {c["name"] for c in collectors}
    missing = expected_collectors - active_names

    result: dict = {
        "check": "collectors",
        "ok": len(unhealthy) == 0 and len(missing) == 0,
        "total": total,
        "healthy": healthy,
        "unhealthy": [c["name"] for c in unhealthy],
        "missing_from_registry": list(missing),
    }

    if unhealthy:
        result["fix"] = f"Unhealthy collectors: {', '.join(c['name'] for c in unhealthy)}"
    if missing:
        result["info"] = (
            f"Collectors registered but not active: {', '.join(missing)} "
            "(may be expected if hardware not present)"
        )

    return result


def check_permissions() -> dict:
    """Check if LocalSystem can read the source directory (editable install)."""
    python_exe = get_nssm_python()
    if not python_exe:
        return {"check": "permissions", "ok": False, "fix": "No NSSM service found"}

    # Check if editable install
    try:
        result = subprocess.run(
            [python_exe, "-m", "pip", "show", "desk2ha-agent"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if "Editable project location" in result.stdout:
            editable_path = None
            for line in result.stdout.splitlines():
                if line.startswith("Editable project location:"):
                    editable_path = line.split(":", 1)[1].strip()

            if editable_path:
                # Check SYSTEM ACL
                acl_result = subprocess.run(
                    ["icacls", editable_path],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                has_system = (
                    "SYSTEM" in acl_result.stdout or "NT AUTHORITY\\SYSTEM" in acl_result.stdout
                )
                fix_cmd = (
                    f'icacls "{editable_path}" /grant "SYSTEM:(OI)(CI)RX" /T'
                    if not has_system
                    else None
                )
                return {
                    "check": "permissions",
                    "ok": has_system,
                    "editable_path": editable_path,
                    "system_access": has_system,
                    "fix": fix_cmd,
                }
    except Exception as e:
        return {"check": "permissions", "ok": False, "error": str(e)}

    return {
        "check": "permissions",
        "ok": True,
        "note": "Non-editable install, no path access needed",
    }


def _discover_expected_collectors() -> set[str]:
    """Self-learning: scan plugin_registry.py to find all registered collectors."""
    registry = REPO_ROOT / "desk2ha_agent" / "plugin_registry.py"
    if not registry.exists():
        return set()

    text = registry.read_text(encoding="utf-8")
    # Find COLLECTOR_MODULES list entries
    names = set()
    for m in re.finditer(r'"desk2ha_agent\.collector\.(\w+)"', text):
        module = m.group(1)
        # Convert module name to collector display name (approximation)
        # e.g., vendor.dell_webcam -> dell_webcam
        parts = module.split(".")
        names.add(parts[-1] if parts else module)
    return names


# ── Auto-fix ────────────────────────────────────────────────────


def auto_fix(
    results: list[dict],
    *,
    dry_run: bool = False,
    use_confidence: bool = False,
) -> list[str]:
    """Attempt to auto-fix issues found during health check.

    When use_confidence is True, applies fixes automatically based on
    historical confidence scores. Higher-confidence fixes are applied
    more aggressively.
    """
    actions = []
    health_history = load_history()

    for r in results:
        if r.get("ok"):
            continue

        issue = r.get("issue", r.get("check", "unknown"))
        fix = r.get("fix")

        if not fix:
            continue

        # Determine severity and escalate fix if needed
        severity = get_issue_severity(issue, health_history)
        escalated_fix = get_escalated_fix(r, severity)
        if escalated_fix and escalated_fix != fix:
            fix = escalated_fix

        # Calculate time-to-detect for this finding
        now_iso = datetime.now(UTC).isoformat()
        ttd = calc_time_to_detect(now_iso)

        # Record the finding for self-learning
        finding: dict = {
            "issue": issue,
            "check": r["check"],
            "fix": fix,
            "severity": severity,
        }
        if ttd is not None:
            finding["time_to_detect_seconds"] = round(ttd, 1)
        record_finding(finding)

        if dry_run:
            conf_str = ""
            if use_confidence:
                confidence = get_fix_confidence(issue)
                conf_str = f" (confidence: {confidence:.0%})"
            actions.append(f"[DRY-RUN] [{severity.upper()}] Would fix '{issue}': {fix}{conf_str}")
            continue

        # Confidence-based gating for auto-fix mode
        if use_confidence:
            confidence = get_fix_confidence(issue)
            if confidence < CONFIDENCE_LOW:
                actions.append(
                    f"[SKIP] {issue}: confidence too low "
                    f"({confidence:.0%}), manual fix needed: {fix}"
                )
                continue
            if (
                confidence < CONFIDENCE_MEDIUM
                and r["check"] not in ("service_running", "version_match")
            ):
                actions.append(
                    f"[SKIP] {issue}: confidence {confidence:.0%}, "
                    f"only safe fixes at this level: {fix}"
                )
                continue
            print(f"  [AUTO-FIX] {issue} (confidence: {confidence:.0%}, severity: {severity})")
        else:
            print(f"  [FIX] {issue} (severity: {severity})")

        # Auto-fix: service not running
        if r["check"] == "service_running" and not r["ok"]:
            if severity in ("critical", "high"):
                # Aggressive fix: kill all desk2ha processes first
                print(
                    f"  [FIX] Killing all desk2ha processes "
                    f"before restart (severity: {severity})..."
                )
                _kill_desk2ha_processes()
                time.sleep(3)
            print(f"  [FIX] Starting service {SERVICE_NAME}...")
            subprocess.run(["nssm", "start", SERVICE_NAME], capture_output=True, timeout=30)
            time.sleep(5)
            actions.append(f"Started service {SERVICE_NAME} (severity: {severity})")

        # Auto-fix: version mismatch (running != installed) -> restart
        elif r.get("issue") == "running_stale":
            if severity in ("critical", "high"):
                print("  [FIX] Aggressive restart: stopping, killing orphans, starting...")
                subprocess.run(
                    ["nssm", "stop", SERVICE_NAME], capture_output=True, timeout=30
                )
                _kill_desk2ha_processes()
                time.sleep(3)
            else:
                print("  [FIX] Restarting service (stale version)...")
                subprocess.run(
                    ["nssm", "stop", SERVICE_NAME], capture_output=True, timeout=30
                )
                time.sleep(3)
            subprocess.run(["nssm", "start", SERVICE_NAME], capture_output=True, timeout=30)
            time.sleep(5)
            actions.append(
                f"Restarted service (was {r.get('running')}, need {r.get('installed')}) "
                f"[severity: {severity}]"
            )

        # Auto-fix: installed stale -> reinstall + restart
        elif r.get("issue") == "installed_stale":
            python_exe = get_nssm_python()
            if python_exe:
                print("  [FIX] Reinstalling package...")
                subprocess.run(
                    ["nssm", "stop", SERVICE_NAME], capture_output=True, timeout=30
                )
                time.sleep(3)

                pip_args = [python_exe, "-m", "pip", "install", "--no-cache-dir"]
                if severity in ("critical", "high"):
                    # Force reinstall for high severity
                    pip_args.append("--force-reinstall")
                    print("  [FIX] Using --force-reinstall due to severity...")
                pip_args.extend(["-e", str(REPO_ROOT)])

                subprocess.run(pip_args, capture_output=True, timeout=120)
                subprocess.run(
                    ["nssm", "start", SERVICE_NAME], capture_output=True, timeout=30
                )
                time.sleep(5)
                actions.append(
                    f"Reinstalled and restarted ({r.get('installed')} -> {r.get('source')}) "
                    f"[severity: {severity}]"
                )

        # Auto-fix: permissions
        elif r["check"] == "permissions" and not r["ok"] and use_confidence:
            editable_path = r.get("editable_path")
            if editable_path and get_fix_confidence(issue) >= CONFIDENCE_HIGH:
                print(f"  [FIX] Granting SYSTEM access to {editable_path}...")
                subprocess.run(
                    ["icacls", editable_path, "/grant", "SYSTEM:(OI)(CI)RX", "/T", "/Q"],
                    capture_output=True,
                    timeout=60,
                )
                actions.append(f"Fixed SYSTEM permissions on {editable_path}")

    return actions


def _kill_desk2ha_processes() -> int:
    """Kill all desk2ha-related Python processes. Returns count killed."""
    killed = 0
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process "
                    "-Filter \"Name LIKE 'python%'\" "
                    "| Where-Object { $_.CommandLine -like '*desk2ha*' } "
                    "| ForEach-Object { "
                    "Stop-Process -Id $_.ProcessId -Force "
                    "-ErrorAction SilentlyContinue; 1 } "
                    "| Measure-Object "
                    "| Select-Object -ExpandProperty Count"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            killed = int(result.stdout.strip())
    except Exception:
        pass
    return killed


# ── Main ────────────────────────────────────────────────────────


def check_duplicate_devices(port: int, token: str | None) -> dict:
    """Detect same physical device reported by multiple collectors."""
    data = agent_request("/v1/metrics", port, token)
    if not data:
        return {"check": "duplicates", "ok": True, "info": "Agent not responding"}

    peripherals = data.get("peripherals", [])
    if not isinstance(peripherals, list):
        return {"check": "duplicates", "ok": True, "info": "No peripherals"}

    from collections import defaultdict

    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in peripherals:
        model_raw = p.get("model", "")
        if isinstance(model_raw, dict):
            model = str(model_raw.get("value", "")).lower().strip()
        else:
            model = str(model_raw).lower().strip()
        mfg_raw = p.get("manufacturer", "")
        if isinstance(mfg_raw, dict):
            mfg = str(mfg_raw.get("value", "")).lower().strip()
        else:
            mfg = str(mfg_raw).lower().strip()
        dev_id = p.get("id", "?")
        if model:
            groups[(model, mfg)].append(dev_id)

    dupes = {k: v for k, v in groups.items() if len(v) > 1}
    if dupes:
        dupe_details = []
        for (model, mfg), ids in dupes.items():
            dupe_details.append(f"{model} ({mfg}): {ids}")
        return {
            "check": "duplicates",
            "ok": False,
            "issue": "duplicate_devices",
            "duplicates": dupe_details,
            "fix": (
                "Same device discovered by multiple collectors. "
                "Add VID:PID to _SKIP_VID_PIDS in usb_devices.py or fix global_id"
            ),
        }

    return {"check": "duplicates", "ok": True, "total_peripherals": len(peripherals)}


def check_metric_staleness(port: int, token: str | None) -> dict:
    """Check for metrics that haven't updated recently."""
    prom_url = f"http://localhost:{port}/v1/metrics/prometheus"
    req = urllib.request.Request(prom_url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
    except Exception:
        return {"check": "staleness", "ok": True, "info": "Prometheus endpoint unavailable"}

    now_ms = int(time.time() * 1000)
    stale: list[str] = []
    aging: list[str] = []

    for line in body.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rsplit(" ", 2)
        if len(parts) == 3:
            try:
                ts_ms = int(parts[2])
                age_min = (now_ms - ts_ms) / 60000
                metric_name = parts[0].split("{")[0]
                if age_min > 30:
                    stale.append(f"{metric_name} ({age_min:.0f}min)")
                elif age_min > 5:
                    aging.append(f"{metric_name} ({age_min:.0f}min)")
            except ValueError:
                pass

    if stale:
        return {
            "check": "staleness",
            "ok": False,
            "issue": "stale_metrics",
            "stale_metrics": stale,
            "aging_metrics": aging,
            "fix": "Metrics not updating — check WMI/DDC collector failures",
        }

    result: dict = {"check": "staleness", "ok": True}
    if aging:
        result["aging_metrics"] = aging
    return result


def check_display_power_state(port: int, token: str | None) -> dict:
    """Check that connected monitors don't falsely report power_state=off.

    A monitor whose devnode is started (physically connected) should have
    power_state 'on', not 'off'.  A persistent 'off' state for an active
    display indicates a DDC/CI or WMI detection issue.
    """
    data = agent_request("/v1/metrics", port, token)
    if not data:
        return {"check": "display_power", "ok": True, "info": "Agent not responding"}

    displays = data.get("displays", [])
    if not displays:
        return {"check": "display_power", "ok": True, "info": "No displays reported"}

    bad: list[str] = []
    for i, d in enumerate(displays):
        model_raw = d.get("model", {})
        model = model_raw.get("value", "?") if isinstance(model_raw, dict) else str(model_raw)
        ps_raw = d.get("power_state", {})
        ps = ps_raw.get("value", "") if isinstance(ps_raw, dict) else str(ps_raw)
        if ps == "off":
            bad.append(f"display.{i} ({model})")

    if bad:
        return {
            "check": "display_power",
            "ok": False,
            "issue": "display_power_off",
            "displays": bad,
            "fix": (
                "Connected display(s) report power_state=off. "
                "Check WMI PnPEntity detection in ddcci.py "
                "and ensure _get_active_monitors_wmi() works under LocalSystem."
            ),
        }

    return {"check": "display_power", "ok": True, "displays_checked": len(displays)}


def check_multi_agent(port: int, token: str | None) -> dict:
    """Detect multiple desk2ha agent processes listening on different ports.

    A ghost agent on a different port (e.g. Desk2HAHelper on 9694) can cause
    HA to connect to the wrong instance, leading to stale/wrong entities.
    """
    import socket

    # Check common neighboring ports for other agents
    scan_ports = [p for p in range(9690, 9700) if p != port]
    extra_agents: list[str] = []

    for p in scan_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", p)) == 0:
                # Port is open — check if it's a desk2ha agent
                try:
                    resp = agent_request("/v1/health", p, token)
                    if resp and "agent_version" in resp:
                        extra_agents.append(
                            f"port {p}: v{resp.get('agent_version')} "
                            f"device_key={resp.get('device_key')}"
                        )
                except Exception:
                    # Try without token
                    try:
                        req = urllib.request.Request(f"http://localhost:{p}/v1/health")
                        with urllib.request.urlopen(req, timeout=2) as r:
                            body = json.loads(r.read())
                            if "agent_version" in body:
                                extra_agents.append(f"port {p}: agent (different token)")
                    except Exception:
                        pass
            sock.close()
        except Exception:
            pass

    if extra_agents:
        return {
            "check": "multi_agent",
            "ok": False,
            "issue": "multiple_agents",
            "extra_agents": extra_agents,
            "fix": (
                "Multiple desk2ha agents detected. The HA integration may "
                "connect to the wrong one. Kill ghost agents and verify "
                "HA config entry points to port " + str(port) + ". "
                "Check NSSM services: Desk2HAAgent (main) vs Desk2HAHelper."
            ),
        }

    return {"check": "multi_agent", "ok": True}


def run_checks(config: dict) -> list[dict]:
    port = config["port"]
    token = config["token"]

    checks = [
        check_service_running(),
        check_agent_responding(port, token),
        check_version_match(port, token),
        check_collectors(port, token),
        check_permissions(),
        check_duplicate_devices(port, token),
        check_metric_staleness(port, token),
        check_display_power_state(port, token),
        check_multi_agent(port, token),
    ]
    return checks


def print_results(results: list[dict]) -> int:
    print()
    print("  ========================================")
    print("  DESK2HA AGENT HEALTH CHECK")
    print("  ========================================")
    print()

    health_history = load_history()
    fails = 0
    for r in results:
        icon = "[OK]" if r["ok"] else "[!!]"
        name = r["check"]

        detail_parts = []
        for k, v in r.items():
            if k in ("check", "ok", "fix", "issue"):
                continue
            detail_parts.append(f"{k}={v}")
        detail = ", ".join(detail_parts)

        status = "PASS" if r["ok"] else "FAIL"
        print(f"  {icon} {name}: {status}")
        if detail:
            print(f"      {detail}")

        if not r["ok"]:
            issue = r.get("issue", r.get("check", "unknown"))
            severity = get_issue_severity(issue, health_history)

            # Show escalated fix for recurring issues
            fix_msg = get_escalated_fix(r, severity)
            if fix_msg:
                print(f"      FIX [{severity.upper()}]: {fix_msg}")
            elif r.get("fix"):
                print(f"      FIX: {r['fix']}")
            fails += 1

        if r.get("info"):
            print(f"      INFO: {r['info']}")

    # Show recurring issues from health history
    recurring = get_recurring_issues()
    if recurring:
        print()
        print("  RECURRING HEALTH ISSUES (from history):")
        for issue, count in sorted(recurring.items(), key=lambda x: -x[1]):
            severity = get_issue_severity(issue, health_history)
            print(f"    {issue}: {count} occurrences [{severity.upper()}]")

    # Show deploy failure patterns (cross-correlation)
    deploy_failures = get_deploy_failure_patterns()
    if deploy_failures:
        print()
        print("  DEPLOY FAILURE PATTERNS (cross-correlation):")
        for reason, count in sorted(deploy_failures.items(), key=lambda x: -x[1]):
            print(f"    {count}x  {reason}")

    # Show time-to-detect stats
    _print_time_to_detect_stats(health_history)

    # Show last deploy info
    last_deploy = get_last_deploy()
    if last_deploy:
        print()
        ts = last_deploy.get("timestamp", "?")
        ver = last_deploy.get("source_version", "?")
        res = last_deploy.get("result", "?")
        print(f"  LAST DEPLOY: v{ver} ({res}) at {ts[:19]}")

    print()
    return fails


def _print_time_to_detect_stats(health_history: list[dict]) -> None:
    """Print time-to-detect statistics from health history."""
    ttd_entries = [
        e for e in health_history if e.get("time_to_detect_seconds") is not None
    ]
    if not ttd_entries:
        return

    ttd_values = [e["time_to_detect_seconds"] for e in ttd_entries]
    avg_ttd = sum(ttd_values) / len(ttd_values)
    min_ttd = min(ttd_values)
    max_ttd = max(ttd_values)

    print()
    print("  TIME-TO-DETECT (after deploy):")
    print(
        f"    Avg: {avg_ttd:.0f}s  Min: {min_ttd:.0f}s  "
        f"Max: {max_ttd:.0f}s  Samples: {len(ttd_values)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Desk2HA Agent Health Watchdog")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument(
        "--interval", type=int, default=0, help="Run continuously with N second interval"
    )
    parser.add_argument("--auto-fix", action="store_true", help="Attempt to auto-fix issues")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what auto-fix would do without doing it"
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Determine if confidence-based auto-fix should be used
    use_confidence = args.auto_fix

    config = get_config()

    if args.interval > 0:
        print(f"  Running health checks every {args.interval}s (Ctrl+C to stop)")
        while True:
            results = run_checks(config)
            fails = print_results(results)
            if fails > 0 and args.auto_fix:
                actions = auto_fix(
                    results, dry_run=args.dry_run, use_confidence=use_confidence
                )
                for a in actions:
                    print(f"  -> {a}")
            time.sleep(args.interval)
    else:
        results = run_checks(config)

        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            fails = print_results(results)

        if fails > 0 and args.auto_fix:
            print("  ATTEMPTING AUTO-FIX (confidence-based)...")
            actions = auto_fix(
                results, dry_run=args.dry_run, use_confidence=use_confidence
            )
            for a in actions:
                print(f"  -> {a}")

            if actions and not args.dry_run:
                print()
                print("  Re-checking after fixes...")
                time.sleep(5)
                results2 = run_checks(config)
                fails2 = print_results(results2)
                return 0 if fails2 == 0 else 1

        return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
