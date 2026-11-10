from __future__ import annotations

import kaiagotchi.network.action_manager as action_manager_module
from kaiagotchi.network.action_manager import InterfaceActionManager


class FakeProcess:
    def __init__(self):
        self.returncode = 0

    async def communicate(self):
        return b"", b""


def test_missing_or_empty_channel_config_preserves_automatic_driver_mode():
    missing = InterfaceActionManager({"main": {"iface": "wlan1"}})
    explicit_empty = InterfaceActionManager(
        {"main": {"iface": "wlan1"}, "personality": {"channels": []}}
    )

    assert missing._channel_list == []
    assert explicit_empty._channel_list == []


async def _assert_automatic_hop_does_not_touch_interface_or_spawn_commands(monkeypatch, manager):
    async def unexpected_interface_check(_interface):
        raise AssertionError("automatic mode must not probe or control the interface")

    async def unexpected_spawn(*_args, **_kwargs):
        raise AssertionError("automatic mode must not invoke iw or iwconfig")

    monkeypatch.setattr(manager, "_interface_exists", unexpected_interface_check)
    monkeypatch.setattr(
        action_manager_module.asyncio,
        "create_subprocess_exec",
        unexpected_spawn,
    )

    assert await manager.hop_channel() is False


async def test_empty_channel_config_leaves_channel_selection_to_capture_driver(monkeypatch):
    manager = InterfaceActionManager(
        {"main": {"iface": "wlan1"}, "personality": {"channels": []}}
    )

    await _assert_automatic_hop_does_not_touch_interface_or_spawn_commands(
        monkeypatch, manager
    )


async def test_missing_channel_config_leaves_channel_selection_to_capture_driver(monkeypatch):
    manager = InterfaceActionManager({"main": {"iface": "wlan1"}})

    await _assert_automatic_hop_does_not_touch_interface_or_spawn_commands(
        monkeypatch, manager
    )


async def test_explicit_channel_list_is_preserved_and_cycles_with_manual_hops(monkeypatch):
    manager = InterfaceActionManager(
        {
            "main": {"iface": "wlan1"},
            "personality": {"channels": [1, 6, 36]},
        }
    )
    calls = []

    async def interface_exists(interface):
        assert interface == "wlan1"
        return True

    async def fake_spawn(*command, **_kwargs):
        calls.append(command)
        return FakeProcess()

    monkeypatch.setattr(manager, "_interface_exists", interface_exists)
    monkeypatch.setattr(
        action_manager_module.asyncio,
        "create_subprocess_exec",
        fake_spawn,
    )

    assert manager._channel_list == [1, 6, 36]
    assert await manager.hop_channel() is True
    assert await manager.hop_channel() is True

    assert await manager.hop_channel() is True
    assert await manager.hop_channel() is True

    assert calls == [
        ("iw", "dev", "wlan1", "set", "channel", "1"),
        ("iw", "dev", "wlan1", "set", "channel", "6"),
        ("iw", "dev", "wlan1", "set", "channel", "36"),
        ("iw", "dev", "wlan1", "set", "channel", "1"),
    ]
