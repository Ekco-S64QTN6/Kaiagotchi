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

        def list_known_bssids(self):
            return ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]

        def get_capture_analysis_summary(self):
            return {
                "total": 3,
                "complete_handshakes": 2,
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
            return {"one": {}, "two": {}}

        def get_pcap_records(self):
            return {
                "valid": {
                    "analysis": [
                        {"handshake_complete": True},
                        {"pmkid": True},
                    ]
                },
                "malformed": None,
                "malformed-analysis": {"analysis": "not-a-list"},
            }

    display = _display_with_store(Store())

    assert display._get_scoreboard({"_aps": []}) == (2, 2, 1, 1)


def test_persistent_network_capture_summary_counts_consistent_records(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    with network._state_lock:
        network._data["bssids"] = {"one": {}, "two": {}}
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

    assert network.list_known_bssids() == ["one", "two"]
    assert network.get_capture_analysis_summary() == {
        "total": 3,
        "complete_handshakes": 1,
        "pmkids": 1,
    }
    # Keep the existing lightweight API's contract intact.
    assert network.get_capture_analysis_count() == 4
