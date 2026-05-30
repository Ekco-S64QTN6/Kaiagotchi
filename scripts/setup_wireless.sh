#!/bin/bash
# Complete wireless setup for Kaiagotchi

echo "Setting up wireless interface for Kaiagotchi..."

INTERFACE="wlan1"

# Check if interface exists
if ! ip link show $INTERFACE > /dev/null 2>&1; then
    echo "Error: Interface $INTERFACE not found!"
    echo "Available interfaces:"
    ip link show | grep -E '^[0-9]+:' | cut -d: -f2
    exit 1
fi

# Stop NetworkManager from managing the interface
echo "1. Taking interface away from NetworkManager..."
sudo nmcli dev set $INTERFACE managed no

# Set monitor mode
echo "2. Setting monitor mode..."
sudo ip link set $INTERFACE down
sudo iw dev $INTERFACE set type monitor
sudo ip link set $INTERFACE up

# Verify monitor mode
echo "3. Verifying monitor mode..."
iwconfig $INTERFACE | grep Mode

# Test airodump-ng with root
echo "4. Testing airodump-ng with root privileges..."
timeout 3s sudo airodump-ng $INTERFACE

echo "Setup complete! Interface $INTERFACE should be ready for Kaiagotchi."