# kaiagotchi/core/system.py
"""
Kaiagotchi Core System Monitor

This module provides:
- Environment setup (log/tmp directories)
- System metric utilities (uptime, memory, CPU load, temperature)
- Asynchronous ticker that periodically updates system metrics
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

_logger = logging.getLogger("kaiagotchi.core.system")


class SystemMetricsSnapshot(TypedDict):
    """Heterogeneous metric values emitted by one SystemTicker update."""

    uptime_seconds: float | None
    cpu_load: float | None
    meminfo: dict[str, Any]
    temperature: float | None
    timestamp: float


SystemTickCallback = Callable[
    [SystemMetricsSnapshot],
    None | Awaitable[None],
]


# ==========================================================
# Environment setup
# ==========================================================
def setup_environment(config: dict[str, Any] | None = None) -> None:
    """Ensure required directories exist for Kaiagotchi."""
    _logger.info("Setting up Kaiagotchi environment...")
    directories = [
        "/etc/kaiagotchi",
        "/var/log/kaiagotchi",
        "/var/tmp/kaiagotchi",
    ]
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            _logger.debug("Ensured directory exists: %s", directory)
        except Exception as e:
            _logger.warning("Failed to create %s: %s", directory, e)
    _logger.info("Environment setup complete")


# ==========================================================
# Metric helpers (low-level sysinfo)
# ==========================================================
def uptime() -> float | None:
    """Return system uptime in seconds, or None if unavailable."""
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            return float(f.readline().split()[0])
    except Exception:
        return None


def mem_usage() -> dict[str, Any]:
    """Return a dict of memory info (kB), or empty if unavailable."""
    try:
        info: dict[str, Any] = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip()] = v.strip()
        return info
    except Exception:
        return {}


def cpu_load() -> float | None:
    """Return CPU load (1-min average) or None."""
    try:
        with open("/proc/loadavg", encoding="utf-8") as f:
            load = f.readline().split()[0]
            return float(load)
    except Exception:
        return None


def temperature() -> float | None:
    """Return CPU temperature in Celsius, or None."""
    try:
        temp_paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
            "/sys/class/hwmon/hwmon1/temp1_input",
        ]
        for path in temp_paths:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    temp = f.readline().strip()
                    return float(temp) / 1000.0
        return None
    except Exception:
        return None


# ==========================================================
# SystemTicker — async subsystem updater
# ==========================================================
class SystemTicker:
    """
    Async background task that updates system metrics periodically.

    Designed to integrate with kaiagotchi.data.system_types.SystemState.
    """

    def __init__(
        self,
        system_state: Any | None = None,
        *,
        interval: float = 2.0,
        on_tick: SystemTickCallback | None = None,
    ):
        self.system_state = system_state
        self.interval = interval
        self.on_tick = on_tick  # Optional callback hook
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_update: float = 0.0
        self._tick_count: int = 0

    async def start(self) -> None:
        """Start the async ticker loop."""
        if self._running:
            _logger.debug("SystemTicker already running")
            return
        _logger.info("SystemTicker started")
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the async ticker loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("SystemTicker stopped")

    async def _loop(self) -> None:
        """Internal loop: periodically update metrics."""
        while self._running:
            try:
                await self._tick()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.warning("SystemTicker error: %s", e)
                await asyncio.sleep(self.interval * 2)

    async def _tick(self) -> None:
        """Perform a single system metrics update."""
        metrics_data: SystemMetricsSnapshot = {
            "uptime_seconds": uptime(),
            "cpu_load": cpu_load(),
            "meminfo": mem_usage(),
            "temperature": temperature(),
            "timestamp": time.time(),
        }

        # Update system_state.metrics if available
        if self.system_state is not None:
            try:
                metrics = getattr(self.system_state, "metrics", None)
                if metrics:
                    if hasattr(metrics, "cpu_usage") and metrics_data["cpu_load"] is not None:
                        # Use psutil for an accurate percentage; fall back to load average
                        # scaled by cpu_count if psutil is unavailable.
                        try:
                            import psutil as _psutil
                            metrics.cpu_usage = _psutil.cpu_percent(interval=None)
                        except Exception:
                            import os
                            cpu_count = os.cpu_count() or 1
                            metrics.cpu_usage = min(100.0, (metrics_data["cpu_load"] / cpu_count) * 100.0)
                    if hasattr(metrics, "memory_usage") and "MemTotal" in metrics_data["meminfo"]:
                        meminfo = metrics_data["meminfo"]
                        total = float(meminfo.get("MemTotal", "0 kB").split()[0])
                        free = float(meminfo.get("MemAvailable", "0 kB").split()[0])
                        metrics.memory_usage = 100.0 - (free / total * 100.0) if total > 0 else 0.0
                    if hasattr(metrics, "uptime_seconds") and metrics_data["uptime_seconds"] is not None:
                        metrics.uptime_seconds = metrics_data["uptime_seconds"]
                self.system_state.metrics = metrics
            except Exception:
                _logger.debug("SystemTicker: failed to apply metrics", exc_info=True)

        # Optional callback; support both regular functions and async hooks.
        if self.on_tick is not None:
            try:
                callback_result = self.on_tick(metrics_data)
                if inspect.isawaitable(callback_result):
                    await callback_result
            except Exception:
                _logger.debug("SystemTicker: on_tick callback failed", exc_info=True)

        self._tick_count += 1
        self._last_update = metrics_data["timestamp"]
        _logger.debug("SystemTicker tick #%d complete", self._tick_count)


# ==========================================================
# CLI diagnostics
# ==========================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kaiagotchi System Diagnostics")
    parser.add_argument("--interval", type=float, default=1.0, help="Tick interval (seconds)")
    parser.add_argument("--ticks", type=int, default=5, help="Number of ticks to run")
    args = parser.parse_args()

    async def main():
        async def show_tick(data: SystemMetricsSnapshot) -> None:
            uptime_value = data["uptime_seconds"]
            uptime_text = f"{uptime_value:.1f}s" if uptime_value is not None else "unavailable"
            print(
                f"[{time.strftime('%H:%M:%S')}] CPU={data['cpu_load']}, "
                f"TEMP={data['temperature']}, UP={uptime_text}"
            )

        ticker = SystemTicker(interval=args.interval, on_tick=show_tick)
        await ticker.start()
        await asyncio.sleep(args.ticks * args.interval)
        await ticker.stop()

    asyncio.run(main())
