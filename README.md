Origin and Attribution

This project, Kaiagotchi, is a direct fork and derivative work of the original Pwnagotchi project, which was initially authored by @evilsocket. This project adapts the core concept from a Raspberry Pi platform to a specialized Linux server environment.

We extend full credit to the original author for the foundational design and core components.

Original Project Name: Pwnagotchi

Original Project Repository: https://github.com/jayofelony/pwnagotchi

Original Author: @evilsocket

License: This fork remains licensed under the GNU General Public License v3 (GPLv3).

Kaia AI - The Autonomous Technical Counterpart

(⌐■_■) Autonomous Wireless Security Research

Kaia AI is a specialized, autonomous wireless security research tool built on the Linux server platform. It is designed for optimal performance in capturing WPA key material (handshakes and PMKIDs) from surrounding Wi-Fi environments.

Kaia's core focus is on precision, autonomy, and structural clarity, ensuring reliable up-time and high-efficiency data collection in a stable server environment.

Core Functionality

Kaia leverages bettercap to perform network monitoring and authentication/association attacks. The primary goal is to maximize the collection of crackable WPA key material, which is saved as PCAP files compatible with tools like hashcat.

Key Features

WPA Handshake Capture: Collects full and half WPA handshakes, as well as PMKIDs.

Autonomous Operation: Operates independently, managing network interfaces and attack strategies using its dedicated decision engine.

High Performance: Optimized for multi-core CPUs and dedicated network cards typical of server deployments.

Peer-to-Peer Protocol: Multiple Kaia units in close proximity can communicate to exchange information and coordinate activity.

Supported Hardware

Kaia AI is designed to run on a standard Linux server environment with sufficient resources for concurrent networking and data processing:

Operating System: Ubuntu Server (recommended) or other modern Linux distributions.

Hardware Requirement: Requires a stable system with dedicated, compatible Wi-Fi hardware capable of Monitor Mode injection.

Documentation and Resources

For installation instructions and detailed setup guides, please refer to the project's documentation (links will be updated upon repository migration).

License

Kaiagotchi is based on work originally created by @evilsocket and is released under the GPL3 license.