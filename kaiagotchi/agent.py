import time
import json
import os
import re
import logging
import asyncio
import threading
import subprocess
from typing import Dict, Any, Optional, List, Tuple

from .network.action_manager import InterfaceActionManager
from .network.utils import iface_channels, total_unique_handshakes
from .events import EventEmitter
from .web.server import Server
from .ui.base import BaseView


class Agent:
    """
    Main agent implementation handling network reconnaissance and interactions.
    """
    def __init__(self, view: BaseView, config: Dict[str, Any], keypair: Optional[Tuple[str, str]] = None):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Core components
        self.action_manager = InterfaceActionManager(config)
        self.events = EventEmitter()
        self._view = view
        self._view.set_agent(self)
        self._web_ui = Server(self, config['ui'])

        # State tracking
        self._started_at = time.time()
        self._current_channel = 0
        self._tot_aps = 0
        self._aps_on_channel = 0
        self._supported_channels = iface_channels(config['main']['iface'])

        # Access point tracking
        self._access_points: List[Dict[str, Any]] = []
        self._last_pwnd: Optional[str] = None
        self._history: Dict[str, int] = {}
        self._handshakes: Dict[str, Dict[str, Any]] = {}

        # Ensure handshakes directory exists
        if not os.path.exists(config['network']['handshakes']):
            os.makedirs(config['network']['handshakes'])

    async def start(self):
        """Initialize and start the agent's operations."""
        try:
            await self._wait_for_network()
            await self.setup_events()
            await self.start_monitor_mode()
            self._start_background_tasks()

            while True:
                try:
                    await self.run_recon_cycle()
                    await asyncio.sleep(5.0)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Error in main loop: {e}", exc_info=True)

        except asyncio.CancelledError:
            self.logger.info("Agent stopping...")
        finally:
            await self._cleanup()

    async def _wait_for_network(self):
        """Wait for network interface to be ready."""
        while True:
            try:
                await self.action_manager.check_interface()
                return
            except Exception:
                self.logger.info("Waiting for network interface...")
                await asyncio.sleep(1)

    async def setup_events(self):
        """Configure event handling."""
        for tag in self.config['network'].get('silence', []):
            try:
                await self.action_manager.ignore_event(tag)
            except Exception:
                pass

    async def start_monitor_mode(self):
        """Initialize monitor mode on the wireless interface."""
        iface = self.config['main']['iface']
        mon_start_cmd = self.config['main'].get('mon_start_cmd')

        has_mon = False
        while not has_mon:
            interfaces = await self.action_manager.get_interfaces()
            has_mon = any(i['name'] == iface and i['mode'] == 'monitor' for i in interfaces)

            if not has_mon:
                if mon_start_cmd:
                    self.logger.info("Starting monitor interface...")
                    await self.action_manager.run_command(mon_start_cmd)
                else:
                    self.logger.info(f"Waiting for monitor interface {iface}...")
                    await asyncio.sleep(1)

        self.logger.info(f"Monitor mode active on {iface}")
        self.logger.info(f"Supported channels: {self._supported_channels}")
        await self._reset_wifi_settings()

    async def _reset_wifi_settings(self):
        """Apply baseline wireless settings."""
        config = self.config['network']
        await self.action_manager.configure_interface(
            interface=self.config['main']['iface'],
            settings={
                'ap_ttl': config['ap_ttl'],
                'sta_ttl': config['sta_ttl'],
                'min_rssi': config['min_rssi'],
                'handshakes_path': config['handshakes']
            }
        )

    def _start_background_tasks(self):
        """Start background monitoring threads."""
        threading.Thread(
            target=self._stats_monitor,
            name="Stats Monitor",
            daemon=True
        ).start()

    async def run_recon_cycle(self):
        """Execute one reconnaissance cycle."""
        try:
            channels = self.config['network'].get('channels', [])
            recon_time = self.config['network']['recon_time']

            # Update access point list
            aps = await self.action_manager.get_access_points()
            self._access_points = self._filter_access_points(aps)

            # Channel hopping
            if not channels:
                await self.action_manager.clear_channel()
                self._current_channel = 0
            else:
                channel = self._select_next_channel(channels)
                await self.action_manager.set_channel(channel)
                self._current_channel = channel

            # Wait for reconnaissance period
            await asyncio.sleep(recon_time)

        except Exception as e:
            self.logger.error(f"Error in recon cycle: {e}", exc_info=True)

    def _filter_access_points(self, aps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter access points based on criteria."""
        whitelist = self.config['network'].get('whitelist', [])
        return [
            ap for ap in aps
            if ap['encryption'] not in ('', 'OPEN') and
            ap['hostname'] not in whitelist and
            ap['mac'].lower() not in whitelist
        ]

    # ... Additional helper methods as needed ...
