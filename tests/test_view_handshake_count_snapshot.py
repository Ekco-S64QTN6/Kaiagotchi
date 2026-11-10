from types import SimpleNamespace

from kaiagotchi.storage.persistent_network import PersistentNetwork
from kaiagotchi.ui.view import View


def test_handshake_count_uses_locked_count_accessor_not_private_data():
    class Store:
        _data = {
            "pcaps": {
                "unsafe-live-reference": {
                    "analysis": [{"type": "PMKID"}, {"type": "WPA Handshake"}]
                }
            }
        }

        def get_pwned_count(self):
            return 3

        def get_pcap_records(self):
            raise AssertionError("UI refresh should not deep-copy all PCAP records")

    view = object.__new__(View)
    view._agent = SimpleNamespace(persistent_network=Store())

    assert view._handshake_count() == 3


def test_handshake_count_does_not_fall_back_to_unlocked_private_data():
    class Store:
        _data = {"pcaps": {"racy": {"analysis": [{"type": "PMKID"}]}}}

    view = object.__new__(View)
    view._agent = SimpleNamespace(persistent_network=Store())

    assert view._handshake_count() == 0


def test_capture_analysis_count_accessor_reads_consistent_store_data(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    with network._state_lock:
        network._data["pcaps"] = {
            "a.pcap": {"analysis": [{"type": "PMKID"}]},
            "b.pcap": {"analysis": [{"type": "WPA Handshake"}, {"type": "PMKID"}]},
            "empty.pcap": {"analysis": []},
        }

    assert network.get_capture_analysis_count() == 3


def test_pwned_count_is_distinct_networks_not_raw_entries(tmp_path):
    """PWND:6 came from counting every analysis entry. A network re-seen across
    PCAPs, and incomplete handshakes, must not inflate the figure."""
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)

    with network._state_lock:
        network._data["pcaps"] = {
            # Same BSSID captured in two PCAPs → one pwned network.
            "a.pcap": {"analysis": [{"type": "WPA Handshake", "bssid": "AA:BB", "handshake_complete": True}]},
            "b.pcap": {"analysis": [{"type": "WPA Handshake", "bssid": "aa:bb", "handshake_complete": True}]},
            # A PMKID for a different network → a second pwned network.
            "c.pcap": {"analysis": [{"type": "PMKID", "bssid": "CC:DD", "pmkid": "deadbeef"}]},
            # An incomplete handshake is not pwned.
            "d.pcap": {"analysis": [{"type": "WPA Handshake", "bssid": "EE:FF", "handshake_complete": False}]},
        }

    assert network.get_pwned_count() == 2
    # The raw accessor still counts every entry (4), which is why PWND used it wrongly.
    assert network.get_capture_analysis_count() == 4
