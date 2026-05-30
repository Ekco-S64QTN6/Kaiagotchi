#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '/home/ekco/github/Kaiagotchi')

from kaiagotchi.storage.persistent_network import PersistentNetwork

# Re-analyze all pcaps to extract BSSIDs and stations
persistence = PersistentNetwork()
persistence.reanalyze_all_pcaps()

print("Re-analyzed all pcap files. Network history should now contain BSSIDs and stations.")