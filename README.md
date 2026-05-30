# Kaiagotchi — Autonomous Emotional Terminal Agent for Wireless Research

> (•‿‿•) *The Adaptive Wireless Companion*

**Kaiagotchi** is an autonomous, adaptive terminal autonomous AI agent for wireless research.  
It merges **real-time network intelligence** with a **terminal-based emotional interface**,  
offering a friendly yet powerful environment for security experimentation and analysis.

---

## 🧠 Overview

Kaiagotchi adapts classic wireless reconnaissance concepts to modern Linux environments.  
It uses asynchronous state management, mood-driven feedback, and modular plugins to perform WPA handshake capture and analysis with minimal supervision.

---

## ✨ Key Features

| Feature | Description |
|----------|-------------|
| **Emotional Terminal Display** | ASCII faces and messages reflect agent state and activity |
| **Autonomous Recon** | Continuous network scanning and decision-driven operation |
| **WPA Handshake Capture** | Supports PMKID and EAPOL collection (Bettercap/Scapy backends) |
| **Pydantic v2 Safety** | Type-safe SystemState and configuration models |
| **Plugin Ecosystem** | Extensible plugin API with 21 default modules |
| **Secure Operation** | Controlled privileges with wrapper and capability-based exec |

---

## 🧩 Requirements

**Hardware**
- Wireless adapter supporting monitor mode + injection  
- Modern Linux desktop or laptop  

**Software**
- Python 3.11+  
- `aircrack-ng`, `iw`, `wireless-tools`  

---

## ⚙️ Installation

```bash
# Dependencies
sudo apt update
sudo apt install aircrack-ng wireless-tools python3-pip python3-venv

# Clone and setup
git clone https://github.com/Ekco-S64QTN6/kaiagotchi
cd kaiagotchi
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

---

## 🚀 Quick Start

Run Kaiagotchi safely with preserved environment and privileges:

```bash
./run_kaiagotchi_sudo.sh
```

**Example Output:**

<img src="https://raw.githubusercontent.com/Ekco-S64QTN6/Kaiagotchi/main/images/image.png" alt="Kaiagotchi Pet Image" width="600">


## 🧾 Logging

Logs are stored under:
```
logs/kaiagotchi.log
```
Use `tail -F logs/kaiagotchi.log` to monitor runtime events.

---

## ⚠️ Legal Notice

Wireless packet capture is regulated by law.  
Only use Kaiagotchi on networks **you own or have explicit permission to test**.  
This software is intended strictly for **ethical research and educational purposes**.

---

## ⚖️ License

Kaiagotchi is licensed under the GNU General Public License v3 (GPLv3).  
A derivative of the original Pwnagotchi project by [@evilsocket](https://github.com/evilsocket).

