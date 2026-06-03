#!/usr/bin/env python3
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kaiagotchi.storage.persistent_network import PersistentNetwork

# Re-analyze all pcaps to extract BSSIDs and stations
persistence = PersistentNetwork()
persistence.reanalyze_all_pcaps()

print("Re-analyzed all pcap files. Network history should now contain BSSIDs and stations.")