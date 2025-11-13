# filepath: kaiagotchi/network/action_manager.py
"""
InterfaceActionManager — Handles wireless interface setup, cleanup, and channel hopping
for Kaiagotchi monitoring and adaptive scanning systems.
"""

import asyncio
import logging
import os
import re
from typing import Dict, Any, List, Optional


class InterfaceActionManager:
    """Manages network interface operations for Linux systems with improved error handling."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._interface = config.get("main", {}).get("iface", "wlan1")
        self._monitor_interface: Optional[str] = None
        self._killed_processes: List[str] = []
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

    # ------------------------------------------------------------------
    async def hop_channel(self, interface: Optional[str] = None) -> bool:
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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)

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
        except asyncio.TimeoutError:
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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)

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
            proc = await asyncio.create_subprocess_exec(
                "ip", "link", "show", "dev", interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    async def get_interface_info(self, interface: str) -> Dict[str, Any]:
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

    async def _get_iw_info(self, interface: str) -> Dict[str, Any]:
        """Parse info from 'iw dev <iface> info'."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "iw", "dev", interface, "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode != 0:
                return {}

            output = stdout.decode(errors="ignore")
            info = {}
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

    async def _get_iwconfig_info(self, interface: str) -> Dict[str, Any]:
        """Parse output from iwconfig as a fallback."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "iwconfig", interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode != 0:
                return {}

            output = stdout.decode(errors="ignore")
            info = {}

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
    async def set_monitor_mode(self, interface: str) -> bool:
        """Set the interface into monitor mode."""
        try:
            self.logger.info(f"Setting {interface} into monitor mode...")
            proc = await asyncio.create_subprocess_exec(
                "ip", "link", "set", interface, "down",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await asyncio.create_subprocess_exec("iw", interface, "set", "monitor", "none")
            await asyncio.create_subprocess_exec("ip", "link", "set", interface, "up")

            self._monitor_interface = interface
            if self.view:
                await self.view.async_update({"status": "Interface in monitor mode"})
            return True
        except Exception as e:
            self.logger.error(f"Failed to set monitor mode for {interface}: {e}")
            return False

    async def set_managed_mode(self, interface: str) -> bool:
        """Return the interface to managed mode."""
        try:
            self.logger.info(f"Restoring managed mode for {interface}")
            await asyncio.create_subprocess_exec(
                "ip", "link", "set", interface, "down",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.create_subprocess_exec("iw", interface, "set", "type", "managed")
            await asyncio.create_subprocess_exec("ip", "link", "set", interface, "up")

            if self.view:
                await self.view.async_update({"status": "Interface restored to managed mode"})
            return True
        except Exception as e:
            self.logger.error(f"Failed to restore managed mode: {e}")
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
                await proc.communicate()
            self.logger.info("Network services restarted.")
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
