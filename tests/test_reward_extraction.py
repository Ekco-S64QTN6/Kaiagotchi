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


def test_handshake_extraction_falls_back_when_higher_priority_values_are_missing_or_invalid():
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
