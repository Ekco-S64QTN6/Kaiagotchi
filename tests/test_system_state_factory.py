"""Tests for the shared initial SystemState factory."""

from kaiagotchi.data.system_types import (
    AccessPoint,
    GlobalSystemState,
    NetworkState,
    SessionMetrics,
    SystemMetrics,
    SystemState,
)


def test_minimal_state_uses_typed_nested_defaults():
    state = SystemState.minimal(config_hash="test-config")

    assert state.current_system_state is GlobalSystemState.BOOTING
    assert state.config_hash == "test-config"
    assert isinstance(state.network, NetworkState)
    assert isinstance(state.metrics, SystemMetrics)
    assert isinstance(state.session_metrics, SessionMetrics)
    assert state.network.access_points == {}
    assert state.network.interfaces == {}
    assert state.metrics.cpu_usage == 0.0
    assert state.session_metrics.handshakes_secured == 0
    assert state.agents == {}


def test_minimal_state_supports_explicit_boot_state():
    state = SystemState.minimal(
        current_system_state=GlobalSystemState.MONITORING,
        config_hash=None,
    )

    assert state.current_system_state is GlobalSystemState.MONITORING
    assert state.config_hash is None


def test_minimal_state_instances_do_not_share_mutable_defaults():
    first = SystemState.minimal(config_hash="first")
    second = SystemState.minimal(config_hash="second")

    first.aps_list.append({"bssid": "AA:BB:CC:DD:EE:FF"})
    first.network.access_points["AA:BB:CC:DD:EE:FF"] = AccessPoint(
        bssid="AA:BB:CC:DD:EE:FF"
    )
    first.session_metrics.handshakes_secured = 1

    assert second.aps_list == []
    assert second.network.access_points == {}
    assert second.session_metrics.handshakes_secured == 0
