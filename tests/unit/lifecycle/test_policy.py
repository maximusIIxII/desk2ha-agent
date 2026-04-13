"""Tests for fleet policy receiver."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from desk2ha_agent.lifecycle.policy import PolicyReceiver


@pytest.fixture
def receiver():
    return PolicyReceiver()


@pytest.fixture
def enforcing_receiver():
    executor = AsyncMock(return_value={"status": "completed"})
    return PolicyReceiver(command_executor=executor), executor


@pytest.mark.asyncio
async def test_apply_policy(receiver):
    result = await receiver.apply_policy(
        {
            "policy_id": "corp-display",
            "kind": "DisplayPolicy",
            "version": 1,
            "name": "Corporate Display Standard",
            "rules": {"brightness_percent": {"min": 30, "max": 80}},
            "enforcement": "report_only",
        }
    )
    assert result["status"] == "accepted"
    assert result["policy_id"] == "corp-display"
    assert receiver.policy_count == 1


@pytest.mark.asyncio
async def test_apply_policy_missing_id(receiver):
    result = await receiver.apply_policy({"rules": {}})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_remove_policy(receiver):
    await receiver.apply_policy({"policy_id": "test", "rules": {}})
    assert receiver.policy_count == 1

    result = await receiver.remove_policy({"policy_id": "test"})
    assert result["status"] == "removed"
    assert receiver.policy_count == 0


@pytest.mark.asyncio
async def test_remove_policy_not_found(receiver):
    result = await receiver.remove_policy({"policy_id": "nonexistent"})
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_get_status_empty(receiver):
    result = await receiver.get_status({})
    assert result["status"] == "compliant"
    assert result["policy_count"] == 0
    assert result["violations"] == []


@pytest.mark.asyncio
async def test_compliance_check_compliant(receiver):
    await receiver.apply_policy(
        {
            "policy_id": "brightness",
            "rules": {"brightness_percent": {"min": 30, "max": 80}},
        }
    )
    report = await receiver.check_compliance({"brightness_percent": {"value": 50}})
    assert report.status == "compliant"
    assert len(report.violations) == 0


@pytest.mark.asyncio
async def test_compliance_check_violation(receiver):
    await receiver.apply_policy(
        {
            "policy_id": "brightness",
            "rules": {"brightness_percent": {"min": 30, "max": 80}},
        }
    )
    report = await receiver.check_compliance({"brightness_percent": {"value": 95}})
    assert report.status == "non_compliant"
    assert len(report.violations) == 1
    assert report.violations[0].rule_key == "brightness_percent"
    assert report.violations[0].actual == 95


@pytest.mark.asyncio
async def test_compliance_exact_value(receiver):
    await receiver.apply_policy(
        {
            "policy_id": "color",
            "rules": {"color_preset": "sRGB"},
        }
    )
    report = await receiver.check_compliance({"color_preset": {"value": "sRGB"}})
    assert report.status == "compliant"

    report = await receiver.check_compliance({"color_preset": {"value": "AdobeRGB"}})
    assert report.status == "non_compliant"


def test_get_metrics(receiver):
    metrics = receiver.get_metrics()
    assert "fleet.policy_count" in metrics
    assert metrics["fleet.policy_count"]["value"] == 0
    assert metrics["fleet.compliance_status"]["value"] == "compliant"


# --- Phase B: Enforcement tests ---


@pytest.mark.asyncio
async def test_enforce_display_policy_brightness_range(enforcing_receiver):
    receiver, executor = enforcing_receiver
    await receiver.apply_policy(
        {
            "policy_id": "brightness",
            "kind": "DisplayPolicy",
            "rules": {"brightness_percent": {"min": 30, "max": 80}},
            "enforcement": "apply_on_connect",
        }
    )
    # apply_on_connect triggers enforcement immediately
    executor.assert_called_once_with(
        "display.set_brightness",
        "display.0",
        {"value": 55},
    )


@pytest.mark.asyncio
async def test_enforce_display_policy_exact_value(enforcing_receiver):
    receiver, executor = enforcing_receiver
    await receiver.apply_policy(
        {
            "policy_id": "color",
            "kind": "DisplayPolicy",
            "rules": {"color_preset": "sRGB"},
            "enforcement": "apply_on_connect",
        }
    )
    executor.assert_called_once_with(
        "display.set_color_preset",
        "display.0",
        {"value": "sRGB"},
    )


@pytest.mark.asyncio
async def test_enforce_display_policy_with_default(enforcing_receiver):
    receiver, executor = enforcing_receiver
    await receiver.apply_policy(
        {
            "policy_id": "brightness",
            "kind": "DisplayPolicy",
            "rules": {"brightness_percent": {"min": 30, "max": 80, "default": 50}},
            "enforcement": "apply_on_connect",
        }
    )
    executor.assert_called_once_with(
        "display.set_brightness",
        "display.0",
        {"value": 50},
    )


@pytest.mark.asyncio
async def test_report_only_no_enforcement(enforcing_receiver):
    receiver, executor = enforcing_receiver
    await receiver.apply_policy(
        {
            "policy_id": "brightness",
            "kind": "DisplayPolicy",
            "rules": {"brightness_percent": {"min": 30, "max": 80}},
            "enforcement": "report_only",
        }
    )
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_enforce_continuous_on_violation(enforcing_receiver):
    receiver, executor = enforcing_receiver
    await receiver.apply_policy(
        {
            "policy_id": "brightness",
            "kind": "DisplayPolicy",
            "rules": {"brightness_percent": {"min": 30, "max": 80}},
            "enforcement": "enforce_continuous",
        }
    )
    # First call: enforcement on apply
    executor.reset_mock()

    # Now check compliance with a violation — should trigger enforcement
    await receiver.check_compliance({"brightness_percent": {"value": 95}})
    executor.assert_called_once_with(
        "display.set_brightness",
        "display.0",
        {"value": 55},
    )


@pytest.mark.asyncio
async def test_enforce_without_executor():
    receiver = PolicyReceiver()  # no executor
    result = await receiver.apply_policy(
        {
            "policy_id": "brightness",
            "kind": "DisplayPolicy",
            "rules": {"brightness_percent": {"min": 30, "max": 80}},
            "enforcement": "apply_on_connect",
        }
    )
    assert result["status"] == "accepted"
    assert result["enforced"] == []
