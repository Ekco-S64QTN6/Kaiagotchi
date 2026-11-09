# Contributing

Kaiagotchi is a Linux-oriented research and learning project. Changes should
favor small reliability improvements and reproducible tests over large rewrites.

## Development setup

Use Python 3.11 or newer and install the project with its development extras:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
# Optional coverage-guided parser fuzzing:
python -m pip install -e ".[dev,fuzz]"
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
and 3.13. The Python 3.11 quality job gates compileall, Ruff, and Mypy. Any Ruff
diagnostic or Mypy error fails CI; both full reports are uploaded for diagnosis. Ruff
was promoted after clearing its 17-diagnostic starting baseline. The Mypy baseline
measured immediately before promotion was 2 errors in 1 source file, down from 96
errors across 18 files; those final two findings are cleared by the current TUI typing
cleanup.

Tests must use synthetic fixtures. Do not commit real capture files, credentials,
or BSSID-specific data. The optional Atheris harness can be run with
`python scripts/fuzz_pcap_parser.py /tmp/kaiagotchi-pcap-corpus -max_len=1048576
-atheris_runs=10000`; it seeds the corpus with minimal synthetic PCAP/PCAPNG headers
and exercises both parser entry points. Fuzzing is an opt-in developer activity and is
not a normal CI requirement. Hardware smoke tests should be explicitly marked and must
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
