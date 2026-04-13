"""Fleet policy receiver and compliance checker.

Receives policies from the HA coordinator via the /v1/commands API,
caches them locally, and reports compliance status in metrics.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

CommandExecutor = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]

logger = logging.getLogger(__name__)


class PolicyKind(StrEnum):
    """Supported policy types."""

    DISPLAY = "DisplayPolicy"
    AGENT = "AgentPolicy"
    SECURITY = "SecurityPolicy"
    UPDATE = "UpdatePolicy"
    PERIPHERAL = "PeripheralPolicy"


class EnforcementMode(StrEnum):
    """How a policy is enforced."""

    REPORT_ONLY = "report_only"
    APPLY_ON_CONNECT = "apply_on_connect"
    ENFORCE_CONTINUOUS = "enforce_continuous"
    SCHEDULED = "scheduled"


class ComplianceStatus(StrEnum):
    """Compliance state of an agent against a policy."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIAL = "partial"


@dataclass
class Violation:
    """A single policy rule violation."""

    policy_id: str
    rule_key: str
    expected: Any
    actual: Any
    message: str = ""


@dataclass
class Policy:
    """A fleet management policy."""

    policy_id: str
    kind: str
    version: int
    name: str
    rules: dict[str, Any]
    enforcement: str = EnforcementMode.REPORT_ONLY
    targets: list[dict[str, Any]] = field(default_factory=list)
    received_at: float = field(default_factory=time.time)


@dataclass
class ComplianceReport:
    """Compliance report for the current agent."""

    status: str
    violations: list[Violation]
    policy_count: int
    checked_at: float = field(default_factory=time.time)


_DISPLAY_RULE_COMMANDS: dict[str, str] = {
    "brightness_percent": "display.set_brightness",
    "color_preset": "display.set_color_preset",
    "power_nap": "display.set_power_nap",
    "auto_brightness": "display.set_auto_brightness",
}


