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

        def get_capture_analysis_count(self):
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
