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

1. **PCAP parser** — continue synthetic coverage for remaining PCAPNG option semantics,
   block-specific constraints, and packet payloads. The preflight also checks that
   each packet references an interface declared in its section, preventing a corrupt
   late packet from yielding partial data. Never use real captures or credentials.
2. **Async shutdown** — complete startup-failure/normal-stop coverage for capture
   subprocesses and web-server thread termination, and verify background tasks
   are awaited without blocking the asyncio event loop.
3. **Reward and mood contract** — document required/optional state fields and
   fallback behavior; extend reward tests for partial/stale state and malformed
   discovery inputs.
4. **Plugin lifecycle** — define a backwards-compatible plugin API versioning
   policy; continue testing unload hooks that mutate manager state and API
   compatibility across future hook changes. Registration and re-entrant
   shutdown during `unload_all()` are now guarded.
5. **Quality gates** — establish clean baselines, then add compileall, Ruff, and
   advisory mypy checks to automated CI without concealing pre-existing issues.
6. **Operator validation** — document a safe hardware smoke-test checklist for
   `airodump-ng`, `iw`, monitor-mode adapters, privileges, and clean stop behavior.

## Recently completed

- Added streaming validation for PCAPNG option TLV boundaries and end-of-options
  placement in section, interface, packet, and enhanced-packet blocks, with valid
  option fixtures and malformed-length regressions.
- Added a streaming PCAPNG block-framing preflight that validates section byte order,
  block boundaries, aligned lengths, file bounds, and trailing lengths before Scapy
  parses packet bodies. Synthetic coverage verifies valid beacons and rejects a
  corrupt later block without returning partial inventory.
- Added synthetic PCAPNG section-header tests for undersized and truncated declared
  lengths, mismatched trailing lengths, and invalid byte-order magic, while also
  checking that a minimal valid section header remains accepted.
- Made both streaming PCAP parser entry points fail closed when the reader raises
  during iteration, and kept reader-close failures from masking results; added
  synthetic regressions for iteration and close errors.
- Guard plugin teardown against re-entrant `unload_all()` calls and reject late
  registrations while unloading, so unload hooks cannot recurse indefinitely or
  leave a newly loaded plugin outside the active registry.
- Read handshake fields lazily in priority order so an exception raised by an
  optional nested `session_metrics` property cannot hide a valid higher-priority
  count. Added regression tests for broken primary/optional properties.
- Make AP count extraction ignore invalid, negative, or boolean direct counts and
  fall back to network inventories/lists or the legacy monitoring-agent count; an
  explicit zero remains authoritative. Added regression tests for each case.
- Ignore negative handshake counts during reward extraction, treating them as invalid
  and falling through to the next supported field instead of allowing one corrupt
  count to reduce valid totals from other agents.
- Filter malformed reward discovery identities instead of counting blank or invalid
  BSSID/station values. Legacy chatter fallback now ignores non-string message
  payloads while preserving deduplicated text-event compatibility.
- Handle cancellation at any await point during monitor startup, route cleanup
  through the normal stop path, and preserve the capture-process handle across
  spawn cancellation so shutdown can reap it and clean the private temp directory.
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
