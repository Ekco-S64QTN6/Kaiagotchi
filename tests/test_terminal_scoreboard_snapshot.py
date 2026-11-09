from types import SimpleNamespace

from kaiagotchi.storage.persistent_network import PersistentNetwork
from kaiagotchi.ui.terminal_display import TerminalDisplay


def _display_with_store(store):
    display = object.__new__(TerminalDisplay)
    display._agent = SimpleNamespace(persistent_network=store)
    return display


def test_terminal_scoreboard_uses_locked_public_store_accessors():
    class Store:
        @property
        def _data(self):
            raise AssertionError("Terminal UI must not inspect live private storage")

        def get_unique_ssid_count(self):
            return 2

        def get_capture_analysis_summary(self):
            return {
                "total": 2,
                "complete_handshakes": 1,
                "pmkids": 1,
            }

    display = _display_with_store(Store())

    assert display._get_scoreboard({"_aps": []}) == (2, 3, 2, 1)


def test_terminal_scoreboard_legacy_fallback_uses_detached_public_snapshots():
    class Store:
        @property
        def _data(self):
            raise AssertionError("Terminal UI must not inspect live private storage")

        def get_all_bssids(self):
            return {
                "one": {"essid": "Home", "essid_history": ["Old Home", "Home"]},
                "two": {"essid": "Home", "essid_history": ["Home"]},
                "three": {"essid": "Guest", "essid_history": ["Guest"]},
                "hidden": {"essid": "<Hidden>", "essid_history": ["Hidden or Unknown"]},
            }

        def get_pcap_records(self):
            return {
                "valid": {
                    "analysis": [
                        {
                            "type": "WPA Handshake (Complete)",
                            "handshake_complete": True,
                        },
                        {
                            "type": "PMKID",
                            "handshake_complete": True,
                            "pmkid": "00112233445566778899aabbccddeeff",
                        },
                    ]
                },
                "malformed": None,
                "malformed-analysis": {"analysis": "not-a-list"},
            }

    display = _display_with_store(Store())

    assert display._get_scoreboard({"_aps": []}) == (3, 2, 1, 1)


def test_persistent_network_capture_summary_counts_consistent_records(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    with network._state_lock:
        network._data["bssids"] = {
            "one": {"essid": "Home", "essid_history": ["Home", "Old Home"]},
            "two": {"essid": "Home", "essid_history": ["Home"]},
            "three": {"essid": "Guest", "essid_history": ["Guest"]},
            "hidden": {"essid": "<Hidden>", "essid_history": ["Hidden or Unknown"]},
        }
        network._data["pcaps"] = {
            "first.pcap": {
                "analysis": [
                    {"handshake_complete": True},
                    {"pmkid": True},
                ]
            },
            "second.pcap": {
                "analysis": [
                    {"handshake_complete": False, "pmkid": False},
                    "not-a-capture-record",
                ]
            },
            "malformed.pcap": None,
        }

    assert network.get_unique_ssid_count() == 3
    assert network.get_capture_analysis_summary() == {
        "total": 3,
        "complete_handshakes": 1,
        "pmkids": 1,
    }
    # Keep the existing lightweight API's contract intact.
    # This older accessor deliberately counts every analysis entry (including
    # PMKIDs); the terminal summary separates those categories.
    assert network.get_capture_analysis_count() == 3


def test_terminal_scoreboard_counts_ssids_from_snapshot_when_store_is_missing():
    display = _display_with_store(None)
    snapshot = {
        "_aps": [
            {"essid": "Home"},
            {"essid": "Home"},
            {"essid": "Guest"},
            {"essid": "<Hidden>"},
            {"essid": "Hidden or Unknown"},
        ]
    }

    assert display._get_scoreboard(snapshot) == (2, 0, 0, 0)
