from types import SimpleNamespace

from kaiagotchi.ui.view import View


def test_handshake_count_uses_persistent_network_snapshot_accessor():
    class Store:
        _data = {
            "pcaps": {
                "unsafe-live-reference": {
                    "analysis": [{"type": "PMKID"}, {"type": "WPA Handshake"}]
                }
            }
        }

        def get_pcap_records(self):
            return {
                "capture-a.pcap": {"analysis": [{"type": "PMKID"}]},
                "capture-b.pcap": {"analysis": [{"type": "WPA Handshake"}, {"type": "WPA Handshake"}]},
            }

    view = object.__new__(View)
    view._agent = SimpleNamespace(persistent_network=Store())

    assert view._handshake_count() == 3


def test_handshake_count_does_not_fall_back_to_unlocked_private_data():
    class Store:
        _data = {"pcaps": {"racy": {"analysis": [{"type": "PMKID"}]}}}

    view = object.__new__(View)
    view._agent = SimpleNamespace(persistent_network=Store())

    assert view._handshake_count() == 0
