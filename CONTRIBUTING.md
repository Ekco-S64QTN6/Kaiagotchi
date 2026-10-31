# Contributing

Kaiagotchi is a Linux-oriented research and learning project. Changes should
favor small reliability improvements and reproducible tests over large rewrites.

## Development setup

Use Python 3.11 or newer and install the project with its development extras:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Checks

Run these from the repository root before opening a pull request:

```bash
python -m compileall -q kaiagotchi tests
python -m pytest -q
python -m ruff check .
python -m mypy kaiagotchi
```

CI gates `compileall` and Ruff, builds the wheel, and runs pytest on Python 3.11, 3.12,
and 3.13. The Python 3.11 quality job records Ruff's exit code/count and uploads its
full report; any Ruff diagnostic fails CI. Mypy remains advisory and its full report
is uploaded for triage. The initial baseline had 17 Ruff diagnostics (now cleared) and
79 mypy errors across 16 source files, down from 96 errors across 18 files. A passing
mypy baseline job does not mean there are no mypy findings.

Tests must use synthetic fixtures. Do not commit real capture files, credentials,
or BSSID-specific data. Hardware smoke tests should be explicitly marked and must
not be required for the normal unit-test suite. The manual [operator hardware checklist](docs/operator-hardware-smoke-test.md)
is intentionally not a CI test because hosted CI has no physical adapter. Only
capture from networks you own or have explicit permission to test.

## Pull requests

- Branch from current `main` and keep the change narrowly scoped.
- Add regression tests for parser, CLI, lifecycle, or reward behavior changes.
- Update `README.md`, `CHANGELOG.md`, and `ROADMAP.md` when workflows or
  project behavior change.
- Include the motivation, exact checks run and their outcomes, known limitations,
  and any required hardware or privilege assumptions.
- Review the complete diff and wait for required CI checks to pass before merge.
