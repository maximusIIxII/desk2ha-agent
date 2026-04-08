# Contributing to Desk2HA Agent

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/maximusIIxII/desk2ha-agent.git
cd desk2ha-agent
pip install -e ".[dev]"
pre-commit install
```

## Before submitting a PR

Run these checks locally:

```bash
ruff check desk2ha_agent/ tests/
ruff format desk2ha_agent/ tests/
pytest tests/ -x --tb=short
```

## Commit guidelines

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `ci:`, `test:`, `chore:`
- Update `CHANGELOG.md` under `[Unreleased]` with emoji categories
- For user-facing changes, update `README.md`

## Adding a new collector

1. Create `desk2ha_agent/collector/{tier}/{name}.py`
2. Implement the `Collector` ABC: `probe()`, `setup()`, `collect()`, `teardown()`
3. Export `COLLECTOR_CLASS` at module level
4. Register in `plugin_registry.py`
5. Add tests in `tests/unit/collector/test_{name}.py`

## Reporting bugs

1. Check existing issues first
2. Include: agent version, OS, Python version, error logs
3. If possible, attach output of `GET /v1/info`

## License

By contributing, you agree that your contributions are licensed under the Apache-2.0 License.
