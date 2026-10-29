"""Regression tests for monitor subprocess shutdown and reaping."""

from unittest.mock import AsyncMock

import pytest

from kaiagotchi.agent.monitoring_agent import MonitoringAgent


class FakeCaptureProcess:
    def __init__(self, *, terminate_raises=False):
        self.returncode = None
        self.terminate_called = False
        self.wait_called = False
        self.kill_called = False
        self.terminate_raises = terminate_raises

    def terminate(self):
        self.terminate_called = True
        if self.terminate_raises:
            raise ProcessLookupError("process already exited")

    async def wait(self):
        self.wait_called = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.kill_called = True
        self.returncode = -9


@pytest.mark.asyncio
@pytest.mark.parametrize("terminate_raises", [False, True])
async def test_stop_reaps_capture_process_even_when_running_flag_is_false(
    monkeypatch, terminate_raises
):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    process = FakeCaptureProcess(terminate_raises=terminate_raises)
    monitor._running = False
    monitor._process = process

    restore_managed_mode = AsyncMock()
    emit_capture_summary = AsyncMock()
    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_emit_capture_summary", emit_capture_summary)
    monkeypatch.setattr(monitor, "_archive_pcap_sync", lambda: None)
    monkeypatch.setattr(monitor, "_cleanup_capture_temp_dir", lambda: None)

    await monitor.stop()

    assert process.terminate_called is True
    assert process.wait_called is True
    assert process.kill_called is False
    assert process.returncode == 0
    assert monitor._process is None
    assert monitor._running is False
    restore_managed_mode.assert_awaited_once()
    emit_capture_summary.assert_awaited_once_with("Monitoring stopped.")

    # A fully stopped instance should make repeated stop() idempotent.
    await monitor.stop()
    restore_managed_mode.assert_awaited_once()
