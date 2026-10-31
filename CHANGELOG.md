# Changelog

All notable user-facing changes to Kaiagotchi are documented here.

## Unreleased

- Explicitly type wireless `iw`/`iwconfig` parser result mappings and add a synthetic subprocess regression for mode and integer channel extraction, reducing the measured mypy baseline from 81 to 80 errors across 16 source files.
- Make splash-image ASCII conversion use distinct character, flattened-buffer, and row variables; add a synthetic image regression for grayscale mapping and fixed-width output, reducing the measured mypy baseline from 83 to 81 errors across 16 source files.
- Add explicit types for wireless-interface records and merged interface snapshots, with synthetic regression coverage for parsed type/channel fields and all aggregate status outcomes; reduce the measured mypy baseline from 87 to 83 errors across 16 source files.
- Type `StatusFile`'s JSON state and Automata's debounce timer/loop snapshot explicitly; cover safe fallback from non-object status-file roots and verify the file is rewritten only on an explicit update, reducing the measured mypy baseline from 90 to 87 errors across 16 source files.
- Add explicit types to Epoch network/capture snapshots and elapsed-duration state, reducing the measured mypy baseline from 94 to 90 errors across 16 source files without changing runtime behavior.
- Track managed-mode restoration failures during monitor shutdown and retry only the adapter restoration on a later stop, without repeating completed capture archiving, persistence, or shutdown summaries; reject starting another capture until restoration succeeds.
- Preserve PCAPNG reader compatibility with pass-through captures whose original packet-length metadata is smaller than captured length; keep snaplen and block-data bounds enforced, and cover both Packet and Enhanced Packet Blocks with synthetic parser regressions.
- Keep legacy Packet Block option semantics separate from Enhanced Packet Blocks: option 4 remains an opaque unknown option there instead of being incorrectly required to be a singleton eight-byte drop counter; cover repeated unknown options with a synthetic fixture.
- Skip an unrecoverable access-point record when fallback construction fails for an invalid BSSID key, preserving valid interfaces and other network state; add a synthetic regression.
- Reduce the advisory mypy baseline to 94 errors across 17 source files with behavior-neutral container annotations in the Wi-Fi channel accumulator and interface-address mapping (down from 96 errors across 18 files).
- Correct EPB option multiplicity so multiple process/thread ID pairs are accepted alongside repeatable packet hashes and verdicts, with a synthetic regression.
- Verify that concatenated PCAPNG sections may switch byte order independently at each section boundary, with synthetic finite-length little-to-big and big-to-little fixtures.
- Preserve PCAPNG section reader compatibility by accepting minor version 2 as equivalent to minor version 0, with a synthetic section-header regression.
- Preserve PCAPNG reader compatibility by ignoring the Interface Description Block's reserved field, with synthetic nonzero-value regressions.
- Require the four-byte PEN field in both standardized PCAPNG Custom Block types while leaving vendor-defined custom data opaque, with synthetic acceptance/rejection fixtures.
- Validate Packet and Enhanced Packet Block flags: reject undefined direction/reception values and nonzero reserved bits 12–15, while preserving checksum/offload and link-layer-specific bits, with synthetic little-/big-endian fixtures.
- Treat PCAPNG interface snaplen as a maximum for Packet and Enhanced Packet captured lengths, accepting valid shorter captures while rejecting values above snaplen or original length, with synthetic fixtures.
- Validate signed PCAPNG Section Header Block section lengths: accept the -1 unspecified-length sentinel and exact finite section lengths, enforce four-byte alignment, and reject section/block boundary mismatches across concatenated sections in both byte orders.
- Validate zero-filled PCAPNG alignment padding in option values, Name Resolution records, Decryption Secrets data, and Packet/Enhanced Packet/Simple Packet payloads using bounded synthetic fixtures.
- Enforce PCAPNG standardized option multiplicity with synthetic fixtures: reject repeated singleton options while preserving repeatable comments/custom extensions, multiple interface addresses, and packet hashes/verdicts; require the four-byte PEN prefix in custom options and enforce interface-speed option exclusivity.
- Validate additional PCAPNG option semantics with synthetic fixtures: Interface Description Block filter and transmit/receive speed options; Enhanced Packet Block packet ID, queue, and process/thread options; and type-dependent packet hash/verdict payload lengths for defined algorithms and verdict types.
- Validate PCAPNG Name Resolution Block record boundaries, mandatory end records, known-record lengths/terminators, DNS and Interface Statistics option sizes, statistics interface references, and Decryption Secrets data/option boundaries with synthetic fixtures.
- Keep MonitoringAgent shutdown shielded through repeated caller cancellation and retain the process handle/capture files when the post-kill wait fails, so a later stop can retry reaping before restoring the adapter or cleaning captures.
- Make Manager startup cancellation-safe: cancellation during View, ticker, or Agent startup now runs bounded component cleanup before propagating, including when cancellation is repeated during teardown.
- Dispatch plugin event and state callbacks over a stable registry snapshot, so registering or replacing a plugin during a callback takes effect on the next pass without invalidating the current iteration.
- Validate Simple Packet Block payload lengths against the first interface's snaplen, including the zero-means-no-limit rule, and reject inconsistent block sizes before Scapy parses packet contents.
- Define plugin API v1 compatibility: legacy subclasses inherit the host version, and unsupported/malformed version declarations are rejected before loading or replacing a working plugin.
- Keep Agent cleanup active across startup awaits; cancelling while the emotional loop starts now cancels/reaps the monitor task and runs component cleanup before propagating cancellation.
- Document a safe operator hardware smoke-test checklist for tool/privilege checks, dedicated monitor-mode adapter startup, clean capture-process shutdown, and recovery when child reaping fails. This remains a manual check because hosted CI has no wireless hardware.
- Reject missing, empty, and files without a recognized PCAP/PCAPNG signature
  during the parser's lightweight preflight validation.
