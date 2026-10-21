import asyncio
import os
import stat

import pytest

import kaiagotchi.agent.monitoring_agent as monitoring_module
from kaiagotchi.agent.monitoring_agent import MonitoringAgent


@pytest.mark.asyncio
async def test_airodump_uses_private_temp_directory(tmp_path, monkeypatch):
    archive_dir = tmp_path / "archive"
    monkeypatch.setattr(monitoring_module, "PCAP_STORAGE_DIR", archive_dir)
    monkeypatch.setattr(monitoring_module.shutil, "which", lambda _name: "/usr/bin/airodump-ng")

    class FakeProcess:
        pass

    async def fake_spawn(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    agent = MonitoringAgent(config={})

    await agent._launch_airodump()

    assert agent._capture_dir is not None
    assert agent._capture_dir.parent == tmp_path if False else str(agent._capture_dir).startswith("/tmp/kaiagotchi_")
    assert stat.S_IMODE(agent._capture_dir.stat().st_mode) == 0o700
    assert agent._base_path is not None and agent._base_path.parent == agent._capture_dir
    assert agent._csv_path is not None and agent._csv_path.parent == agent._capture_dir
    assert agent._session_pcap is not None and agent._session_pcap.parent == agent._capture_dir
    assert stat.S_IMODE(archive_dir.stat().st_mode) == 0o700

    agent._cleanup_capture_directory()
    assert agent._capture_dir is None
