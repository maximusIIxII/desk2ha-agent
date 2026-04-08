# desk2ha-agent — Development Guide

You are working on the **Desk2HA Agent**, a cross-platform Python service that
runs on endpoint devices and exposes local telemetry via HTTP and MQTT.

## Quick Reference

- Python package: `desk2ha_agent`
- Entry point: `python -m desk2ha_agent`
- Config format: TOML (`desk2ha-agent.toml`)
- API port: 9693

## Autonomie-Regeln

Du darfst OHNE Rueckfrage:
- Code, Tests, Doku auf Feature-Branches schreiben, committen und pushen
- Draft-PRs erstellen
- Lint/Format/Type-Fehler fixen
- Dependencies in pyproject.toml hinzufuegen (mit Begruendung im Commit)

Du MUSST den User fragen fuer:
- PR auf main mergen (ausser docs/*)
- Release taggen
- Deploy auf Live-System
- OpenAPI Spec oder ARCHITECTURE.md aendern
- CLAUDE.md aendern

## Vor jedem Commit

```bash
ruff check . && ruff format --check . && mypy desk2ha_agent/ && pytest tests/unit/ -x
```

## Projektstruktur

- `desk2ha_agent/collector/platform/` — OS-specific host telemetry (Windows/Linux/macOS)
- `desk2ha_agent/collector/generic/` — Standard protocols (DDC/CI, UVC, BLE, HID)
- `desk2ha_agent/collector/vendor/` — Vendor plugins (Dell, HP, Lenovo, Logitech)
- `desk2ha_agent/transport/` — HTTP, MQTT, Prometheus transports
- `desk2ha_agent/lifecycle/` — Self-update, config API, service manager
- `desk2ha_agent/images/` — Product image fetcher + cache
- `desk2ha_agent/tray/` — Windows system tray helper

## Coding Standards

- Type hints on all public functions
- `from __future__ import annotations` in every module
- Async by default (aiohttp event loop)
- Collectors inherit from `collector.base.Collector`
- Use `logging` (no print statements)
- Keep platform-specific imports behind `sys.platform` guards

## Commit Convention

Format: `{type}: {description}`
Types: feat, fix, refactor, test, docs, ci, chore
All commits end with: `Co-Authored-By: Claude <noreply@anthropic.com>`
