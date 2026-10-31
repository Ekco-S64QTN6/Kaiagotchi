# filepath: kaiagotchi/network/action_manager.py
"""
InterfaceActionManager — Handles wireless interface setup, cleanup, and channel hopping
for Kaiagotchi monitoring and adaptive scanning systems.
"""

import asyncio
import logging
import os
import re
import shutil
from typing import Any


class InterfaceActionManager:
    """Manages network interface operations for Linux systems with improved error handling."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._interface = config.get("main", {}).get("iface", "wlan1")
        self._monitor_interface: str | None = None
        self._killed_processes: list[str] = []
        self._channel_hop_disabled = False
        self._channel_hop_disabled_logged = False

        # ✅ Shared View reference for UI updates
        self.view = None

        # Channel hopping setup
        self._channel_list = config.get("personality", {}).get("channels", [])
        if not self._channel_list:
            self._channel_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        self._channel_index = 0

        self.logger.info(
            f"ActionManager initialized for interface '{self._interface}' "
            f"with channel list: {self._channel_list}"
        )

    def set_monitor_interface(self, interface: str) -> None:
        """Pin channel hopping and cleanup to the dedicated capture interface."""
        interface = interface.strip()
        if not interface:
            raise ValueError("monitor interface cannot be empty")
        self._interface = interface
        self._monitor_interface = interface
        self.logger.info("ActionManager pinned to monitor interface '%s'", interface)

    # ------------------------------------------------------------------
    async def hop_channel(self, interface: str | None = None) -> bool:
        """
        Cycle the monitor interface to the next channel in the configured list.
        Immediately pushes a UI update with the new channel if possible.
        """
        if getattr(self, "_channel_hop_disabled", False):
            if not getattr(self, "_channel_hop_disabled_logged", False):
                self.logger.warning("Channel hopping disabled due to permission issues.")
                self._channel_hop_disabled_logged = True
            return False

        iface_to_use = interface or self._monitor_interface or self._interface

        if not await self._interface_exists(iface_to_use):
            self.logger.error(f"Cannot hop channel: interface {iface_to_use} not found.")
            return False

        if not self._channel_list:
            self.logger.warning("No channels configured for hopping.")
            return False

        self._channel_index = (self._channel_index + 1) % len(self._channel_list)
        next_channel = self._channel_list[self._channel_index]

        self.logger.debug(f"Hopping {iface_to_use} → channel {next_channel}")

        try:
            proc = await asyncio.create_subprocess_exec(
                "iw", "dev", iface_to_use, "set", "channel", str(next_channel),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await self._communicate_with_timeout(proc, timeout=5.0, command=' '.join(('iw', 'dev', iface_to_use, 'set', 'channel', str(next_channel))))

            if proc.returncode == 0:
                self.logger.debug(f"Hopped to channel {next_channel} via iw")
                if self.view:
                    try:
                        await self.view.async_update({"channel": str(next_channel)})
                    except Exception as e:
                        self.logger.debug(f"Failed to update view channel {next_channel}: {e}")
                return True

            error_msg = stderr.decode().strip()
            if "permission denied" in error_msg.lower() or "operation not permitted" in error_msg.lower():
                self._channel_hop_disabled = True
                self._channel_hop_disabled_logged = True
                self.logger.error("Permission denied while hopping channel — disabling further attempts.")
                return False

            self.logger.error(f"iw failed (code {proc.returncode}): {error_msg}")
            return await self._hop_channel_iwconfig(iface_to_use, next_channel)

        except FileNotFoundError:
            self.logger.error("iw not found, falling back to iwconfig...")
            return await self._hop_channel_iwconfig(iface_to_use, next_channel)
        except TimeoutError:
            self.logger.error("Timeout while setting channel via iw.")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error hopping channel: {e}")
            return False

    # ------------------------------------------------------------------
    async def _hop_channel_iwconfig(self, interface: str, channel: int) -> bool:
        """Fallback to iwconfig for legacy drivers."""
        try:
            self.logger.warning(f"Fallback: hopping {interface} to channel {channel} with iwconfig.")
            proc = await asyncio.create_subprocess_exec(
                "iwconfig", interface, "channel", str(channel),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await self._communicate_with_timeout(proc, timeout=5.0, command=' '.join(('iwconfig', interface, 'channel', str(channel))))

            if proc.returncode == 0:
                self.logger.info(f"iwconfig hop success: {interface} → channel {channel}")
                if self.view:
                    try:
                        await self.view.async_update({"channel": str(channel)})
                    except Exception as e:
                        self.logger.debug(f"View update after iwconfig hop failed: {e}")
                return True

            self.logger.error(f"iwconfig failed: {stderr.decode().strip()}")
            return False

        except Exception as e:
            self.logger.error(f"iwconfig hop failed: {e}")
            return False

    # ------------------------------------------------------------------
    async def _interface_exists(self, interface: str) -> bool:
        """Check if an interface exists."""
        try:
            return os.path.exists(f"/sys/class/net/{interface}")
        except Exception:
            return False

    # ------------------------------------------------------------------
    async def get_interface_info(self, interface: str) -> dict[str, Any]:
        """
        Gather interface mode, frequency, and status info.
        Uses iw first; falls back to iwconfig if not available.
        """
        try:
            info = await self._get_iw_info(interface)
            if not info or "mode" not in info:
                info = await self._get_iwconfig_info(interface)
            return info
        except Exception as e:
            self.logger.error(f"Failed to get interface info for {interface}: {e}")
            return {}

    async def _get_iw_info(self, interface: str) -> dict[str, Any]:
        """Parse info from 'iw dev <iface> info'."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "iw", "dev", interface, "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await self._communicate_with_timeout(proc, timeout=3.0, command=f'iw dev {interface} info')
            if proc.returncode != 0:
                return {}

            output = stdout.decode(errors="ignore")
            info: dict[str, Any] = {}
            for line in output.splitlines():
                if "type" in line:
                    info["mode"] = line.split()[-1].lower()
                elif "channel" in line:
                    match = re.search(r"channel\s+(\d+)", line)
                    if match:
                        info["channel"] = int(match.group(1))
            return info
        except Exception:
            return {}

    async def _get_iwconfig_info(self, interface: str) -> dict[str, Any]:
        """Parse output from iwconfig as a fallback."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "iwconfig", interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await self._communicate_with_timeout(proc, timeout=3.0, command=f'iwconfig {interface}')
            if proc.returncode != 0:
                return {}

            output = stdout.decode(errors="ignore")
            info: dict[str, Any] = {}

            if "Mode:" in output:
                match = re.search(r"Mode:(\w+)", output)
                if match:
                    info["mode"] = match.group(1).lower()
            if "Frequency:" in output:
                freq_match = re.search(r"Frequency:(\d+\.\d+)", output)
                if freq_match:
                    freq = float(freq_match.group(1))
                    info["channel"] = self._frequency_to_channel(freq)
            return info
        except Exception:
            return {}

    def _frequency_to_channel(self, freq: float) -> int:
        """Convert frequency (GHz) to Wi-Fi channel."""
        if 2.412 <= freq <= 2.484:
            return int((freq - 2.412) / 0.005 + 1)
        elif 5.17 <= freq <= 5.825:
            return int((freq - 5.17) / 0.005 + 34)
        return 0

    # ------------------------------------------------------------------
    async def _communicate_with_timeout(
        self,
        proc: asyncio.subprocess.Process,
        *,
        timeout: float,
        command: str,
    ) -> tuple[bytes, bytes]:
        """Communicate with a subprocess under a deadline and always reap it.

        Shield the communication task so timeout cancellation does not interrupt
        pipe draining before we terminate the child. Cancellation follows the
        same cleanup path so shutdown cannot orphan a privileged tool.
        """
        communicate_task = asyncio.create_task(proc.communicate())
        try:
            return await asyncio.wait_for(
                asyncio.shield(communicate_task),
                timeout=max(0.01, float(timeout)),
            )
        except (TimeoutError, asyncio.CancelledError):
            if proc.returncode is None:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass

            # Killing the process should close its pipes and let communicate()
            # reap it. Bound this cleanup too, in case a descendant inherited a
            # pipe handle or a test double violates subprocess semantics.
            try:
                await asyncio.wait_for(asyncio.shield(communicate_task), timeout=1.0)
            except TimeoutError:
                communicate_task.cancel()
                await asyncio.gather(communicate_task, return_exceptions=True)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except (TimeoutError, ProcessLookupError):
                    self.logger.error("Timed out reaping wireless command %s", command)
            except Exception:
                self.logger.debug("Error draining terminated command %s", command, exc_info=True)
            raise

    async def _run_checked(self, *command: str) -> None:
        """Run one interface command and fail if the process reports an error."""
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await self._communicate_with_timeout(proc, timeout=5.0, command=' '.join(command))
        if proc.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"Command {' '.join(command)!r} failed with exit code {proc.returncode}"
                + (f": {detail}" if detail else "")
            )

    async def set_monitor_mode(self, interface: str) -> bool:
        """Set the dedicated capture interface into monitor mode."""
        target = self._monitor_interface or interface or self._interface
        try:
            if not await self._interface_exists(target):
                self.logger.error("Cannot set monitor mode: interface %s not found", target)
                return False

            self.logger.info("Setting %s into monitor mode...", target)
            if shutil.which("nmcli"):
                await self._run_checked("nmcli", "device", "set", target, "managed", "no")

            await self._run_checked("ip", "link", "set", "dev", target, "down")
            await self._run_checked("iw", "dev", target, "set", "type", "monitor")
            await self._run_checked("ip", "link", "set", "dev", target, "up")

            info = await self.get_interface_info(target)
            if info.get("mode") != "monitor":
                raise RuntimeError(f"Interface {target} did not enter monitor mode")

            self._monitor_interface = target
            if self.view:
                await self.view.async_update({"status": "Interface in monitor mode"})
            return True
        except Exception as e:
            self.logger.error("Failed to set monitor mode for %s: %s", target, e)
            return False

    async def set_managed_mode(self, interface: str) -> bool:
        """Return the dedicated capture interface to managed mode."""
        target = self._monitor_interface or interface or self._interface
        try:
            if not await self._interface_exists(target):
                self.logger.error("Cannot restore managed mode: interface %s not found", target)
                return False

            self.logger.info("Restoring managed mode for %s", target)
            await self._run_checked("ip", "link", "set", "dev", target, "down")
            await self._run_checked("iw", "dev", target, "set", "type", "managed")
            await self._run_checked("ip", "link", "set", "dev", target, "up")
            if shutil.which("nmcli"):
                await self._run_checked("nmcli", "device", "set", target, "managed", "yes")

            info = await self.get_interface_info(target)
            if info.get("mode") not in {"managed", "unknown"}:
                raise RuntimeError(f"Interface {target} did not return to managed mode")

            self._monitor_interface = None
            if self.view:
                await self.view.async_update({"status": "Interface restored to managed mode"})
            return True
        except Exception as e:
            self.logger.error("Failed to restore managed mode for %s: %s", target, e)
            return False

    # ------------------------------------------------------------------
    async def _restart_network_services(self):
        """Attempt to restart network services after cleanup."""
        try:
            for svc in ("NetworkManager", "wpa_supplicant", "systemd-networkd"):
                proc = await asyncio.create_subprocess_exec(
                    "systemctl", "restart", svc,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await self._communicate_with_timeout(
                    proc, timeout=15.0, command=f"systemctl restart {svc}"
                )
                if proc.returncode != 0:
                    self.logger.warning(
                        "systemctl restart %s exited %s: %s",
                        svc, proc.returncode, stderr.decode(errors="replace").strip(),
                    )
            self.logger.info("Network services restart attempts completed.")
        except Exception as e:
            self.logger.warning(f"Failed to restart network services: {e}")

    # ------------------------------------------------------------------
    async def cleanup(self):
        """Restore managed mode and restart network services if needed."""
        try:
            self.logger.info("Performing network cleanup...")

            info = await self.get_interface_info(self._interface)
            if info.get("mode") == "monitor":
                await self.set_managed_mode(self._interface)

            if self._killed_processes:
                await self._restart_network_services()
                self._killed_processes.clear()

            self._monitor_interface = None
            self.logger.info("Network cleanup completed.")
        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")
