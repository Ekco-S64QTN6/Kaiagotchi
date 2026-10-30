# Kaiagotchi

> `(•‿‿•)` — an autonomous, emotion-driven terminal companion for Wi-Fi reconnaissance research.

Kaiagotchi runs a live **curses dashboard** in your terminal while it autonomously
scans the airwaves, captures WPA handshakes, and reacts with moods driven by a
reinforcement-style reward loop. It's a research and learning tool inspired by
[Pwnagotchi](https://github.com/evilsocket/pwnagotchi), rebuilt around a modern
async Python core, a headless terminal UI, and an optional browser HUD.

---

## Features

| Area | What it does |
|------|--------------|
| **Curses dashboard** | A btop-style terminal UI (`TerminalDisplay`) showing APs, stations, spectrum, mood, and a live event log. Press **`q`** to quit. |
| **Cyber-deck web UI** | An optional browser HUD (on by default): live telemetry over WebSocket and an animated Kaia codec avatar. Loopback-only unless you opt into LAN access. |
| **Autonomous recon** | A decision engine drives an `INITIALIZING → RECON_SCAN → TARGETING → MAINTENANCE` state machine, with channel hopping paced by the current mood. |
| **Handshake capture** | Launches `airodump-ng` and records PCAPs; `scapy`-based parsing extracts EAPOL handshakes and PMKIDs and exports hashcat-ready material. |
| **Emotional loop** | `RewardEngine → Epoch → Automata` maps live activity into 12 moods (happy, curious, bored, sad, frustrated, …), each with its own face and voice lines. Reward and UI code share one typed `AgentMood` enum. |
| **Persistence** | Network history and mood/reward state survive restarts (`network_history.json`, `mood_state.json`, plus JSON/Markdown handshake summaries). |
| **Typed core** | `SystemState` and related models are validated with Pydantic v2. |
| **Plugin API** | A small lifecycle-hook plugin system (`on_load` / `on_unload` / `on_event` / `on_state_update`). No plugins ship by default — bring your own. |

---

## Requirements

**Hardware**
- A dedicated wireless adapter that supports **monitor mode** and packet injection. Keep your normal internet adapter in managed mode; Kaiagotchi defaults to using a separate capture dongle on `wlan1`.

**Software**
- Linux (uses `curses`, `/proc`, and Linux wireless tooling)
- Python **3.11+**
- `aircrack-ng` (provides `airodump-ng`) and `iw`

Kaiagotchi manages the wireless interface, so it needs to run as **root** (or with
`CAP_NET_ADMIN`).
Before the first live session, follow the [operator hardware smoke-test checklist](docs/operator-hardware-smoke-test.md). It verifies adapter/tool prerequisites and clean startup/shutdown without requiring active packet injection.

---

## Installation

```bash
# System tools (Arch)
sudo pacman -S aircrack-ng iw

# System tools (Debian/Ubuntu)
# sudo apt install aircrack-ng iw

# Clone and install
git clone https://github.com/Ekco-S64QTN6/Kaiagotchi
cd Kaiagotchi
python3 -m venv venv
source venv/bin/activate
pip install -e .            # add ".[dev]" for tests/lint/type-check tooling
```

---

## Usage

The interface work requires root, so launch with `sudo`. Any of these work:

```bash
# Convenience wrapper (re-execs itself with sudo, uses ./venv if present)
./run_kaiagotchi.sh

# Console script installed by pip
sudo kaiagotchi --debug

# Module form
sudo python -m kaiagotchi.cli --debug
```

By default a cyber-deck web HUD also serves on `http://127.0.0.1:8080`
(animated avatar and live telemetry). Add `--no-web` for terminal-only, or
`--host 0.0.0.0` to reach it from the LAN (unauthenticated — see the warning
it logs).

Useful flags: `--config PATH` (defaults to `/etc/kaiagotchi/config.toml`),
`--debug`, `--manual`, `--no-web`, `--port`, `--host`.

Press **`q`** (or `Ctrl-C`) to exit; the curses UI restores your terminal on the
way out.

Shutdown also attempts to terminate and reap the `airodump-ng` capture process
and restore the capture interface to managed mode. Interface restoration is
best-effort when the driver or system tools report an error.
If startup is cancelled at any await point, the Agent's lifecycle guard runs cleanup
before propagating cancellation, including when cancellation occurs during the
emotional-loop startup barrier. The Manager also owns cleanup when startup is cancelled
while awaiting View, ticker, or Agent startup, or when a fatal bootstrap/Agent startup
error occurs. Already-created subsystems are stopped before the failure is propagated,
even when Manager is used without the CLI wrapper. The monitor keeps its shutdown
cleanup shielded through repeated caller cancellation. If the capture child cannot be
confirmed reaped after graceful and forced termination, the process handle and private
capture files are retained for a later shutdown retry. Capture-process creation is also
shielded long enough to retain its handle for cleanup.
The CLI waits for the web server's blocking thread join in a worker thread, so
that wait does not block the asyncio event loop during shutdown.

---

## Configuration

Configuration is layered: the packaged defaults
([`kaiagotchi/config/defaults.toml`](kaiagotchi/config/defaults.toml)) are merged
with an optional system config. Override only what you need.

```bash
sudo mkdir -p /etc/kaiagotchi
sudo cp kaiagotchi/config/examples/config.toml /etc/kaiagotchi/config.toml
sudo $EDITOR /etc/kaiagotchi/config.toml
```

Key sections:

- `[main]` — instance `name` and primary/interface metadata (`iface`)
- Capture uses `wlan1` by default, independently of `[main].iface`; set `KAIAGOTCHI_INTERFACE` to override the capture dongle name.
- `[personality]` — reward smoothing and the thresholds that map reward → mood
- `[reward.weights]` — how much each signal (handshakes, discoveries, activity …) contributes
- `[ui]` — render `fps`, pane sizes, and mood faces
- `[bettercap] handshakes` — where captures are written
- `[web]` — the browser HUD: `enabled`, `host` (loopback by default), `port`, `update_hz`

Point Kaiagotchi at a different file with `--config` or the `KAIA_CONFIG`
environment variable.

---

## How it works

```
        ┌────────────┐     state      ┌──────────────┐
        │ Monitoring │───────────────▶│ SystemState  │
        │   Agent    │  (airodump-ng) │  (pydantic)  │
        └────────────┘                └──────┬───────┘
              │ pcaps                          │
              ▼                                ▼
       ┌────────────┐   reward   ┌───────┐  mood  ┌──────────┐
       │ pcap_parser│──────────▶ │ Epoch │──────▶ │ Automata │
       │ EAPOL/PMKID│  Reward    │       │        │ (moods)  │
       └────────────┘  Engine    └───────┘        └────┬─────┘
                                                       │ face/voice
                                                       ▼
                                              ┌──────────────────┐
                                              │  TerminalDisplay │
                                              │  (curses UI)     │
                                              └──────────────────┘
```

The `Agent` owns all of these subsystems; the optional `Manager` is a thin
orchestrator that builds the shared view and system state and coordinates
startup/shutdown.

Startup state is created through `SystemState.minimal()`, which relies on the
typed model's default factories for network, system, and session metrics. The
CLI, manager, and base agent share this constructor rather than maintaining
separate copies of the nested defaults.

Network snapshots are recovered best-effort. If an access-point entry cannot be
reconstructed from its value or fallback BSSID key, only that entry is skipped;
valid interfaces and other access points remain available.

### Reward state contract

`RewardEngine.evaluate()` accepts a dictionary snapshot or a Pydantic model
that implements `model_dump()`. No single dictionary key is required for every
integration; fields are read opportunistically, with these rules:

- **AP count:** a valid top-level `aps` count wins (including explicit zero).
  Invalid, negative, or boolean values fall back to a non-empty
  `network.access_points` mapping, a populated `aps_list`, or the legacy
  `monitoring_agent.aps` value. If none provides a valid count, the previous AP
  baseline is retained.
- **Handshake count:** when `agents` is supplied, the first nonnegative,
  integer-convertible value per agent wins in this order: `handshakes`,
  `handshakes_secured`, `handshake_count`, then
  `session_metrics.handshakes_secured`. Booleans, missing/invalid/negative values
  are ignored. If `agents` is omitted or `None`, the previous handshake baseline
  is retained; an explicitly supplied empty agent mapping represents zero.
- **Uptime and channel:** valid nonnegative `metrics.uptime_seconds` updates the
  baseline. Invalid, non-finite, or missing uptime keeps the last value.
  `network.current_channel` falls back to `network.channel`; a missing, blank,
  sentinel (`"--"`), or boolean channel does not count as a channel change.
- **Mood:** penalties use the first non-empty string or `AgentMood` enum
  value among `agent_mood`, `mood`, and `agent.mood`, case-insensitively.
  The alias precedence is explicit: `agent_mood` first, then top-level
  `mood`, then nested `agent.mood`. Only values containing `bored` or
  `sad` apply their configured penalties.
- **Discoveries:** valid six-octet AP/station IDs are rewarded once per engine
  session. Legacy string events in `recent_captures` are used only when the
  corresponding inventory is unavailable, and repeated events are deduplicated.

Missing or invalid optional counters do not reset known delta baselines, so a
temporary partial snapshot cannot make unchanged totals look like new activity
when the full snapshot returns. An explicit valid zero remains authoritative.
Unexpected evaluation errors are logged and return the last computed reward.

### Reward handshake count precedence

For each agent, the reward engine checks `handshakes`, `handshakes_secured`,
`handshake_count`, then `session_metrics.handshakes_secured`. The first
nonnegative integer-convertible value wins, including an explicit zero. Missing,
`None`, invalid, or negative counts fall through to the next supported field,
avoiding stale or corrupt aliases from overriding valid state. Fields are fetched
lazily, so an error in a lower-priority optional property does not discard an
already valid higher-priority count.

For AP counts, an explicit nonnegative integer-convertible `aps` value remains
authoritative (including zero). Invalid, negative, or boolean values are ignored
so extraction can fall back to `network.access_points`, an AP list, or the
legacy `monitoring_agent.aps` field.

### Discovery reward input validation

AP and station inventory entries earn discovery rewards only when their identity
is a six-octet MAC address using colon or hyphen separators. Invalid or non-string
inventory values are ignored; a valid AP dictionary key can still identify an
entry when its embedded BSSID is missing or invalid. Legacy chatter fallback
continues to recognize string messages only and deduplicates them across recent
snapshots.

### PCAP input validation

Before parsing, Kaiagotchi rejects missing or empty files and files whose first
four bytes do not match a known classic PCAP or PCAPNG signature. The PCAPNG reader
ignores the Interface Description Block's reserved field as required for readers,
even though writers must set it to zero. The extension
is advisory: nonstandard extensions produce a warning, but a recognized capture
signature is accepted. This is a lightweight preflight check, not a full
integrity check; the preflight scan verifies PCAPNG section byte order independently
at each concatenated section boundary, treats minor version 2 as equivalent to 0,
checks finite Section Header Block length boundaries, block framing,
declared/trailing lengths, packet captured lengths, option framing, and fixed-size
values across section, interface, packet, and name resolution,
interface statistics, and decryption secrets blocks. It also checks supported
section-header major versions, packet and statistics interface references,
mandatory Name Resolution Block record terminators and known-record lengths,
Decryption Secrets Block data extents, zero-filled alignment padding for option
values, Name Resolution records, secrets, and packet payloads, and Simple Packet
Block payload lengths against the first interface's snaplen without loading packet
bodies or secret contents into memory.
A snaplen of zero means no limit. Legacy Packet and Enhanced Packet captured
lengths may be shorter than the original packet, but cannot exceed either the
original length or a nonzero snaplen. Packet flags validate direction/reception
enumerations and zero reserved bits while preserving link-layer-specific error flags. Interface
transmit/receive speeds, enhanced-packet IDs, queue numbers, and process/thread IDs
are checked against their fixed lengths;
interface-filter, packet-hash, verdict, and custom options enforce their minimum or
type-dependent lengths, including the four-byte private-enterprise number in custom
options. The two standardized Custom Block types require their four-byte PEN
field; their vendor-defined custom data remains opaque. Standard singleton options
cannot repeat, while repeatable comments/custom options, multiple interface addresses,
and EPB packet hashes, verdicts, and process/thread ID pairs remain accepted.
Directional interface speeds follow the if_speed exclusivity rules. Packet blocks
may only reference interfaces declared in the current section.
Scapy then handles packet and payload decoding; malformed framing is rejected before
partial data can be extracted.
Captures may contain sensitive identifiers and traffic, so only inspect files you
are authorized to handle.

Streaming parsing uses Scapy's `PcapReader` only for large captures. If iteration
hits a malformed/truncated record, both parser entry points log the failure and
return an empty result instead of leaking a reader exception; reader-close
errors are logged without masking the parse result.

---

## Plugins

A plugin is a subpackage of `kaiagotchi.plugins` exposing a `Plugin` subclass:

```python
from kaiagotchi.plugins.base import Plugin

class MyPlugin(Plugin):
    def on_load(self):
        ...
    def on_state_update(self, state):
        ...        # called with each SystemState snapshot
    def on_event(self, event_name, data=None):
        ...        # e.g. "mood_change"
```

All hooks are optional. Disable a discovered plugin with
`[plugins.my_plugin] enabled = false` in your config.

### Plugin API versioning

The host currently supports API version `1`, exported as
`PLUGIN_API_VERSION` from `kaiagotchi.plugins.base` and inherited as
`Plugin.PLUGIN_API_VERSION`. Existing subclasses inherit version 1 automatically;
no change is required for legacy plugins. Version 1 hooks are synchronous and
optional (`on_load`, `on_unload`, `on_event`, and `on_state_update`).

When making an incompatible change to hook signatures or lifecycle semantics,
introduce a new version deliberately and document migration steps before enabling
it. Prefer additive optional hooks and optional arguments for backwards-compatible
changes.

Plugin event and state callbacks run against a snapshot of the active registry. A
plugin registered or replaced during a callback becomes eligible on the next
dispatch pass, so lifecycle changes cannot invalidate the in-progress iteration.

The current manager accepts only an integer exactly equal to the host's API
version and rejects `None`, unsupported integers, booleans, strings, and numeric
floats (including `1.0`) before calling `on_load`; an incompatible same-name replacement
cannot displace the working plugin. A future multi-version transition must explicitly
define the supported version set and test each version before the host starts
accepting it.

A plugin is only registered for event/state dispatch after `on_load()` succeeds.
If loading raises, the manager logs the failure and attempts `on_unload()` to
clean up partial initialization. A same-name replacement must finish loading
before the current instance is unloaded, so a failed update leaves the working
plugin active.
During `unload_all()`, new registrations and re-entrant unload calls are rejected;
each active plugin receives at most one unload attempt per shutdown pass.

---

## Development

```bash
pip install -e ".[dev]"

pytest           # run the test suite
ruff check .     # lint
mypy kaiagotchi  # type-check (advisory)
```

Runnable, non-automated demos live in [`scripts/demos/`](scripts/demos).

### Project layout

```
kaiagotchi/
├── agent/      # Agent, MonitoringAgent, DecisionEngine
├── ai/         # Epoch (temporal loop) + RewardEngine
├── core/       # Manager, Automata (moods), system ticker, utils
├── config/     # defaults.toml + loader
├── network/    # airodump integration, PCAP parser, interface monitor
├── storage/    # persistent mood + network history
├── ui/         # curses TerminalDisplay, View, Voice, splash, web HUD
└── plugins/    # plugin base + manager
```

---

## Logging

Logs are written under `logs/kaiagotchi.log` (a writable fallback is chosen if
that path isn't available). Follow them with:

```bash
tail -F logs/kaiagotchi.log
```

---

## Legal notice

Capturing wireless traffic is regulated by law. Only use Kaiagotchi on networks
you **own or have explicit written permission to test**. This project is intended
strictly for ethical security research and education. You are responsible for
complying with all applicable laws.

---

## License

Kaiagotchi is licensed under the **GNU General Public License v3.0** (see
[`LICENSE.md`](LICENSE.md)). It is a derivative work inspired by the original
[Pwnagotchi](https://github.com/evilsocket/pwnagotchi) project by
[@evilsocket](https://github.com/evilsocket).
