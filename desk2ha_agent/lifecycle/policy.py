"""Fleet policy receiver and compliance checker.

Receives policies from the HA coordinator via the /v1/commands API,
caches them locally, and reports compliance status in metrics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

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


class PolicyReceiver:
    """Receives and caches fleet policies, reports compliance."""

    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}
        self._last_check: float = 0.0
        self._last_report: ComplianceReport | None = None

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

        return {
            "status": "accepted",
            "policy_id": policy_id,
            "enforcement": policy.enforcement,
        }

    async def get_status(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle policy.status command — return compliance report."""
        report = self.check_compliance()
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

    def check_compliance(
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
