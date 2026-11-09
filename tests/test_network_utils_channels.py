from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from kaiagotchi.core import utils as core_utils
from kaiagotchi.network import utils as network_utils


def _result(returncode: int, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_iface_channels_uses_interface_wiphy_and_filters_disabled_channels(monkeypatch):
    calls = []
    phy_output = """Wiphy phy3
    Band 1:
        Frequencies:
            * 2412 MHz [1] (20.0 dBm)
            * 2437 MHz [6] (20.0 dBm)
            * 5180 MHz [36] (20.0 dBm)
            * 5260 MHz [52] (20.0 dBm) (radar detection)
            * 5280 MHz [56] (disabled)
    Band 2:
        Frequencies:
            * 5955 MHz [1] (14.0 dBm) (no IR)
            * 5975 MHz [5] (14.0 dBm) (no IR)
            * 7115 MHz [233] (14.0 dBm) (no IR)
"""

    def fake_run(command, **kwargs):
        calls.append(command)
        if command == ["iw", "dev", "wlan7", "info"]:
            return _result(0, "Interface wlan7\n\twiphy 3\n")
        if command == ["iw", "phy", "phy3", "info"]:
            return _result(0, phy_output)
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(network_utils.subprocess, "run", fake_run)

    assert network_utils.iface_channels("wlan7") == [1, 5, 6, 36, 52, 233]
    assert calls == [
        ["iw", "dev", "wlan7", "info"],
        ["iw", "phy", "phy3", "info"],
    ]


@pytest.mark.parametrize(
    "interface",
    ["", " wlan0", "wlan0 ", "--help", "wlan/0", "w" * 16, None],
)
def test_iface_channels_rejects_invalid_interface_names_without_running_iw(
    monkeypatch, interface
):
    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("iw must not run for an invalid interface name")

    monkeypatch.setattr(network_utils.subprocess, "run", unexpected_run)

    assert network_utils.iface_channels(interface) == []


def test_iface_channels_returns_empty_when_interface_has_no_wiphy(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return _result(0, "Interface wlan0\n\tifindex 3\n")

    monkeypatch.setattr(network_utils.subprocess, "run", fake_run)

    assert network_utils.iface_channels("wlan0") == []
    assert calls == [["iw", "dev", "wlan0", "info"]]


def test_iface_channels_returns_empty_when_interface_query_fails(monkeypatch):
    monkeypatch.setattr(
        network_utils.subprocess,
        "run",
        lambda *_args, **_kwargs: _result(1, stderr="No such device"),
    )

    assert network_utils.iface_channels("wlan0") == []


def test_iface_channels_returns_empty_when_phy_query_fails(monkeypatch):
    def fake_run(command, **_kwargs):
        if command == ["iw", "dev", "wlan0", "info"]:
            return _result(0, "Interface wlan0\n\twiphy 0\n")
        return _result(1, stderr="No such device")

    monkeypatch.setattr(network_utils.subprocess, "run", fake_run)

    assert network_utils.iface_channels("wlan0") == []


@pytest.mark.parametrize("error", [FileNotFoundError("iw"), subprocess.TimeoutExpired("iw", 5)])
def test_iface_channels_returns_empty_when_iw_cannot_be_executed(monkeypatch, error):
    def fail_run(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(network_utils.subprocess, "run", fail_run)

    assert network_utils.iface_channels("wlan0") == []


def test_core_utils_iface_channels_delegates_to_shared_network_helper(monkeypatch):
    seen = []

    def fake_query(interface):
        seen.append(interface)
        return [6, 36, 149]

    monkeypatch.setattr(network_utils, "iface_channels", fake_query)

    assert core_utils.iface_channels("wlan2mon") == [6, 36, 149]
    assert seen == ["wlan2mon"]


def test_iface_channels_returns_empty_when_phy_has_no_enabled_frequencies(monkeypatch):
    def fake_run(command, **_kwargs):
        if command == ["iw", "dev", "wlan0", "info"]:
            return _result(0, "Interface wlan0\n\twiphy 0\n")
        return _result(
            0,
            "Wiphy phy0\n    Band 1:\n        Frequencies:\n"
            "            * 2412 MHz [1] (disabled)\n",
        )

    monkeypatch.setattr(network_utils.subprocess, "run", fake_run)

    assert network_utils.iface_channels("wlan0") == []
