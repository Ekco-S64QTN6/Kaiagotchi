# Kaiagotchi - Autonomous Wireless Security Research

> (⌐■_■) The Autonomous Technical Counterpart

**Kaiagotchi** is a specialized, autonomous wireless security research tool built for Linux server environments. Designed for precision, autonomy, and structural clarity, it ensures reliable operation and high-efficiency data collection in stable server deployments.

## 🚀 Overview

Kaiagotchi adapts the core concepts of wireless security research to modern server infrastructure, leveraging high-performance hardware for optimal WPA key material capture and network analysis.

### Core Capabilities

- **WPA Handshake Capture**: Collects full/half WPA handshakes and PMKIDs
- **Autonomous Operation**: Self-managing decision engine for continuous operation  
- **High-Performance Design**: Optimized for multi-core CPUs and server-grade hardware
- **Peer-to-Peer Coordination**: Multi-unit communication and activity synchronization
- **PCAP Compatibility**: Output compatible with industry tools like hashcat

## 🛠️ Key Features

| Feature | Description |
|---------|-------------|
| **Autonomous Recon** | Continuous network scanning and target assessment |
| **WPA Material Capture** | Handshake and PMKID collection for security research |
| **Server Optimization** | Multi-threaded architecture for high-performance hardware |
| **Modern Architecture** | Async/await patterns with type-safe data validation |
| **Extensible Plugin System** | Modular design for custom functionality |

## 📋 Requirements

### Hardware
- **Wi-Fi Adapter**: Compatible wireless card supporting monitor mode and packet injection
- **System**: Modern Linux server with multi-core CPU and adequate RAM
- **Storage**: Sufficient space for capture files and logs

### Software
- **OS**: Ubuntu Server 20.04+ or other modern Linux distributions
- **Python**: 3.11 or newer
- **Dependencies**: `aircrack-ng`, `wireless-tools`, `iw`

## ⚡ Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/Ekco-S64QTN6/kaiagotchi
cd kaiagotchi

# Install Python dependencies
pip install -e .

# Install system dependencies (Ubuntu/Debian)
sudo apt update
sudo apt install aircrack-ng wireless-tools iw

### Basic Usage

```bash
# Start Kaiagotchi (requires root for network access)
sudo kaiagotchi

# View available options
kaiagotchi --help

# Interactive configuration wizard
kaiagotchi --wizard


Configuration
Edit /etc/kaiagotchi/config.toml to customize:

[main]
name = "your-kaiagotchi"
iface = "wlan0mon"

[personality]
advertise = true
deauth = true
channels = [1, 6, 11]


## 🏗️ Architecture
Kaiagotchi employs a modern, modular architecture:

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Monitoring    │    │  Decision Engine │    │ Network Actions │
│     Agent       │◄──►│   (State Machine)│◄──►│    Manager      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  System State   │    │   Event System   │    │  bettercap API  │
│  (Pydantic)     │    │   (Async)        │    │  Integration    │
└─────────────────┘    └──────────────────┘    └─────────────────┘


## 🔧 Advanced Usage
Plugin Development
Kaiagotchi supports custom plugins. Create plugins in /etc/kaiagotchi/plugins/:

```python
from kaiagotchi.plugins import Plugin

class CustomPlugin(Plugin):
    def on_loaded(self):
        self.logger.info("Custom plugin loaded!")
    
    async def on_handshake_captured(self, agent, access_point, client):
        # Custom handshake processing
        pass
Service Deployment

# Install as systemd service
```bash
sudo cp contrib/kaiagotchi.service /etc/systemd/system/
sudo systemctl enable kaiagotchi
sudo systemctl start kaiagotchi

## 🤝 Contributing
We welcome contributions! Please see our Contributing Guide for details on:

Code style and standards

Testing requirements

Pull request process

Issue reporting

## 📚 Documentation
Installation Guide

Configuration Reference

Plugin Development

Troubleshooting

## ⚖️ License & Attribution
Origin
Kaiagotchi is a direct fork and derivative work of the original Pwnagotchi project.

Original Project: Pwnagotchi
Original Author: @evilsocket

We extend full credit to the original author for the foundational design and core concepts.

License
This project remains licensed under the GNU General Public License v3 (GPLv3).

text
Copyright (C) 2024 Kaiagotchi Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

##  🐛 Support
Issues: GitHub Issues

Discussions: GitHub Discussions
Kaiagotchi - Precision wireless security research for the modern era. (⌐■_■)
