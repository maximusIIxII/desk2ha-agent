#!/usr/bin/env bash
set -euo pipefail

echo "=== ruff check ==="
ruff check .

echo "=== ruff format ==="
ruff format --check .

echo "=== mypy ==="
mypy desk2ha_agent/

echo "=== pytest ==="
pytest tests/unit/ -x --tb=short

echo "All checks passed"
