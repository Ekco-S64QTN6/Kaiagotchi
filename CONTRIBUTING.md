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

CI gates `compileall` and builds the wheel, then runs pytest on Python 3.11, 3.12,
and 3.13. A separate Python 3.11 quality-baseline job runs Ruff and mypy, prints
their exit codes and finding counts, and uploads complete reports. The first reported
baseline is 17 Ruff diagnostics (14 marked fixable) and 92 mypy errors across 18 source
files. These static checks are explicitly non-gating while findings are triaged; a
green baseline job does not mean Ruff or mypy reported zero findings. Treat the counts
as a starting point and keep the uploaded report for the run under review.

Tests must use synthetic fixtures. Do not commit real capture files, credentials,
or BSSID-specific data. Hardware smoke tests should be explicitly marked and must
not be required for the normal unit-test suite. Only capture from networks you
own or have explicit permission to test.

## Pull requests

- Branch from current `main` and keep the change narrowly scoped.
- Add regression tests for parser, CLI, lifecycle, or reward behavior changes.
- Update `README.md`, `CHANGELOG.md`, and `ROADMAP.md` when workflows or
  project behavior change.
- Include the motivation, exact checks run and their outcomes, known limitations,
  and any required hardware or privilege assumptions.
- Review the complete diff and wait for required CI checks to pass before merge.
