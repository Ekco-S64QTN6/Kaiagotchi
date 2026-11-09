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
   The optional Atheris target in `scripts/fuzz_pcap_parser.py` drives both public
   parser entry points with synthetic PCAP/PCAPNG seeds and a 1 MiB input cap;
   normal CI does not require the fuzzing dependency. Never use real captures
   or credentials.
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
   malformed snapshots preserving delta baselines, malformed discovery inputs, and
   authoritative zero rewards across Epoch/RewardEngine fallback selection. A valid
   finite zero is preserved; fallback occurs only when a higher-priority source is
   unavailable, invalid, or did not advance its epoch.
4. **Plugin lifecycle** — host API version 1 is now explicit and inherited by legacy
   subclasses; the manager rejects unsupported declarations before loading or replacing
   a plugin. Event and state dispatch now iterate stable snapshots, so registration or
   replacement inside a hook takes effect on the next pass. `unload_all()` also snapshots
   its initial registry, so a hook removing a peer cannot skip that peer's unload callback.
   Registration and re-entrant `unload_all()` from hooks are rejected/guarded. Synthetic
   tests now cover inherited/explicit v1 declarations and reject booleans, strings, None,
   integral floats, zero, negative, and unsupported future integer versions before hooks.
5. **Quality gates** — compileall, Ruff, and Mypy gate CI. PR #79 cleared all 17
   initial Ruff diagnostics (14 marked fixable); any new Ruff finding fails the
   Python 3.11 quality job. Mypy was promoted to a blocking check after the measured
   baseline reached zero errors: the immediate pre-promotion baseline was 2 errors
   across 1 source file, down from the original 96 errors across 18 files. Both full
   static-analysis reports remain attached to CI for diagnosis. Type-focused cleanup
   has covered `mesh/wifi.py`, `network/interface_monitor.py`, `ai/epoch.py`,
   `core/automata.py`, `core/utils.py`, `ui/splash.py`, `network/action_manager.py`,
   `agent/decision_engine.py`, `ui/terminal_display.py`, `ui/voice/voice.py`,
   `core/system.py`, `core/manager.py`, `cli.py`, `agent/monitoring_agent.py`,
   `ui/web/server.py`, and `network/pcap_parser.py`.
6. **Operator validation** — checklist documented at
   `docs/operator-hardware-smoke-test.md` for `airodump-ng`, `iw`, monitor-mode
   support, privileges, clean shutdown, and safe recovery. A maintainer must still
   execute it on a dedicated physical adapter; CI cannot verify RF hardware.

## Recently completed

- Preserve InterfaceMonitor fields when combining ifconfig, ip-address, wireless, and system-stat records; use deterministic later-source precedence only for conflicting fields on the same interface.

- Consolidate legacy iface_channels() helpers around the selected interface's Wiphy capabilities from iw; filter disabled channels and use an explicit empty result instead of a fabricated list when capability data is unavailable.

- Make the legacy `core.utils.extract_from_pcap()` adapter use the supported PCAP/PCAPNG parser; keep the old dictionary keys, distinguish complete handshakes from partial/PMKID captures, and fail closed to a no-capture result.

- Bind each authenticated Web HUD WebSocket to its browser session; require same-origin logout, revoke connected sockets on logout, and close idle sockets at expiry as well as rejecting later client requests/broadcasts.

- Align the README and requirements notes with the current passive-only capture path: monitor mode is sufficient, the privileged launcher does not forward arbitrary environment variables, and the combined extras example includes `fuzz`.

- Honor custom `PluginManager(plugin_dir=...)` roots with isolated package namespaces and relative imports; replace the mocked discovery test with a real external package fixture.

- Normalize Scapy's string channel identifiers for Epoch histograms, skip malformed optional AP/peer fields, and fall back safely when `bond_encounters_factor` is zero, negative, boolean, non-finite, or non-numeric.

- Protect shared `PersistentMood` state with a re-entrant state lock and serialize snapshot writes with a separate save lock; detach getter state and keep the persisted mood file private (`0600`).

- Detach Epoch snapshots and input network records; read public reward/observation data under the epoch lock so Automata and other consumers cannot mutate live state or observe dictionaries mid-transition.

- Require a high-entropy token before any non-loopback Cyber-Deck bind; protect index, HTTP telemetry, and WebSocket with short-lived HttpOnly/SameSite browser sessions, while preserving unauthenticated loopback defaults.

- Add an optional Atheris harness that fuzzes both PCAP parser entry points with synthetic PCAP/PCAPNG seeds and a hard 1 MiB per-input cap; correct README's stale Mypy advisory note and document how to run the opt-in fuzzer.

- Clear the final two Mypy findings in `ui/terminal_display.py` (optional channel narrowing and iterable typing) and promote Mypy from advisory to blocking CI; retain the full report artifact and add a regression for a missing spectrum channel.

- Make JSON state replacement crash-durable: write and fsync the temporary file before atomic replace, then fsync the parent directory; preserve privacy/metadata and clean up serialization failures.

- Preserve valid zero rewards from Epoch/RewardEngine and only fall back when the source is unavailable, malformed, non-finite, or its epoch did not advance; cover source precedence with synthetic tests.

- Keep the terminal dashboard panes non-overlapping at the supported minimum terminal sizes, and include all observed Wi-Fi channel identifiers in the spectrum view (with a bounded summary when more than twelve channels are present).

- Make an unexpected curses-thread failure request the CLI's normal shutdown path and always clear the thread-started flag when the wrapper exits; add synthetic regressions for initialization failure and normal thread return.

