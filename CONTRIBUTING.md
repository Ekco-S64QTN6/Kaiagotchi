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

Epoch observation tests must include string-valued channel IDs from Scapy and malformed optional peer/AP fields; zero/non-finite bond scaling must not abort monitoring.
Plugin-discovery regressions should import a real temporary package from an external plugin root, including a relative helper module; do not mock away the import mechanism being tested.

Legacy capture helper tests must exercise missing, empty, malformed, valid-empty PCAPNG, and a valid synthetic 802.11/EAPOL PCAP; never assert a positive handshake without parser-derived complete-handshake evidence.

PCAP archive reconciliation tests must use synthetic files and verify that symlink entries are ignored without changing permissions or contents of their targets; regular `.pcap` and `.pcapng` files, including uppercase extensions, must still be indexed.

PCAP registration/re-analysis tests must verify that only regular direct children of the private archive are analyzed or registered. External paths, symlink entries, and persisted paths outside the archive must be skipped without touching their targets; the archive directory itself must be rejected when it is a symlink.

Network summary-report tests must cover hidden AP records with missing/null `last_seen`, non-string optional ESSID/channel/encryption values, and malformed non-dictionary persisted records while confirming that valid neighboring entries still appear in both JSON and Markdown outputs.

JSON storage tests must verify that `load_data()` refuses symlink/non-regular inputs without reading targets, and that atomic save replaces a symlink destination with a private `0600` regular file while leaving the target untouched. Retain regular-file permission preservation, relative-path behavior, and file/directory fsync ordering tests. `PersistentMood` permission changes and `LastSession` loads/saves must use the same no-follow regular-file contract, and the `~/.kaiagotchi` storage directory itself must not be a symlink.

Unsupported backend compatibility shims must fail explicitly on `start()`; do not add successful-looking no-op process lifecycle methods. Any newly supported external capture backend needs bounded startup, health/error reporting, and deterministic process termination/reaping tests before it is documented as available.

Wireless channel capability tests must use synthetic iw dev / iw phy outputs, cover 2.4/5/6 GHz and disabled frequencies, and verify unavailable interfaces/commands return an empty list without a hardware dependency.

Channel-hop tests must cover absent/empty configuration staying driver-managed without iw/iwconfig calls, and explicit channel lists selecting the first entry on the first hop before advancing and wrapping.

Manager lifecycle regressions must verify concurrent stop callers share one cleanup attempt, failed component shutdown remains visible and retryable, and timed-out in-flight stop tasks are reused rather than duplicated.
MonitoringAgent and Agent shutdown tests must assert explicit completion results. A monitor process that cannot be reaped or an adapter that cannot be restored must remain retryable through the Agent/Manager lifecycle; legacy cleanup hooks returning `None` remain successful for compatibility.

Terminal table tests must cover AccessPoint.model_dump() values (boolean privacy and ssid), nullable/non-string display fields, malformed row filtering, and snapshot sorting with no real curses terminal.

InterfaceMonitor merge tests must combine synthetic source records that describe the same interface; later sources may override conflicting fields but must not erase unrelated fields, and interfaces first seen in different sources must all remain in the merged snapshot. IP-address parser tests must include veth peer display names such as veth0@if7 and confirm the address is stored under the local interface name veth0.

Web HUD auth regressions must cover already-established WebSockets as well as HTTP: same-origin logout revokes active sockets, foreign-origin logout is rejected, expiry closes idle sockets, and expired clients cannot request a fresh state snapshot.

Documented hardware requirements must match implemented operations: the current monitor/capture path is passive and does not require packet injection. The convenience root launcher deliberately forwards only named app selectors, not arbitrary environment variables.

Tests must use synthetic fixtures. Do not commit real capture files, credentials,
tokens, or BSSID-specific data. The Web HUD tests cover mandatory token configuration for non-loopback binds and
verify that login protects both the HTTP telemetry endpoint and WebSocket while
leaving the default loopback mode unchanged. The optional Atheris harness can be run
with:

```bash
python scripts/fuzz_pcap_parser.py /tmp/kaiagotchi-pcap-corpus -max_len=1048576 -atheris_runs=10000
```

It seeds the corpus with minimal synthetic PCAP/PCAPNG headers and exercises both
parser entry points. Fuzzing is an opt-in developer activity and is not a normal CI
requirement. Hardware smoke tests should be explicitly marked and must not be required
for the normal unit-test suite. The persistent mood store is shared by the monitoring
loop and the Epoch worker; its regression tests must keep state mutations short under
the state lock and filesystem writes serialized from detached snapshots. The manual
[operator hardware checklist](docs/operator-hardware-smoke-test.md)
is intentionally not a CI test because hosted CI has no physical adapter. Only capture
from networks you own or have explicit permission to test.

## Pull requests

- Branch from current `main` and keep the change narrowly scoped.
- Add regression tests for parser, CLI, lifecycle, or reward behavior changes.
- Update `README.md`, `CHANGELOG.md`, and `ROADMAP.md` when workflows or
  project behavior change.
- Include the motivation, exact checks run and their outcomes, known limitations,
  and any required hardware or privilege assumptions.
- Review the complete diff and wait for required CI checks to pass before merge.
