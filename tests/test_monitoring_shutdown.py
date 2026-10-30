"""Regression tests for monitor subprocess shutdown and reaping."""

import asyncio
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


@pytest.mark.asyncio
async def test_stop_bounds_unresponsive_scan_and_retries_deferred_capture_cleanup(
    monkeypatch
):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    process = FakeCaptureProcess()
    monitor._running = True
    monitor._process = process
    monitor._capture_tmp_dir = "/private/capture"

    scan_started = asyncio.Event()
    scan_cancelled = asyncio.Event()
    release_scan = asyncio.Event()

    async def scan_loop_that_suppresses_cancellation():
        scan_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            scan_cancelled.set()
            await release_scan.wait()

    loop_task = asyncio.create_task(scan_loop_that_suppresses_cancellation())
    monitor._loop_task = loop_task
    await scan_started.wait()

    archive_calls = []
    cleanup_calls = []
    monkeypatch.setattr(monitor, "_restore_managed_mode", AsyncMock())
    monkeypatch.setattr(monitor, "_archive_pcap_sync", lambda: archive_calls.append(True))
    monkeypatch.setattr(
        monitor,
        "_cleanup_capture_temp_dir",
        lambda: (cleanup_calls.append(True), setattr(monitor, "_capture_tmp_dir", None)),
    )
    monkeypatch.setattr(monitor, "_emit_capture_summary", AsyncMock())

    stop_task = asyncio.create_task(monitor.stop())
    await scan_cancelled.wait()
    # A caller cancellation must not cancel the inner shutdown midway through
    # process reaping. stop() re-raises it only after its bounded cleanup attempt.
    stop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stop_task, timeout=2.5)

    assert process.terminate_called is True
    assert process.wait_called is True
    assert process.returncode == 0
    assert monitor._process is None
    assert monitor._loop_task is loop_task
    assert monitor._capture_tmp_dir == "/private/capture"
    assert archive_calls == []
    assert cleanup_calls == []

    # Once the task can exit, a subsequent stop() reaps the task handle and
    # completes the deferred archive/temporary-directory cleanup.
    release_scan.set()
    await loop_task
    await monitor.stop()

    assert monitor._loop_task is None
    assert monitor._capture_tmp_dir is None
    assert archive_calls == [True]
    assert cleanup_calls == [True]


class FailOnceWaitCaptureProcess(FakeCaptureProcess):
    def __init__(self):
        super().__init__()
        self.wait_attempts = 0

    async def wait(self):
        self.wait_attempts += 1
        if self.wait_attempts == 1:
            self.wait_called = True
            raise RuntimeError("simulated wait failure")
        return await super().wait()


@pytest.mark.asyncio
async def test_stop_defers_capture_cleanup_and_mode_restore_until_process_is_reaped(
    monkeypatch
):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    process = FailOnceWaitCaptureProcess()
    monitor._running = True
    monitor._process = process
    monitor._capture_tmp_dir = "/private/capture"

    restore_managed_mode = AsyncMock()
    archive_calls = []
    cleanup_calls = []
    summary_messages = []

    async def emit_summary(message):
        summary_messages.append(message)

    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_archive_pcap_sync", lambda: archive_calls.append(True))
    monkeypatch.setattr(
        monitor,
        "_cleanup_capture_temp_dir",
        lambda: (cleanup_calls.append(True), setattr(monitor, "_capture_tmp_dir", None)),
    )
    monkeypatch.setattr(monitor, "_emit_capture_summary", emit_summary)

    await monitor.stop()

    assert process.wait_attempts == 1
    assert process.returncode is None
    assert monitor._process is process
    assert monitor._capture_tmp_dir == "/private/capture"
    restore_managed_mode.assert_not_awaited()
    assert archive_calls == []
    assert cleanup_calls == []
    assert summary_messages == [
        "Monitoring shutdown incomplete; capture process could not be reaped."
    ]

    # The next stop() retries wait/reap and only then restores the adapter and
    # archives/removes the private temporary capture directory.
    await monitor.stop()

    assert process.wait_attempts == 2
    assert process.returncode == 0
    assert monitor._process is None
    assert monitor._capture_tmp_dir is None
    restore_managed_mode.assert_awaited_once()
    assert archive_calls == [True]
    assert cleanup_calls == [True]
    assert summary_messages[-1] == "Monitoring stopped."