- Keep PMKID-only analysis records out of the terminal's “Total Handshakes” and “Complete WPA” counts while retaining a separate PMKID total; preserve the general analyzed-capture count API and cover complete, partial, and PMKID-only fixtures.

- Correct the terminal scoreboard's “Unique SSIDs Seen” metric to count distinct, observed network names (including persisted ESSID history) rather than BSSID records; exclude hidden/unknown placeholders and cover repeated names in synthetic fixtures.

- Keep terminal shutdown output consistent with TTY ownership: `show_goodbye()` no longer writes ANSI screen-control sequences to redirected/non-interactive stdout; add a regression test for pipe output.

- Make the curses scoreboard read BSSID and capture totals through locked public persistence accessors rather than traversing the live private network dictionary; retain a detached-snapshot compatibility path and cover malformed persisted entries with synthetic regressions.

- Normalize Scapy's 802.11/EAPOL imports to their owning modules, pass a non-optional byte order into PCAPNG option validation, separate optional record lengths, and type eager/streaming packet sources as `Iterable[Packet]`; retain Section Header Block singleton-option validation and existing reader cleanup, reducing the verified mypy baseline from 21 errors across 2 files to 8 across 1.
- Type the web index route as aiohttp's shared `StreamResponse` base and narrow the optional network snapshot once; add coverage for `FileResponse` and an explicit null network snapshot.
- Make CLI optional subsystem imports explicitly nullable without evaluating optional class types at runtime; headless startup now handles a missing or broken splash implementation through a tested factory, and the CLI mypy findings are cleared.
- Keep an unknown monitoring channel unset when the View snapshot contains `None`; avoid converting missing data or fabricating network state, with a regression for the unavailable-channel path.
- Pass a `Path` to the Manager's configuration loader, type optional Agent/View/SystemTicker/State implementations while retaining import fallbacks, and await values returned by synchronous shutdown wrappers; add regressions for configured paths and wrapped async shutdown.
- Preserve optional `RewardEngine` and `Epoch` exports with nullable class types while retaining the module's graceful import fallback.
- Update shared system temperature only when a sensor reading is available, retaining the last known value during sensor dropouts.
- Type Agent's optional ActionManager lifecycle state and the optional ActionManager view; setup narrows the concrete manager, while shutdown tolerates partial initialization without losing persisted state.

- Type the base Agent action manager as optional and narrow the constructed manager during setup; cleanup now tolerates a missing manager after partial initialization. Explicitly type the optional view on `InterfaceActionManager`, cover the uninitialized cleanup path, remove all four Agent mypy findings, and reduce the measured baseline from 54 errors across 8 files to 50 across 7.

- Model `SystemTicker` snapshots with a `TypedDict` and support both synchronous and awaitable callbacks; await callback results rather than dropping coroutines, handle unavailable uptime in CLI output, and cover synchronous, asynchronous, and sync-wrapper-returned awaitables with deterministic metric fixtures; reduce the measured mypy baseline from 62 errors across 9 files to 54 across 8.

- Call the inherited async Agent decision cycle directly and await any awaitable returned by view shutdown hooks, including synchronous wrappers; add synthetic coverage for native async, wrapped-awaitable, and synchronous hooks; reduce the measured mypy baseline from 64 errors across 9 files to 62 across 9.

- Give the voice translator one explicit `Callable[[str], str]` contract for both gettext catalogues and the identity fallback; add tests for translated custom/default text and catalogue-unavailable fallback; remove the remaining voice translator finding and reduce the measured mypy baseline from 65 errors across 10 files to 64 errors across 9 files.

- Narrow `sys.__stdout__` at each terminal-display use: startup captures a non-optional local stream, cleanup/goodbye return safely when it is absent, and compatibility render stubs no-op without a stream; add a regression for missing and disappearing stdout; remove all 13 `terminal_display.py` findings and reduce the measured mypy baseline from 78 errors across 11 files to 65 errors across 10 files.

- Declare the core utility loader's nested default configuration as `dict[str, Any]` so partial TOML overrides retain the documented mapping shape; add a regression that checks each nested section preserves unspecified defaults while applying explicit overrides; reduce the measured mypy baseline from 79 errors across 12 source files to 78 errors across 11 source files.

- Guard the optional `DecisionEngine.view` before invoking its redraw hook, retaining sync and async redraw support; test transitions with no view attached and both redraw styles, including state-change event emission; reduce the measured mypy baseline from 80 errors across 13 source files to 79 errors across 12 source files.

- Type the `iw` and `iwconfig` interface-info result mappings explicitly so textual mode values and numeric channel values share a safe `dict[str, Any]` shape; add synthetic subprocess coverage for parsed monitor mode and channel number; reduce the measured mypy baseline from 81 errors across 14 source files to 80 errors across 13 source files.

- Separate the splash converter's character list, flattened ASCII buffer, and row list so each value has one stable type; add a synthetic Pillow-compatible image test for grayscale-to-ASCII output and row wrapping; reduce the measured mypy baseline from 83 errors across 15 source files to 81 errors across 14 source files.

- Type the `iw dev` mixed wireless-interface records and the aggregate interface snapshot explicitly; cover wireless type/channel parsing plus READY, NET_DOWN, and NO_INTERFACES aggregation with synthetic fixtures; reduce the measured mypy baseline from 87 errors across 16 source files to 83 errors across 15 source files.

- Add explicit types to plugin status storage and Automata's debounce timer/loop snapshot; cover non-object JSON status roots with a regression that confirms the invalid file is not rewritten until an explicit update; reduce the measured mypy baseline from 90 to 87 errors across 16 source files.

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