- Add synthetic regression tests for classic PCAP byte orders, PCAPNG, empty
  files, missing files, unknown signatures, and advisory file extensions.
- Exercise both parser entry points against signature-only files and truncated
  packet records to guard graceful handling of malformed inputs.
- Use the shared `AgentMood` enum in Automata so mood-specific voice lookup and
  typed system state recognize the same enum members.
- Treat an explicit zero handshake count as authoritative instead of falling
  through to stale legacy count fields.
- Reject failed plugin loads from active dispatch, attempt cleanup after partial
  initialization, and only replace a same-name plugin after the new instance loads.
  Failed replacements leave the existing working instance active.
- Centralize initial typed system-state construction in a shared factory used by
  the CLI, manager, and base agent.
- Harden monitor shutdown to attempt child-process reaping after partial startup
  and retain the process handle if cleanup does not fully complete.
- Offload the web server's blocking thread join from the CLI's asyncio event loop,
  with a regression test asserting that stop executes on a worker thread.
- Run shutdown cleanup on cancellation at any await point during monitor startup,
  including restoring the interface, reaping a spawned child, and cleaning its
  private capture directory before propagating cancellation.
- Ignore malformed AP/station identities in reward inventories and non-string
  legacy chatter payloads, with regression tests for fallback and deduplication.
- Fall back from invalid/negative/boolean direct AP counts to the next supported
  state source while preserving explicit zero counts.
- Read handshake-count fields lazily, so broken lower-priority properties do not
  cause valid higher-priority agent counts to be dropped.
- Ignore negative handshake counts and fall back to lower-priority fields so corrupt
  values cannot subtract valid counts from other agents.
- Make streaming PCAP parsing return empty results on reader iteration failures and
  log close errors without allowing cleanup exceptions to escape.
- Add synthetic PCAPNG section-header coverage for invalid byte-order magic, invalid
  declared lengths, mismatched trailers, and a minimal valid section header.
- Validate all PCAPNG block boundaries and trailers before packet parsing so malformed
  later blocks fail closed instead of yielding a partial network inventory.
- Reject PCAPNG Enhanced Packet Blocks whose captured length exceeds original length
  or the padded packet data available in the declared block body.
- Validate PCAPNG option value lengths and end-of-options markers in section-header,
  interface-description, legacy packet, and enhanced packet blocks before parsing.
- Validate fixed-size PCAPNG option values, including interface timestamp resolution
  and packet flags, and reject malformed lengths before packet decoding.
- Reject PCAPNG packet blocks that reference undeclared interface IDs before parsing,
  rather than treating Scapy's invalid-interface EOF as a successful partial capture.
- Reject unsupported PCAPNG section-header major versions and reset interface state
  at every new section boundary.
- Bound monitor shutdown's wait for cancellation-resistant scan tasks, retain the task
  handle for retry, and defer capture archive/temp cleanup while the scan task is active.
- Shield CLI's final resource-cleanup task from repeated cancellation requests and re-raise
  cancellation only after the cleanup task has completed.
- Defer monitor-mode restoration and capture archive/temp removal when the capture process
  cannot be reaped; bound post-kill waiting and retry with the retained process handle.
- Preserve reward delta baselines across partial snapshots, recognize the canonical top-level
  typed-state mood field, and ignore boolean handshake counts.
- Add a CI quality-baseline job that gates compileall and publishes explicit Ruff/mypy
  outcomes and full reports while existing static-analysis findings are triaged.
- Promote Ruff to a blocking CI gate after clearing all 17 baseline diagnostics; keep
  mypy advisory and continue uploading its full report while its 92 existing errors are triaged.
- Guard plugin teardown against recursive unload calls and registrations attempted
  by unload hooks.
- Establish contributor guidance and a prioritized reliability roadmap.
