#!/bin/bash
echo "=== Wireless Interface Diagnostic ==="

INTERFACE="wlan1"

echo "1. Checking interface $INTERFACE..."
ip link show $INTERFACE

echo ""
echo "2. Checking monitor mode..."
iw dev $INTERFACE info

echo ""
echo "3. Testing airodump-ng for 15 seconds..."
timeout 15s sudo airodump-ng $INTERFACE

echo ""
echo "4. Checking for nearby networks with iwlist..."
sudo iwlist $INTERFACE scan | head -50

echo ""
echo "5. Checking wireless reg domain..."
iw reg get

echo ""
echo "=== Diagnostic Complete ==="