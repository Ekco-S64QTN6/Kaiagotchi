from __future__ import annotations

import os
from pathlib import Path

import pytest

import kaiagotchi.agent.monitoring_agent as monitoring_module
from kaiagotchi.agent.monitoring_agent import MonitoringAgent


class FakeProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_airodump_uses_private_randomized_temp_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring_module.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        monitoring_module.shutil,
        "which",
        lambda command: "/usr/bin/airodump-ng" if command == "airodump-ng" else None,
    )
    storage_dir = tmp_path / "archive"
    monkeypatch.setattr(monitoring_module, "PCAP_STORAGE_DIR", storage_dir)
    launched = []

    async def fake_create_subprocess_exec(*args, **_kwargs):
        launched.append(args)
        return FakeProcess()

    monkeypatch.setattr(
        monitoring_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})

    await monitor._launch_airodump()

    capture_dir = monitor._capture_tmp_dir
    assert capture_dir is not None
    assert capture_dir.parent == tmp_path
    assert capture_dir.is_dir()
    assert os.stat(capture_dir).st_mode & 0o777 == 0o700
    assert monitor._base_path == capture_dir / "capture"
    assert monitor._csv_path == capture_dir / "capture-01.csv"
    assert monitor._session_pcap == capture_dir / "capture-01.cap"
    assert launched[0][launched[0].index("--write") + 1] == str(capture_dir / "capture")
    assert launched[0][-1] == "wlan1"

    monitor._cleanup_capture_temp_dir()
    assert not capture_dir.exists()
    assert monitor._capture_tmp_dir is None


@pytest.mark.asyncio
async def test_launch_failure_cleans_empty_capture_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring_module.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(monitoring_module.shutil, "which", lambda _command: "/usr/bin/airodump-ng")
    monkeypatch.setattr(monitoring_module, "PCAP_STORAGE_DIR", tmp_path / "archive")

    async def fail_create_subprocess_exec(*_args, **_kwargs):
        raise OSError("simulated process creation failure")

    monkeypatch.setattr(
        monitoring_module.asyncio,
        "create_subprocess_exec",
        fail_create_subprocess_exec,
    )
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})

    with pytest.raises(OSError, match="simulated process creation failure"):
        await monitor._launch_airodump()

    assert monitor._capture_tmp_dir is None
    assert not list(tmp_path.glob(f"kaiagotchi_{os.getpid()}_*"))


def test_cleanup_preserves_directory_when_pcap_was_not_archived(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring_module.tempfile, "gettempdir", lambda: str(tmp_path))
    capture_dir = Path(
        monitoring_module.tempfile.mkdtemp(
            prefix=f"kaiagotchi_{os.getpid()}_",
            dir=str(tmp_path),
        )
    )
    os.chmod(capture_dir, 0o700)
    pcap = capture_dir / "capture-01.cap"
    pcap.write_bytes(b"unarchived capture")

    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    monitor._capture_tmp_dir = capture_dir

    monitor._cleanup_capture_temp_dir()

    assert capture_dir.is_dir()
    assert pcap.read_bytes() == b"unarchived capture"
    assert monitor._capture_tmp_dir == capture_dir



@pytest.mark.asyncio
async def test_launch_refuses_to_replace_session_with_unarchived_pcap(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring_module.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(monitoring_module.shutil, "which", lambda _command: "/usr/bin/airodump-ng")
    monkeypatch.setattr(monitoring_module, "PCAP_STORAGE_DIR", tmp_path / "archive")

    capture_dir = Path(
        monitoring_module.tempfile.mkdtemp(
            prefix=f"kaiagotchi_{os.getpid()}_",
            dir=str(tmp_path),
        )
    )
    os.chmod(capture_dir, 0o700)
    pcap = capture_dir / "capture-01.cap"
    pcap.write_bytes(b"unarchived")

    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    monitor._capture_tmp_dir = capture_dir

    with pytest.raises(RuntimeError, match="Previous PCAP session is still unarchived"):
        await monitor._launch_airodump()

    assert monitor._capture_tmp_dir == capture_dir
    assert pcap.read_bytes() == b"unarchived"
    assert len(list(tmp_path.glob(f"kaiagotchi_{os.getpid()}_*"))) == 1
