"""Regression tests for reward extraction across old and current state schemas."""

import math
from types import SimpleNamespace

import pytest

from kaiagotchi.ai.reward import RewardEngine
from kaiagotchi.data.system_types import AgentMood


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

def test_negative_handshake_counts_are_ignored_without_subtracting_valid_counts():
    engine = RewardEngine({})
    agents = [
        {"handshakes": -5, "handshakes_secured": 2},
        {
            "handshakes": -3,
            "session_metrics": {"handshakes_secured": 4},
        },
        {"handshakes": 6},
        {"handshakes": -100},
    ]

    assert engine._extract_handshakes(agents) == 12

def test_negative_nested_handshake_count_contributes_nothing():
    engine = RewardEngine({})
    agent = {"session_metrics": {"handshakes_secured": -2}}

    assert engine._extract_handshakes([agent]) == 0


def test_partial_snapshot_does_not_reset_reward_delta_baselines(monkeypatch):
    import kaiagotchi.ai.reward as reward_module

    monkeypatch.setattr(reward_module.time, "time", lambda: 1000.0)
    engine = RewardEngine({
        "reward": {
            "idle_decay_per_min": 0.0,
            "weights": {
                "handshakes": 1.0,
                "ap_discovery": 0.5,
                "station_discovery": 0.1,
                "ap_growth": 0.5,
                "channel_diversity": 0.2,
                "activity": 0.3,
                "boredom": 0.0,
                "sadness": 0.0,
                "idle_decay": 0.0,
            },
        }
    })
    complete = {
        "aps": 2,
        "agents": {"monitor": {"handshakes": 2}},
        "network": {"current_channel": 6},
        "metrics": {"uptime_seconds": 30.0},
        "aps_list": [{"bssid": "aa:bb:cc:dd:ee:01"}],
        "stations_list": [{"station_mac": "11:22:33:44:55:66"}],
    }

    first_reward = engine.evaluate(complete)
    assert first_reward > 0.0

    # A partial snapshot omits all counters, uptime, and channel. It must not
    # reset the last known baseline and make the same totals look new later.
    assert engine.evaluate({}) == 0.0
    recovered_reward = engine.evaluate(complete)
    assert recovered_reward == 0.0


def test_invalid_or_missing_optional_fields_preserve_prior_baseline(monkeypatch):
    import kaiagotchi.ai.reward as reward_module

    monkeypatch.setattr(reward_module.time, "time", lambda: 2000.0)
    engine = RewardEngine({
        "reward": {
            "idle_decay_per_min": 0.0,
            "weights": {
                "handshakes": 1.0,
                "ap_growth": 0.5,
                "channel_diversity": 0.2,
                "activity": 0.3,
                "boredom": 0.0,
                "sadness": 0.0,
                "idle_decay": 0.0,
            },
        }
    })
    complete = {
        "aps": 3,
        "agents": {"monitor": {"handshakes": 4}},
        "network": {"current_channel": 11},
        "metrics": {"uptime_seconds": 60.0},
    }
    engine.evaluate(complete)

    malformed = {
        "aps": True,
        "agents": None,
        "network": {"current_channel": True},
        "metrics": {"uptime_seconds": float("nan")},
    }
    assert engine.evaluate(malformed) == 0.0
    assert engine.evaluate(complete) == 0.0


def test_top_level_mood_field_is_used_for_typed_state_compatibility(monkeypatch):
    import kaiagotchi.ai.reward as reward_module

    monkeypatch.setattr(reward_module.time, "time", lambda: 3000.0)
    engine = RewardEngine({
        "reward": {
            "idle_decay_per_min": 0.0,
            "weights": {"idle_decay": 0.0, "boredom": -0.4, "sadness": -0.5},
        }
    })

    neutral = engine.evaluate({"mood": "neutral"})
    bored = engine.evaluate({"mood": "bored"})
    assert neutral == 0.0
    assert bored < neutral


def test_boolean_handshake_counts_are_invalid_and_fall_back_to_numeric_aliases():
    engine = RewardEngine({})
    agents = [
        {"handshakes": True, "handshakes_secured": 3},
        {"handshakes": False, "handshake_count": 2},
        {"session_metrics": {"handshakes_secured": True}},
    ]

    assert engine._extract_handshakes(agents) == 5

@pytest.mark.parametrize(
    ("snapshot", "expected_penalty"),
    [
        pytest.param({"agent_mood": AgentMood.BORED}, -0.4, id="agent-mood-alias"),
        pytest.param({"mood": AgentMood.SAD}, -0.5, id="top-level-mood-alias"),
        pytest.param(
            {"agent": {"mood": AgentMood.BORED}},
            -0.4,
            id="nested-agent-mood-alias",
        ),
        pytest.param(
            {"agent_mood": AgentMood.NEUTRAL, "mood": AgentMood.SAD},
            0.0,
            id="first-nonempty-alias-wins",
        ),
        pytest.param(
            {"agent_mood": "", "mood": AgentMood.SAD},
            -0.5,
            id="empty-alias-falls-through",
        ),
    ],
)
def test_typed_agent_mood_aliases_preserve_precedence_and_penalties(
    monkeypatch, snapshot, expected_penalty
):
    import kaiagotchi.ai.reward as reward_module

    monkeypatch.setattr(reward_module.time, "time", lambda: 4000.0)
    engine = RewardEngine(
        {
            "reward": {
                "idle_decay_per_min": 0.0,
                "weights": {
                    "idle_decay": 0.0,
                    "boredom": -0.4,
                    "sadness": -0.5,
                },
            }
        }
    )

    assert engine.evaluate(snapshot) == pytest.approx(math.tanh(expected_penalty))