@pytest.mark.asyncio
async def test_stop_finishes_process_reaping_after_repeated_caller_cancellation(
    monkeypatch,
):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    wait_started = asyncio.Event()
    allow_reap = asyncio.Event()

    class BlockingWaitCaptureProcess(FakeCaptureProcess):
        def __init__(self):
            super().__init__()
            self.wait_calls = 0

        async def wait(self):
            self.wait_calls += 1
            self.wait_called = True
            wait_started.set()
            await allow_reap.wait()
            self.returncode = 0
            return self.returncode

    process = BlockingWaitCaptureProcess()
    monitor._process = process
    monitor._capture_tmp_dir = "/private/capture"

    restore_managed_mode = AsyncMock()
    emit_capture_summary = AsyncMock()
    archive_calls = []
    cleanup_calls = []

    def archive_capture():
        archive_calls.append(True)

    def cleanup_capture():
        cleanup_calls.append(True)
        monitor._capture_tmp_dir = None

    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_emit_capture_summary", emit_capture_summary)
    monkeypatch.setattr(monitor, "_archive_pcap_sync", archive_capture)
    monkeypatch.setattr(monitor, "_cleanup_capture_temp_dir", cleanup_capture)

    stop_task = asyncio.create_task(monitor.stop())
    await asyncio.wait_for(wait_started.wait(), timeout=1.0)

    # Both cancellation requests must be deferred until the protected cleanup
    # task has completed the wait that confirms the child was reaped.
    stop_task.cancel()
    await asyncio.sleep(0)
    stop_task.cancel()
    await asyncio.sleep(0)
    assert not stop_task.done()

    allow_reap.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stop_task, timeout=2.0)

    assert process.terminate_called is True
    assert process.wait_calls == 1
    assert process.returncode == 0
    assert monitor._process is None
    assert monitor._capture_tmp_dir is None
    restore_managed_mode.assert_awaited_once()
    emit_capture_summary.assert_awaited_once_with("Monitoring stopped.")
    assert archive_calls == [True]
    assert cleanup_calls == [True]


class FailPostKillWaitCaptureProcess(FakeCaptureProcess):
    def __init__(self):
        super().__init__()
        self.wait_attempts = 0

    async def wait(self):
        self.wait_attempts += 1
        if self.wait_attempts == 1:
            raise TimeoutError("simulated graceful wait timeout")
        if self.wait_attempts == 2:
            raise RuntimeError("simulated post-kill wait failure")
        self.returncode = 0
        self.wait_called = True
        return self.returncode

    def kill(self):
        self.kill_called = True
        # Keep returncode unset until wait() confirms the child was reaped.


@pytest.mark.asyncio
async def test_stop_retains_child_and_capture_files_after_post_kill_wait_failure(
    monkeypatch,
):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    process = FailPostKillWaitCaptureProcess()
    monitor._process = process
    monitor._capture_tmp_dir = "/private/capture"

    restore_managed_mode = AsyncMock()
    emit_capture_summary = AsyncMock()
    archive_calls = []
    cleanup_calls = []

    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_emit_capture_summary", emit_capture_summary)
    monkeypatch.setattr(
        monitor, "_archive_pcap_sync", lambda: archive_calls.append(True)
    )

    def cleanup_capture():
        cleanup_calls.append(True)
        monitor._capture_tmp_dir = None

    monkeypatch.setattr(monitor, "_cleanup_capture_temp_dir", cleanup_capture)

    await monitor.stop()

    assert process.terminate_called is True
    assert process.kill_called is True
    assert process.wait_attempts == 2
    assert process.returncode is None
    assert monitor._process is process
    assert monitor._capture_tmp_dir == "/private/capture"
    restore_managed_mode.assert_not_awaited()
    assert archive_calls == []
    assert cleanup_calls == []
    emit_capture_summary.assert_awaited_once_with(
        "Monitoring shutdown incomplete; capture process could not be reaped."
    )

    # A later stop() retries reaping before restoring the interface or touching
    # any capture file, preventing loss of a still-running child's output.
    await monitor.stop()

    assert process.wait_attempts == 3
    assert process.returncode == 0
    assert monitor._process is None
    assert monitor._capture_tmp_dir is None
    restore_managed_mode.assert_awaited_once()
    assert archive_calls == [True]
    assert cleanup_calls == [True]


@pytest.mark.asyncio
async def test_stop_orders_reaping_restore_archive_and_persistence(monkeypatch):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    events = []

    class OrderedCaptureProcess:
        returncode = None

        def terminate(self):
            events.append("terminate")

        async def wait(self):
            events.append("reap")
            self.returncode = 0
            return self.returncode

        def kill(self):
            events.append("kill")
            self.returncode = -9

    class OrderedNetworkPersistence:
        def save(self):
            assert monitor._capture_tmp_dir is None
            events.append("network-save")

    class OrderedMoodPersistence:
        def update_mood(self, mood):
            events.append(f"mood:{mood}")

        def apply_reward(self, reward, *, event):
            events.append(f"reward:{event}")

    process = OrderedCaptureProcess()
    monitor._running = True
    monitor._process = process
    monitor._capture_tmp_dir = "/private/capture"
    monitor.persistent_network = OrderedNetworkPersistence()
    monitor.persistent_mood = OrderedMoodPersistence()

    async def restore_managed_mode():
        assert process.returncode is not None
        assert monitor._process is None
        events.append("restore-managed-mode")

    def archive_capture():
        assert monitor._process is None
        assert monitor._capture_tmp_dir == "/private/capture"
        events.append("archive")

    def cleanup_capture():
        assert "archive" in events
        events.append("cleanup-temp")
        monitor._capture_tmp_dir = None

    async def emit_summary(message):
        events.append(f"summary:{message}")

    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_archive_pcap_sync", archive_capture)
    monkeypatch.setattr(monitor, "_cleanup_capture_temp_dir", cleanup_capture)
    monkeypatch.setattr(monitor, "_emit_capture_summary", emit_summary)

    await monitor.stop()

    assert events == [
        "terminate",
        "reap",
        "restore-managed-mode",
        "archive",
        "cleanup-temp",
        "network-save",
        "mood:neutral",
        "reward:session_end",
        "summary:Monitoring stopped.",
    ]
    assert monitor._process is None
    assert monitor._capture_tmp_dir is None
