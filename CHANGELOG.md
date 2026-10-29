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
  initialization, and unload an existing same-name plugin before replacement.
- Centralize initial typed system-state construction in a shared factory used by
  the CLI, manager, and base agent.
- Establish contributor guidance and a prioritized reliability roadmap.
