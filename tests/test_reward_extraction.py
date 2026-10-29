"""Regression tests for reward extraction across old and current state schemas."""

from types import SimpleNamespace

from kaiagotchi.ai.reward import RewardEngine


def test_explicit_zero_handshakes_beats_stale_legacy_aliases():
    engine = RewardEngine({})
    agents = [
        {
            "handshakes": 0,
            "handshakes_secured": 7,
            "handshake_count": 8,
            "session_metrics": {"handshakes_secured": 9},
        },
        SimpleNamespace(
            handshakes=0,
            handshakes_secured=2,
            handshake_count=3,
            session_metrics=SimpleNamespace(handshakes_secured=4),
        ),
    ]

    assert engine._extract_handshakes(agents) == 0


def test_handshake_extraction_falls_back_from_missing_or_invalid_values():
    engine = RewardEngine({})
    agents = [
        {
            "handshakes": None,
            "handshakes_secured": 3,
            "handshake_count": 8,
            "session_metrics": {"handshakes_secured": 10},
        },
        {
            "handshakes": "not-a-number",
            "handshakes_secured": None,
            "handshake_count": "2",
        },
        SimpleNamespace(
            handshakes=None,
            handshakes_secured=None,
            handshake_count=None,
            session_metrics=SimpleNamespace(handshakes_secured=4),
        ),
    ]

    assert engine._extract_handshakes(agents) == 9


def test_handshake_extraction_accepts_object_with_mapping_session_metrics():
    engine = RewardEngine({})
    agent = SimpleNamespace(
        handshakes=None,
        handshakes_secured=None,
        handshake_count=None,
        session_metrics={"handshakes_secured": 5},
    )

    assert engine._extract_handshakes([agent]) == 5


def test_broken_agent_does_not_hide_counts_from_other_agents():
    class BrokenAgent:
        @property
        def handshakes(self):
            raise RuntimeError("stale state object")

    engine = RewardEngine({})
    assert engine._extract_handshakes([BrokenAgent(), {"handshakes": 2}]) == 2



def test_invalid_direct_ap_count_falls_back_to_network_inventory():
    engine = RewardEngine({})
    state = {
        "aps": "not-a-number",
        "network": {
            "access_points": {
                "AA:BB:CC:DD:EE:01": {},
                "AA:BB:CC:DD:EE:02": {},
            }
        },
        "aps_list": [{"bssid": "AA:BB:CC:DD:EE:03"}],
    }

    assert engine._extract_ap_count(state) == 2


def test_negative_direct_ap_count_falls_back_to_ap_list():
    engine = RewardEngine({})
    state = {
        "aps": -5,
        "network": {"access_points": None},
        "aps_list": [{}, {}, {}],
    }

    assert engine._extract_ap_count(state) == 3


def test_boolean_direct_ap_count_falls_back_to_monitoring_agent_count():
    engine = RewardEngine({})
    state = {
        "aps": True,
        "network": [],
        "aps_list": [],
        "monitoring_agent": {"aps": "4"},
    }

    assert engine._extract_ap_count(state) == 4


def test_explicit_zero_ap_count_remains_authoritative():
    engine = RewardEngine({})
    state = {
        "aps": 0,
        "network": {"access_points": {"AA:BB:CC:DD:EE:01": {}}},
        "aps_list": [{"bssid": "AA:BB:CC:DD:EE:02"}],
    }

    assert engine._extract_ap_count(state) == 0



def test_valid_handshake_count_survives_broken_lower_priority_property():
    class AgentWithBrokenSessionMetrics:
        @property
        def handshakes(self):
            raise RuntimeError("stale primary field")

        @property
        def handshakes_secured(self):
            return 3

        @property
        def session_metrics(self):
            raise RuntimeError("unavailable optional nested metrics")

    engine = RewardEngine({})
    assert engine._extract_handshakes([AgentWithBrokenSessionMetrics()]) == 3


def test_valid_primary_handshake_count_does_not_read_nested_metrics():
    class AgentWithBrokenSessionMetrics:
        handshakes = 5

        @property
        def session_metrics(self):
            raise RuntimeError("lower-priority field should not be read")

    engine = RewardEngine({})
    assert engine._extract_handshakes([AgentWithBrokenSessionMetrics()]) == 5
