# Kaiagotchi

> `(•‿‿•)` — an autonomous, emotion-driven terminal companion for Wi-Fi reconnaissance research.

Kaiagotchi runs a live **curses dashboard** in your terminal while it autonomously
scans the airwaves, captures WPA handshakes, and reacts with moods driven by a
reinforcement-style reward loop. It's a research and learning tool inspired by
[Pwnagotchi](https://github.com/evilsocket/pwnagotchi), rebuilt around a modern
async Python core and a headless terminal UI.

---

## Features

| Area | What it does |
|------|--------------|
| **Curses dashboard** | A btop-style terminal UI (`TerminalDisplay`) showing APs, stations, spectrum, mood, and a live event log. Press **`q`** to quit. |
| **Autonomous recon** | A decision engine drives an `INITIALIZING → RECON_SCAN → TARGETING → MAINTENANCE` state machine, with channel hopping paced by the current mood. |
| **Handshake capture** | Launches `airodump-ng` and records PCAPs; `scapy`-based parsing extracts EAPOL handshakes and PMKIDs and exports hashcat-ready material. |
| **Emotional loop** | `RewardEngine → Epoch → Automata` maps live activity into 12 moods (happy, curious, bored, sad, frustrated, …), each with its own face and voice lines. |
| **Persistence** | Network history and mood/reward state survive restarts (`network_history.json`, `mood_state.json`, plus JSON/Markdown handshake summaries). |
| **Typed core** | `SystemState` and related models are validated with Pydantic v2. |
| **Plugin API** | A small lifecycle-hook plugin system (`on_load` / `on_unload` / `on_event` / `on_state_update`). No plugins ship by default — bring your own. |

---

## Requirements

**Hardware**
- A wireless adapter that supports **monitor mode** and packet injection.

**Software**
- Linux (uses `curses`, `/proc`, and Linux wireless tooling)
- Python **3.11+**
- `aircrack-ng` (provides `airodump-ng`) and `iw`

Kaiagotchi manages the wireless interface, so it needs to run as **root** (or with
`CAP_NET_ADMIN`).

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

Useful flags: `--config PATH` (defaults to `/etc/kaiagotchi/config.toml`),
`--debug`, `--manual`.

Press **`q`** (or `Ctrl-C`) to exit; the curses UI restores your terminal on the
way out.

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

- `[main]` — instance `name` and wireless `iface`
- `[personality]` — reward smoothing and the thresholds that map reward → mood
- `[reward.weights]` — how much each signal (handshakes, discoveries, activity …) contributes
- `[ui]` — render `fps`, pane sizes, and mood faces
- `[bettercap] handshakes` — where captures are written

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
├── ui/         # curses TerminalDisplay, View, Voice, splash
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
