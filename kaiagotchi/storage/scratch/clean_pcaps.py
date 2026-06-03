#!/usr/bin/env python3
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kaiagotchi.storage.persistent_network import PersistentNetwork

persistence = PersistentNetwork()
pcaps_dir = Path(persistence.pcaps_dir)

# Identify all general _airodump.pcap and _unknown_airodump.pcap files
unknown_pcaps = list(pcaps_dir.glob("*_unknown_airodump.pcap"))

print(f"Found {len(unknown_pcaps)} '_unknown_airodump.pcap' files to clean up.")

for unk_path in unknown_pcaps:
    # Build the corresponding clean filename path
    clean_name = unk_path.name.replace("_unknown_airodump.pcap", "_airodump.pcap")
    clean_path = pcaps_dir / clean_name
    
    if clean_path.exists():
        print(f"Duplicate found:\n  Removing: {unk_path.name}\n  Keeping:  {clean_name}")
        try:
            # Delete the file
            unk_path.unlink()
            
            # Remove from JSON metadata records if present
            if unk_path.name in persistence._data.get("pcaps", {}):
                del persistence._data["pcaps"][unk_path.name]
                print(f"  Removed metadata record for {unk_path.name}")
        except Exception as e:
            print(f"  Error removing duplicate: {e}")
    else:
        # If the duplicate cleanly-named file does not exist, rename it instead of deleting it
        print(f"No direct clean file found for {unk_path.name}. Renaming to {clean_name}")
        try:
            # Rename the file on disk
            unk_path.rename(clean_path)
            
            # Update the JSON metadata records
            if unk_path.name in persistence._data.get("pcaps", {}):
                record = persistence._data["pcaps"].pop(unk_path.name)
                record["path"] = str(clean_path)
                persistence._data["pcaps"][clean_name] = record
                print(f"  Updated metadata record from {unk_path.name} to {clean_name}")
        except Exception as e:
            print(f"  Error renaming file: {e}")

# Save updates and regenerate reports
persistence.save()
print("\nCleanup completed and reports successfully regenerated.")
