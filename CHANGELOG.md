# Changelog

All notable user-facing changes to Kaiagotchi are documented here.

## Unreleased

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
- Guard plugin teardown against recursive unload calls and registrations attempted
  by unload hooks.
- Establish contributor guidance and a prioritized reliability roadmap.
