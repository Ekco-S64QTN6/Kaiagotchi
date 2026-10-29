# Roadmap

This roadmap tracks small, testable steps toward a more reliable research tool.
It is intentionally focused on reliability and verification before larger
features or capture-backend changes.

## Current baseline

- Python 3.11+ async application with a curses dashboard and optional browser HUD.
- `airodump-ng` capture integration, Scapy-based PCAP parsing, Pydantic state,
  a reward/mood loop, persistence, and a lightweight plugin lifecycle.
- GitHub Actions builds a wheel, verifies packaged UI/splash assets, and runs
  pytest on Python 3.11, 3.12, and 3.13.
- Automated CI does not validate a physical Wi-Fi adapter, monitor-mode setup,
  privileged capture, or live subprocess behavior.

## Reliability priorities

1. **PCAP parser** — extend synthetic coverage for truncated headers, malformed
   packet records, PCAPNG edge cases, and streaming-reader cleanup. Never add
   real captures, credentials, or BSSID-specific data to fixtures.
2. **Async shutdown** — complete startup-failure/normal-stop coverage for capture
   subprocesses and web-server thread termination, and verify background tasks
   are awaited without blocking the asyncio event loop.
3. **Reward and mood contract** — document required/optional state fields and
   fallback behavior; extend reward tests for partial/stale state and malformed
   discovery inputs.
4. **Plugin lifecycle** — define a backwards-compatible plugin API versioning
   policy; continue testing unload hooks that mutate manager state and API
   compatibility across future hook changes.
5. **Quality gates** — establish clean baselines, then add compileall, Ruff, and
   advisory mypy checks to automated CI without concealing pre-existing issues.
6. **Operator validation** — document a safe hardware smoke-test checklist for
   `airodump-ng`, `iw`, monitor-mode adapters, privileges, and clean stop behavior.

## Recently completed

- Handle cancellation during monitor-mode setup and capture launch. Setup cancellation
  attempts managed-mode restoration; capture-spawn cancellation preserves the child
  handle so normal shutdown can reap it and clean the private capture directory.
- Run the synchronous web-server stop/join operation in a worker thread from CLI
  cleanup so the asyncio event loop can continue servicing cancellation and other
  shutdown work while the server thread exits.
- Improved monitor shutdown so a leftover child process is still waited/reaped
  even if the running flag was cleared during partial startup, and the process
  handle is retained when reaping fails so cleanup can be retried.
- Centralized initial typed state creation in `SystemState.minimal()`; CLI,
  manager, and base agent now share Pydantic's nested default factories instead
  of duplicating network and metrics constructors.
- Hardened plugin registration: failed `on_load()` hooks are not registered for
  dispatch and receive best-effort cleanup; same-name replacements load first,
  so a failed update leaves the current working plugin active.
- Made handshake reward extraction honor the first integer-convertible field,
  including explicit zero counts, while retaining fallbacks for missing/invalid
  values across dictionary and object-backed agent state.
- Consolidated `AgentMood` in `data/system_types.py` as the shared enum for
  Automata and voice handling, preventing mood-specific voice lookups from
  silently falling back to neutral because of enum type mismatch.
- Added PCAP/PCAPNG signature checks before parsing, with synthetic regression
  coverage. File extensions remain advisory so valid captures with a nonstandard
  extension can still be processed; Scapy remains responsible for deeper parsing.
- Added synthetic regressions for signature-only/truncated classic PCAP and
  PCAPNG inputs, including partial packet-record headers and packet data. Both
  parser entry points are expected to fail closed with no extracted captures.