class PolicyReceiver:
    """Receives and caches fleet policies, reports compliance."""

    def __init__(
        self,
        command_executor: CommandExecutor | None = None,
    ) -> None:
        self._policies: dict[str, Policy] = {}
        self._last_check: float = 0.0
        self._last_report: ComplianceReport | None = None
        self._command_executor = command_executor

    @property
    def policy_count(self) -> int:
        return len(self._policies)

    @property
    def last_report(self) -> ComplianceReport | None:
        return self._last_report

    async def apply_policy(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle policy.apply command — store a policy."""
        policy_id = params.get("policy_id", "")
        if not policy_id:
            return {"status": "error", "message": "Missing policy_id"}

        policy = Policy(
            policy_id=policy_id,
            kind=params.get("kind", "AgentPolicy"),
            version=params.get("version", 1),
            name=params.get("name", policy_id),
            rules=params.get("rules", {}),
            enforcement=params.get("enforcement", EnforcementMode.REPORT_ONLY),
            targets=params.get("targets", []),
        )

        self._policies[policy_id] = policy
        logger.info(
            "Policy applied: %s (%s, enforcement=%s)",
            policy.name,
            policy.kind,
            policy.enforcement,
        )

        # Enforce immediately for apply_on_connect mode
        enforced: list[dict[str, Any]] = []
        if policy.enforcement in (
            EnforcementMode.APPLY_ON_CONNECT,
            EnforcementMode.ENFORCE_CONTINUOUS,
        ):
            enforced = await self.enforce_policy(policy)

        return {
            "status": "accepted",
            "policy_id": policy_id,
            "enforcement": policy.enforcement,
            "enforced": enforced,
        }

    async def enforce_policy(self, policy: Policy) -> list[dict[str, Any]]:
        """Enforce a single policy by dispatching commands."""
        if self._command_executor is None:
            logger.debug("No command executor — skipping enforcement for %s", policy.policy_id)
            return []

        if policy.kind != PolicyKind.DISPLAY:
            return []

        results: list[dict[str, Any]] = []
        for rule_key, rule_spec in policy.rules.items():
            cmd = _DISPLAY_RULE_COMMANDS.get(rule_key)
            if cmd is None:
                continue

            value = self._enforcement_value(rule_spec)
            if value is None:
                continue

            try:
                result = await self._command_executor(cmd, "display.0", {"value": value})
                results.append({"rule_key": rule_key, "command": cmd, "value": value, **result})
            except Exception as exc:
                logger.warning("Enforcement failed for %s: %s", rule_key, exc)
                results.append(
                    {
                        "rule_key": rule_key,
                        "command": cmd,
                        "value": value,
                        "status": "error",
                        "message": str(exc),
                    }
                )

        return results

    async def enforce_all(self) -> list[dict[str, Any]]:
        """Enforce all policies with enforce_continuous mode."""
        results: list[dict[str, Any]] = []
        for policy in self._policies.values():
            if policy.enforcement == EnforcementMode.ENFORCE_CONTINUOUS:
                results.extend(await self.enforce_policy(policy))
        return results

    @staticmethod
    def _enforcement_value(rule_spec: Any) -> Any:
        """Extract the value to enforce from a rule specification."""
        if isinstance(rule_spec, dict):
            # Explicit default takes precedence
            if "default" in rule_spec:
                return rule_spec["default"]
            # Exact match
            if "value" in rule_spec:
                return rule_spec["value"]
            # Range: use midpoint
            if "min" in rule_spec and "max" in rule_spec:
                return (rule_spec["min"] + rule_spec["max"]) // 2
            return None
        # Scalar: use directly
        return rule_spec

    async def get_status(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle policy.status command — return compliance report."""
        report = await self.check_compliance()
        return {
            "status": report.status,
            "policy_count": report.policy_count,
            "violations": [
                {
                    "policy_id": v.policy_id,
                    "rule_key": v.rule_key,
                    "expected": v.expected,
                    "actual": v.actual,
                    "message": v.message,
                }
                for v in report.violations
            ],
            "checked_at": report.checked_at,
        }

    async def remove_policy(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle policy.remove command — remove a cached policy."""
        policy_id = params.get("policy_id", "")
        if policy_id in self._policies:
            del self._policies[policy_id]
            logger.info("Policy removed: %s", policy_id)
            return {"status": "removed", "policy_id": policy_id}
        return {"status": "not_found", "policy_id": policy_id}

    async def check_compliance(
        self,
        current_values: dict[str, Any] | None = None,
    ) -> ComplianceReport:
        """Check compliance against all active policies.

        For Phase A, this is report-only: we compare declared rules against
        current_values (if provided) or return a basic policy-count report.
        """
        violations: list[Violation] = []
        now = time.time()

        if current_values:
            for policy in self._policies.values():
                for rule_key, rule_spec in policy.rules.items():
                    actual = current_values.get(rule_key)
                    if actual is None:
                        continue

                    # Extract actual value from metric wrapper
                    if isinstance(actual, dict) and "value" in actual:
                        actual = actual["value"]

                    if not self._check_rule(actual, rule_spec):
                        violations.append(
                            Violation(
                                policy_id=policy.policy_id,
                                rule_key=rule_key,
                                expected=rule_spec,
                                actual=actual,
                                message=f"{rule_key}: expected {rule_spec}, got {actual}",
                            )
                        )

        if violations:
            status = ComplianceStatus.NON_COMPLIANT
        elif self._policies:
            status = ComplianceStatus.COMPLIANT
        else:
            status = ComplianceStatus.COMPLIANT

        report = ComplianceReport(
            status=status,
            violations=violations,
            policy_count=len(self._policies),
            checked_at=now,
        )
        self._last_check = now
        self._last_report = report

        # Enforce continuous policies when violations are found
        if violations:
            await self.enforce_all()

        return report

    @staticmethod
    def _check_rule(actual: Any, rule_spec: Any) -> bool:
        """Check if an actual value satisfies a rule specification."""
        if isinstance(rule_spec, dict):
            # Range check: {"min": x, "max": y}
            if "min" in rule_spec and actual < rule_spec["min"]:
                return False
            if "max" in rule_spec and actual > rule_spec["max"]:
                return False
            # Exact match: {"value": x}
            return "value" not in rule_spec or actual == rule_spec["value"]
        # Simple equality check
        return actual == rule_spec

    def get_metrics(self) -> dict[str, Any]:
        """Return fleet compliance metrics for /v1/metrics."""
        from desk2ha_agent.collector.base import metric_value

        report = self._last_report
        status = report.status if report else ComplianceStatus.COMPLIANT
        violations = len(report.violations) if report else 0

        return {
            "fleet.policy_count": metric_value(self.policy_count),
            "fleet.compliance_status": metric_value(status),
            "fleet.violations": metric_value(violations),
            "fleet.last_policy_check": metric_value(
                self._last_check if self._last_check else None
            ),
        }
