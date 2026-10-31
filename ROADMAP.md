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
   block-specific constraints, and packet payloads. The preflight validates supported
   section major versions, finite Section Header Block length boundaries, independent
   byte order changes at concatenated section boundaries, and minor version 2 as
   equivalent to 0; ignores the Interface Description Block reserved
   field as required for readers and resets interface references per section. It checks
   packet and statistics interface references, Packet/Enhanced Packet captured lengths
   against each referenced interface's snaplen as an upper bound (allowing shorter
   captures), and Packet/Enhanced Packet flag
   enumerations and reserved bits;
   validates Name Resolution Block records and their mandatory terminator, checks
   fixed/minimum lengths and singleton-option multiplicity while preserving
   repeatable EPB hash/verdict/process-thread options (including custom-option PEN
   prefixes and interface-speed consistency), validates the PEN field in standardized
   Custom Blocks, checks zero-filled alignment padding for all padded metadata/packet
   data, and checks Simple Packet Block payload size against interface snaplen.
   Never use real captures or credentials.
2. **Async shutdown** — the Agent's cleanup guard covers startup awaits and Manager now
   cleans up already-started View/ticker/Agent components when startup is cancelled, even
   under repeated cancellation. MonitoringAgent defers cancellation through repeated
   caller cancellation until bounded process reaping and cleanup finish; failed graceful
   or post-kill waits retain the child handle and capture files for a later retry. Failed
   managed-mode restoration is also retained as pending and can be retried independently
   without repeating completed session finalization. Synthetic tests assert the shutdown order: reap child, restore managed mode,
   archive capture, remove private temp data, persist network/mood state, then emit summary.
3. **Reward and mood contract** — synthetic tests now cover typed `AgentMood`
   values through all three supported aliases, explicit alias precedence, partial and
   malformed snapshots preserving delta baselines, and malformed discovery inputs.
   README documents accepted snapshot fields, precedence, authoritative zeros,
   discovery deduplication, and baseline preservation when optional counters/channels
   are absent.
4. **Plugin lifecycle** — host API version 1 is now explicit and inherited by legacy
   subclasses; the manager rejects unsupported declarations before loading or replacing
   a plugin. Event and state dispatch now iterate stable snapshots, so registration or
   replacement inside a hook takes effect on the next pass. `unload_all()` also snapshots
   its initial registry, so a hook removing a peer cannot skip that peer's unload callback.
   Registration and re-entrant `unload_all()` from hooks are rejected/guarded. Synthetic
   tests now cover inherited/explicit v1 declarations and reject booleans, strings, None,
   integral floats, zero, negative, and unsupported future integer versions before hooks.
5. **Quality gates** — compileall and Ruff now gate CI. PR #79 cleared all 17 initial
   Ruff diagnostics (14 marked fixable); the Python 3.11 job records exit code/counts and
   uploads the report, so new Ruff findings fail CI. Mypy remains advisory; its latest
   measured baseline is 90 errors across 16 source files, with full reports attached for
   systematic triage. Explicit container annotations in `mesh/wifi.py`,
   `network/interface_monitor.py`, and `ai/epoch.py` have removed six inference
   errors since the 96-error, 18-file baseline without changing runtime behavior.
6. **Operator validation** — checklist documented at
   `docs/operator-hardware-smoke-test.md` for `airodump-ng`, `iw`, monitor-mode
   support, privileges, clean shutdown, and safe recovery. A maintainer must still
   execute it on a dedicated physical adapter; CI cannot verify RF hardware.

## Recently completed

- Add explicit types for Epoch's AP, station, and capture snapshots and its floating-point duration; this removes four straightforward mypy findings without changing runtime behavior.

- Treat PCAPNG interface snaplen as a maximum rather than an exact capture-length target; accept valid shorter Packet and Enhanced Packet captures while rejecting lengths above snaplen.

- Scope PCAPNG option length and multiplicity checks to each block's own registry; preserve unknown Packet Block options rather than applying Enhanced Packet Block drop-count rules.

- Accept preserved PCAPNG Packet and Enhanced Packet Blocks whose original-length metadata is smaller than the captured length, while still bounding captured bytes by snaplen and block extent.

- Preserve typed network state when an access-point record cannot be reconstructed from its value or fallback BSSID key: skip only that record instead of discarding the full network snapshot. A synthetic regression verifies that valid interfaces and other access points survive.

- Correct EPB option multiplicity so process/thread ID option 8 can repeat while flags, drop count, packet ID, and queue remain singleton options.

- Verify concatenated PCAPNG sections can independently switch little-/big-endian interpretation at each SHB boundary, with finite-length synthetic fixtures in both orders.

