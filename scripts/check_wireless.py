#!/usr/bin/env python3
#kaiagotchi/scipts/check_wireless.py - CHECK WIRELESS INTERFACE AVAILABILITY
import subprocess
import sys

def check_interface(interface="wlan1"):
    """Check if wireless interface exists and can scan."""
    try:
        # Check if interface exists
        result = subprocess.run(['iw', 'dev', interface, 'info'], 
                              capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Interface {interface} not found or not wireless")
            return False
            
        # Check if we can scan (requires root)
        scan_result = subprocess.run(['iw', 'dev', interface, 'scan'],
                                   capture_output=True, text=True)
        if scan_result.returncode == 0:
            print(f"✅ Interface {interface} ready for scanning!")
            return True
        else:
            print(f"⚠️  Interface found but cannot scan (need root?): {scan_result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking interface: {e}")
        return False

if __name__ == "__main__":
    check_interface()