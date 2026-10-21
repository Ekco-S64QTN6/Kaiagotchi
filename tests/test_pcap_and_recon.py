import os
import tempfile
import unittest
from pathlib import Path

from kaiagotchi.storage.persistent_network import PersistentNetwork


class TestPcapAndRecon(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for storage
        self.test_dir = tempfile.TemporaryDirectory()
        self.network = PersistentNetwork(storage_dir=self.test_dir.name)
        # PersistentNetwork performs an initial filesystem reconciliation in a
        # daemon thread. Wait for that initialization to finish before this test
        # mutates the private in-memory records, otherwise the startup scan can
        # race the fixture setup and remove the synthetic PCAP record.
        self.network._sync_thread.join(timeout=5.0)
        self.assertFalse(
            self.network._sync_thread.is_alive(),
            "PersistentNetwork startup sync did not finish during test setup",
        )

    def tearDown(self):
        # Clean up temporary directory
        self.test_dir.cleanup()

    def test_pcap_filename_generation(self):
        """Test that BSSID-less PCAP filenames do not contain the 'unknown' keyword anymore."""
        filename_no_bssid = self.network._make_pcap_filename(base_name="airodump", bssid=None)
        self.assertNotIn("unknown", filename_no_bssid)
        self.assertTrue(filename_no_bssid.endswith("_airodump.pcap"))

        filename_unknown_bssid = self.network._make_pcap_filename(base_name="airodump", bssid="UNKNOWN")
        self.assertNotIn("unknown", filename_unknown_bssid)
        self.assertTrue(filename_unknown_bssid.endswith("_airodump.pcap"))

        filename_with_bssid = self.network._make_pcap_filename(base_name="airodump", bssid="12:34:56:78:90:AB")
        self.assertIn("12-34-56-78-90-AB", filename_with_bssid)

    def test_generate_reports(self):
        """Test that reports are generated and contain the expected structure and details."""
        # Populate some mock database entries
        self.network.update_bssid(
            bssid="00:11:22:33:44:55",
            essid="Test-AP",
            packets=100,
            beacons=10,
            channel="6",
            encryption="WPA2"
        )

        # Add mock PCAP record with analysis
        pcap_path = Path(self.network.pcaps_dir) / "2026-05-30T12-00-00_airodump.pcap"
        # Create dummy file
        pcap_path.touch()

        # Register mock PCAP record with analysis containing a PMKID handshake
        self.network._data["pcaps"]["2026-05-30T12-00-00_airodump.pcap"] = {
            "bssid": "00:11:22:33:44:55",
            "created": "2026-05-30T12:00:00-05:00",
            "size": 1234,
            "path": str(pcap_path),
            "analysis": [
                {
                    "type": "PMKID",
                    "bssid": "00:11:22:33:44:55",
                    "ssid": "Test-AP",
                    "client_mac": "AA:BB:CC:DD:EE:FF",
                    "handshake_complete": False,
                    "pmkid": "0102030405060708090a0b0c0d0e0f10"
                }
            ]
        }

        # Save triggers report generation
        self.network.save()

        # Verify output files exist
        json_path = os.path.join(self.test_dir.name, "handshakes_summary.json")
        md_path = os.path.join(self.test_dir.name, "handshakes_summary.md")

        self.assertTrue(os.path.exists(json_path))
        self.assertTrue(os.path.exists(md_path))

        # Check content of JSON report
        import json
        with open(json_path) as f:
            data = json.load(f)

        self.assertEqual(data["summary"]["total_unique_ssids_seen"], 1)
        self.assertEqual(data["summary"]["total_handshakes_captured"], 1)
        self.assertEqual(data["summary"]["total_pmkids"], 1)
        self.assertIn("Test-AP", data["ssids"])

        # Verify hashcat values are constructed correctly
        handshake = data["handshakes"][0]
        self.assertEqual(handshake["hashcat_22000"], "WPA*01*0102030405060708090a0b0c0d0e0f10*001122334455*aabbccddeeff*546573742d4150")
        self.assertEqual(handshake["hashcat_16800"], "0102030405060708090a0b0c0d0e0f10*001122334455*aabbccddeeff*546573742d4150")

        # Check content of MD report
        with open(md_path) as f:
            md_content = f.read()

        self.assertIn("Test-AP", md_content)
        self.assertIn("00:11:22:33:44:55", md_content)
        self.assertIn("WPA*01*0102030405060708090a0b0c0d0e0f10*001122334455*aabbccddeeff*546573742d4150", md_content)

if __name__ == '__main__':
    unittest.main()


    def test_startup_sync_does_not_overwrite_concurrent_pcap_record(self):
        """A record inserted during PCAP analysis wins over the stale scan result."""
        # Complete the initial background sync so the race can be injected
        # deterministically below.
        self.network._sync_thread.join(timeout=5)
        filename = "2026-10-21T12-00-00_airodump.pcap"
        pcap_path = Path(self.network.pcaps_dir) / filename
        pcap_path.touch()

        late_record = {
            "bssid": "00:11:22:33:44:55",
            "created": "2026-10-21T12:00:00-05:00",
            "size": 1234,
            "path": str(pcap_path),
            "analysis": [{
                "type": "PMKID",
                "bssid": "00:11:22:33:44:55",
                "ssid": "Test-AP",
                "client_mac": "AA:BB:CC:DD:EE:FF",
                "handshake_complete": False,
                "pmkid": "0102030405060708090a0b0c0d0e0f10",
            }],
        }

        def insert_late_record(_path, _record):
            # Simulate another thread registering a more complete record
            # after startup sync's initial filename check.
            self.network._data.setdefault("pcaps", {})[filename] = late_record

        self.network._analyze_pcap_into_record = insert_late_record
        self.network._sync_pcaps_with_filesystem()

        stored = self.network._data["pcaps"][filename]
        self.assertEqual(stored["analysis"], late_record["analysis"])
        self.assertEqual(stored["bssid"], "00:11:22:33:44:55")