- Assert that the PCAPNG reader ignores the IDB's reserved 16-bit field even for nonzero values, as required of readers (while writers are expected to emit zero).

- Require the four-byte PEN field in the standardized copyable/non-copyable PCAPNG Custom Block types while keeping vendor-defined data opaque; retain generic framing-only handling for other local-use block types.

- Validate Packet/Enhanced Packet flags for defined direction and reception values and zero reserved bits 12–15, while preserving checksum/offload and link-layer-specific flag bits with synthetic little-/big-endian captures.

- Exercise strict plugin API-version declaration boundaries with synthetic plugins: inherited and explicit v1 are accepted, while boolean, string, None, integral-float, zero, negative, and unsupported future integer declarations are rejected before lifecycle hooks.

- Validate Packet and Enhanced Packet captured lengths against the snaplen of each packet's referenced interface, including full capture, truncation, and zero-as-unlimited cases.

- Validate PCAPNG signed Section Header Block section lengths and exact section boundaries, including the -1 unspecified-length sentinel, finite lengths across concatenated sections, four-byte alignment, and both section byte orders.

- Reject nonzero alignment padding in PCAPNG option values, Name Resolution records, Decryption Secrets data, and Packet/Enhanced Packet/Simple Packet payloads by reading only the padding bytes.

- Validate PCAPNG option multiplicity by block type, preserve explicitly repeatable common/custom/address/hash/verdict options, enforce custom-option PEN minimum lengths, and reject conflicting interface-speed metadata using synthetic captures.

- Verify `PluginManager.unload_all()` finishes invoking hooks from its initial registry snapshot even when an earlier unload hook removes a peer from the live registry.

- Assert monitor shutdown ordering with a synthetic process and persistence doubles: child reaping precedes managed-mode restoration, which precedes capture archiving/temp cleanup and network/mood persistence.

- Validate PCAPNG Name Resolution Block record boundaries, known-record minimum lengths and name terminators, block-specific DNS/statistics option lengths, Interface Statistics Block interface references, and Decryption Secrets Block data/option boundaries with synthetic fixtures.

- Keep MonitoringAgent's internal shutdown task shielded through repeated caller cancellation, then re-raise cancellation after cleanup reaches a terminal state. Add synthetic coverage for repeated cancellation during a blocked child wait and a failed post-kill wait that must retain the process handle and capture files until retry.

- Make Manager startup cleanup-owned: cancellation while awaiting View, ticker, or Agent
  startup stops already-created components before propagating. Fatal bootstrap and Agent
  startup failures also trigger teardown. Shield the bounded cleanup from repeated
  cancellation and cover each await boundary with synthetic tests.

- Dispatch event and state callbacks over a snapshot of active plugins. Plugins registered
  or replaced from within a callback become eligible on the next dispatch pass, avoiding
  dictionary-size errors and keeping each pass's membership stable.

- Validate Simple Packet Block payload sizes against the first interface's snaplen, treating
  zero snaplen as unlimited, and fail closed before parsing malformed/truncated payloads.
  Synthetic coverage exercises full packets, snaplen truncation, no-limit captures, and
  inconsistent payload lengths through both parser entry points.

- Defined the backwards-compatible plugin API v1 contract: existing subclasses inherit
  version 1, only the host-supported integer version loads, and an incompatible same-name
  candidate is rejected before hooks run so the existing plugin remains active.

- Extended Agent's lifecycle `try/finally` across the monitor/Automata startup barrier and
  added a regression that cancels while Automata is waiting, asserting the monitor task,
  monitoring component, persistence, and action manager all receive cleanup.

- Documented a passive, authorized operator smoke-test for required tools, monitor-mode
  capability, startup, process reaping, managed-mode restoration, and privacy-conscious
  results. Physical-adapter execution remains unverified by CI.

- Promoted Ruff to a blocking CI check after clearing all 17 initial baseline diagnostics; mypy remains advisory with a full report and a measured baseline of 92 errors across 18 source files.
- Documented the RewardEngine input contract and added regression coverage showing that
  partial/malformed snapshots preserve known counter/channel baselines, top-level typed
  state `mood` applies mood penalties, and boolean handshake counts are ignored.

- Defer monitor-mode restoration and capture archive/temp cleanup when a capture child
  cannot be confirmed reaped; bound the post-kill wait and retain the process handle for
  retry. A synthetic wait-failure regression verifies cleanup happens only after retry.
- Shield CLI resource cleanup through repeated task cancellation: manager/agent/view and
  web-server shutdown can finish bounded cleanup attempts before caller cancellation is
  re-raised. A synthetic repeated-cancel regression covers the cleanup waiter.

- Reject unsupported PCAPNG section-header major versions and add a regression that
  proves interface IDs reset at new section headers instead of carrying over from the
  preceding section.
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
