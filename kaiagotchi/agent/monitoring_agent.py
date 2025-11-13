"""
MonitoringAgent — launches airodump-ng in a PTY, parses the CSV for AP and station
lists, and pushes structured data to the View / TerminalDisplay.

Enhanced with Epoch and Reward System Integration:
- Updates Epoch tracker with real-time network data for reward calculations
- Properly records BSSIDs and stations to PersistentNetwork
- Integrates with Epoch system for activity tracking and mood updates
- Ensures reward system receives discovery events and network state
"""

from __future__ import annotations
import asyncio
import csv
import logging
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from kaiagotchi.storage.persistent_network import PersistentNetwork
from kaiagotchi.storage.persistent_mood import PersistentMood
from kaiagotchi.storage.utils_time import TZ
from kaiagotchi.ui.voice import Voice

_LOG = logging.getLogger("kaiagotchi.agent.monitoring")

PCAP_STORAGE_DIR = Path("kaiagotchi/storage/pcaps")


class MonitoringAgent:
    def __init__(
        self,
        interface: Optional[str] = None,
        view=None,
        config: Optional[Dict[str, Any]] = None,
        system_state: Optional[Any] = None,
        state_lock: Optional[asyncio.Lock] = None,
    ):
        self.view = view
        self.config = config or {}
        self.system_state = system_state or {}
        self.state_lock = state_lock or asyncio.Lock()

        self.interface = (
            interface
            or (self.config.get("interface") if isinstance(self.config, dict) else None)
            or os.getenv("KAIAGOTCHI_INTERFACE")
            or "wlan1"
        )

        self._running = False
        self._process: Optional[asyncio.subprocess.Process] = None
        self._csv_path: Optional[Path] = None
        self._base_path: Optional[Path] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._start_time = time.time()

        self._seen_bssids: set[str] = set()
        self._seen_stations: set[str] = set()
        self._session_pcap: Optional[Path] = None

        self._max_aps_seen: int = 0

        ui_cfg = self.config.get("ui", {}) if isinstance(self.config, dict) else {}
        self._max_ap_records: int = int(ui_cfg.get("max_ap_records", 200))
        self._max_station_records: int = int(ui_cfg.get("max_station_records", 400))

        self.refresh_interval = float(
            self.config.get("monitor", {}).get("csv_poll", 1.0)
        ) or 1.0

        self.persistent_network: Optional[PersistentNetwork] = None
        self.persistent_mood: Optional[PersistentMood] = None
        self.epoch_tracker = None  # Will be set by agent
        self.reward_engine = None  # Will be set by agent
        self.voice = Voice()

        self._ensure_recent_captures()
        _LOG.info(f"[monitoring] Using interface: {self.interface}")

    # ------------------------------------------------------------------
    def _ensure_recent_captures(self) -> None:
        try:
            if isinstance(self.system_state, dict):
                self.system_state.setdefault("recent_captures", [])
                self.system_state.setdefault("chatter_log", [])
            elif not hasattr(self.system_state, "recent_captures"):
                setattr(self.system_state, "recent_captures", [])
                setattr(self.system_state, "chatter_log", [])
        except Exception:
            setattr(self, "_fallback_captures", [])
            _LOG.debug("[monitoring] Could not attach recent_captures; using fallback list")

    def _get_recent_captures_list(self) -> List[Dict[str, Any]]:
        if isinstance(self.system_state, dict):
            return self.system_state.setdefault("recent_captures", [])
        elif hasattr(self.system_state, "recent_captures"):
            return getattr(self.system_state, "recent_captures")
        return getattr(self, "_fallback_captures", [])

    # ------------------------------------------------------------------
    def set_persistence(self, persistence: PersistentNetwork) -> None:
        self.persistent_network = persistence
        _LOG.info("[monitoring] PersistentNetwork attached.")

    def set_mood_persistence(self, mood: PersistentMood) -> None:
        self.persistent_mood = mood
        _LOG.info("[monitoring] PersistentMood attached.")

    def set_epoch_tracker(self, epoch_tracker) -> None:
        self.epoch_tracker = epoch_tracker
        _LOG.info("[monitoring] EpochTracker attached.")

    def set_reward_engine(self, reward_engine) -> None:
        self.reward_engine = reward_engine
        _LOG.info("[monitoring] RewardEngine attached.")

    # ------------------------------------------------------------------
    async def start(self):
        if self._running:
            _LOG.debug("[monitoring] Already running.")
            return
        self._running = True
        _LOG.info("[monitoring] Starting monitoring setup...")

        try:
            await self._set_monitor_mode()
        except Exception:
            _LOG.exception("[monitoring] monitor mode setup failed")

        if self.view:
            try:
                await self.view.async_update(
                    {"substatus": "Initializing packet capture...", "mode": "AUTO"}
                )
            except Exception:
                pass

        await self._launch_airodump()
        self._loop_task = asyncio.create_task(self._scan_loop())

        if self.persistent_mood:
            try:
                if hasattr(self.persistent_mood, "update_mood"):
                    self.persistent_mood.update_mood("curious")
            except Exception:
                _LOG.debug("Failed to nudge persistent_mood to curious", exc_info=True)

        await self._emit_capture_summary("Monitoring initialized.")
        _LOG.info("[monitoring] Monitoring started.")

    # ------------------------------------------------------------------
    async def stop(self):
        if not self._running:
            return
        _LOG.info("[monitoring] Stopping agent...")
        self._running = False

        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        if self._process:
            try:
                self._process.terminate()
                await asyncio.sleep(0.2)
                if self._process.returncode is None:
                    self._process.kill()
                    await self._process.wait()
            except Exception:
                pass

        try:
            await self._restore_managed_mode()
        except Exception:
            pass

        try:
            if self.persistent_network:
                self.persistent_network.save()
        except Exception:
            _LOG.exception("[monitoring] Failed to save network history")

        if self.persistent_mood:
            try:
                if hasattr(self.persistent_mood, "update_mood"):
                    self.persistent_mood.update_mood("neutral")
                if hasattr(self.persistent_mood, "apply_reward"):
                    self.persistent_mood.apply_reward(-0.2, event="session_end")
            except Exception:
                _LOG.debug("persistent_mood shutdown hooks failed", exc_info=True)

        await self._archive_pcap()
        await self._emit_capture_summary("Monitoring stopped.")
        _LOG.info("[monitoring] Stopped cleanly.")

    # ------------------------------------------------------------------
    async def _set_monitor_mode(self):
        import subprocess
        subprocess.run(["ip", "link", "set", self.interface, "down"], check=False)
        subprocess.run(["iwconfig", self.interface, "mode", "monitor"], check=False)
        subprocess.run(["ip", "link", "set", self.interface, "up"], check=False)

    async def _restore_managed_mode(self):
        import subprocess
        subprocess.run(["ip", "link", "set", self.interface, "down"], check=False)
        subprocess.run(["iwconfig", self.interface, "mode", "managed"], check=False)
        subprocess.run(["ip", "link", "set", self.interface, "up"], check=False)

    # ------------------------------------------------------------------
    async def _launch_airodump(self):
        session_time = datetime.now(TZ).strftime("%Y-%m-%dT%H-%M-%S")
        base_name = f"{session_time}_session"
        self._base_path = Path("/tmp") / f"kaiagotchi_{os.getpid()}"
        self._csv_path = Path(f"{self._base_path}-01.csv")
        self._session_pcap = Path(f"{self._base_path}-01.cap")
        PCAP_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

        args = [
            "airodump-ng",
            "--write",
            str(self._base_path),
            "--output-format",
            "csv,pcap",
            "--write-interval",
            "2",
            self.interface,
        ]

        _LOG.info(f"[monitoring] Launching airodump: {' '.join(args)}")
        self._process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        _LOG.info(f"[monitoring] airodump started; CSV: {self._csv_path}")

    # ------------------------------------------------------------------
    async def _emit_capture_summary(self, message: str):
        """Append a structured line to System Chatter + View."""
        try:
            now_str = datetime.now(TZ).strftime("%H:%M:%S")
            voice_line = self.voice.get_event_line(message)
            summary_msg = voice_line or message
            new_entry = {"timestamp": now_str, "message": summary_msg}

            async with self.state_lock:
                captures = self._get_recent_captures_list()
                captures.append(new_entry)
                if len(captures) > 10:
                    captures[:] = captures[-10:]

                if isinstance(self.system_state, dict):
                    self.system_state["recent_captures"] = list(captures)
                    self.system_state["chatter_log"] = list(captures)
                else:
                    setattr(self.system_state, "recent_captures", list(captures))
                    setattr(self.system_state, "chatter_log", list(captures))

            if self.view:
                await self.view.async_update({
                    "recent_captures": list(captures),
                    "chatter_log": list(captures)
                })

        except Exception:
            _LOG.debug("[monitoring] Failed to emit capture summary", exc_info=True)

    # ------------------------------------------------------------------
    async def _archive_pcap(self):
        """Register the session PCAP directly with persistence (no copy)."""
        try:
            src = Path(f"{self._base_path}-01.cap")
            if not src.exists():
                _LOG.debug("[monitoring] No .cap file found to archive.")
                return

            self._session_pcap = src
            src_size = src.stat().st_size
            _LOG.info(f"[monitoring] Found session PCAP: {src.name} ({src_size} bytes)")

            if self.persistent_network:
                try:
                    # Generate clean filename without BSSID placeholder
                    timestamp = datetime.now(TZ).strftime("%Y-%m-%dT%H-%M-%S")
                    clean_filename = f"{timestamp}_airodump.pcap"
                    clean_dest = PCAP_STORAGE_DIR / clean_filename
                    
                    # Copy the file with clean name
                    import shutil
                    shutil.copy2(src, clean_dest)
                    _LOG.info(f"[monitoring] Copied PCAP to: {clean_dest}")
                    
                    # Register with persistent network using the clean file
                    self.persistent_network.add_pcap_file(
                        str(clean_dest), bssid=None, src_name="airodump", analyze=True
                    )
                    _LOG.info("[monitoring] Handed PCAP to PersistentNetwork.")
                except Exception:
                    _LOG.debug("persistent_network.add_pcap_file failed", exc_info=True)
            else:
                _LOG.debug("[monitoring] PersistentNetwork not attached; skipping registration.")

            await self._emit_capture_summary("Session PCAP archived.")
        except Exception:
            _LOG.exception("[monitoring] Failed to archive PCAP")

    # ------------------------------------------------------------------
    async def _scan_loop(self):
        try:
            while self._running:
                await asyncio.sleep(self.refresh_interval)
                if not self._csv_path or not self._csv_path.exists():
                    continue

                aps, stations = self._parse_airodump_csv(self._csv_path)

                if len(aps) > self._max_ap_records:
                    aps = aps[: self._max_ap_records]
                if len(stations) > self._max_station_records:
                    stations = stations[: self._max_station_records]

                aps = sorted(aps, key=lambda a: self._parse_last_seen_for_sort(a.get("last_seen", "")), reverse=True)

                new_aps = [a for a in aps if a["bssid"] not in self._seen_bssids]
                new_stations = [s for s in stations if s["station_mac"] not in self._seen_stations]

                # Update persistent network with discovered BSSIDs and stations
                if self.persistent_network:
                    try:
                        for ap in aps:
                            self.persistent_network.add_bssid(ap["bssid"], ap)
                        for station in stations:
                            self.persistent_network.add_station(station["station_mac"], station)
                    except Exception as e:
                        _LOG.debug("Failed to update persistent network: %s", e)

                for ap in new_aps:
                    self._seen_bssids.add(ap["bssid"])
                    await self._emit_capture_summary(f"New network detected: {ap['bssid']}")
                    try:
                        if self.persistent_mood and hasattr(self.persistent_mood, "apply_reward"):
                            self.persistent_mood.apply_reward(0.05, event="discover_ap")
                    except Exception:
                        _LOG.debug("persistent_mood.apply_reward failed", exc_info=True)

                for sta in new_stations:
                    self._seen_stations.add(sta["station_mac"])
                    await self._emit_capture_summary(f"New station detected: {sta['station_mac']}")
                    try:
                        if self.persistent_mood and hasattr(self.persistent_mood, "apply_reward"):
                            self.persistent_mood.apply_reward(0.02, event="discover_sta")
                    except Exception:
                        _LOG.debug("persistent_mood.apply_reward failed", exc_info=True)

                await self._update_state(aps, stations)
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOG.exception("[monitoring] CSV loop error")

    # ------------------------------------------------------------------
    def _parse_airodump_csv(self, csv_path: Path):
        aps, stations = [], []
        try:
            with open(csv_path, newline="", encoding="utf-8", errors="ignore") as fh:
                reader = csv.reader(fh)
                section = None
                for row in reader:
                    if not any(cell.strip() for cell in row):
                        continue
                    first = row[0].strip()
                    if first.startswith("BSSID"):
                        section = "aps"
                        continue
                    if first.startswith("Station MAC"):
                        section = "stations"
                        continue
                    if section == "aps" and len(row) >= 14:
                        ap_data = {
                            "bssid": row[0].strip(),
                            "first_seen": row[1].strip(),
                            "last_seen": row[2].strip(),
                            "channel": row[3].strip(),
                            "speed": row[4].strip(),
                            "privacy": row[5].strip() or "--",
                            "cipher": row[6].strip() or "--",
                            "auth": row[7].strip() or "--",
                            "power": row[8].strip(),
                            "beacons": row[9].strip(),
                            "iv": row[10].strip(),
                            "lan_ip": row[11].strip(),
                            "id_length": row[12].strip(),
                            "essid": row[13].strip(),
                        }
                        # Clean up ESSID (remove non-printable characters)
                        if ap_data["essid"]:
                            ap_data["essid"] = ''.join(char for char in ap_data["essid"] 
                                                     if char.isprintable() or char in ' _-')
                        aps.append(ap_data)
                    elif section == "stations" and len(row) >= 6:
                        station_data = {
                            "station_mac": row[0].strip(),
                            "first_seen": row[1].strip() if len(row) > 1 else "",
                            "last_seen": row[2].strip() if len(row) > 2 else "",
                            "power": row[3].strip() if len(row) > 3 else "",
                            "packets": row[4].strip() if len(row) > 4 else "",
                            "bssid": row[5].strip() if len(row) > 5 else "",
                            "probed_essids": row[6].strip() if len(row) > 6 else "",
                        }
                        stations.append(station_data)
            
            # Normalize privacy field
            for ap in aps:
                privacy = ap.get("privacy", "").upper()
                if privacy == "OPN":
                    ap["privacy"] = "OPEN"
                elif not privacy or privacy == "--":
                    ap["privacy"] = "UNKNOWN"
                    
        except Exception:
            _LOG.exception("[monitoring] Failed to parse CSV output")
        return aps, stations

    # ------------------------------------------------------------------
    def _parse_last_seen_for_sort(self, last_seen: str) -> float:
        if not last_seen:
            return 0.0
        s = str(last_seen).strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.timestamp()
            except Exception:
                pass
        try:
            dt = datetime.strptime(s, "%H:%M:%S")
            now = datetime.now()
            dt = dt.replace(year=now.year, month=now.month, day=now.day)
            return dt.timestamp()
        except Exception:
            pass
        try:
            return float(hash(s))
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    async def _update_state(self, aps: List[Dict[str, Any]], stations: List[Dict[str, Any]]):
        ap_count = len(aps)
        self._max_aps_seen = max(self._max_aps_seen, ap_count)
        uptime = time.strftime("%H:%M:%S", time.gmtime(time.time() - self._start_time))
        
        # Get recent captures for epoch tracking
        recent_captures = self._get_recent_captures_list()
        
        # Update epoch tracker with current network state
        if self.epoch_tracker and hasattr(self.epoch_tracker, 'update_network_state'):
            try:
                self.epoch_tracker.update_network_state(aps, stations, recent_captures)
                _LOG.debug("[monitoring] Updated epoch tracker with %d APs, %d stations", ap_count, len(stations))
            except Exception as e:
                _LOG.debug("Failed to update epoch tracker: %s", e)

        new_state = {
            "aps": ap_count,
            "aps_max_seen": self._max_aps_seen,
            "mode": "MONITORING",
            "uptime": uptime,
            "substatus": "Monitoring Wi-Fi traffic...",
            "aps_list": aps,
            "stations_list": stations,
            "recent_captures": recent_captures,
        }

        async with self.state_lock:
            if isinstance(self.system_state, dict):
                self.system_state.update(new_state)
            else:
                for k, v in new_state.items():
                    setattr(self.system_state, k, v)

        if self.view:
            try:
                await self.view.async_update({
                    "aps": ap_count,
                    "aps_max_seen": self._max_aps_seen,
                    "recent_captures": recent_captures,
                    "chatter_log": recent_captures,
                    "aps_list": aps,
                    "stations_list": stations,
                    "mode": "MONITORING",
                    "uptime": uptime,
                })
            except Exception:
                _LOG.debug("view.async_update failed in monitoring _update_state", exc_info=True)

        if self.view and hasattr(self.view, "display"):
            disp = getattr(self.view, "display")
            if hasattr(disp, "update_table"):
                try:
                    disp.update_table(aps, stations)
                except Exception:
                    _LOG.debug("display.update_table failed", exc_info=True)

    # ------------------------------------------------------------------
    def get_network_summary(self) -> Dict[str, Any]:
        """Get current network summary for debugging and UI."""
        return {
            "aps_count": len(self._seen_bssids),
            "stations_count": len(self._seen_stations),
            "max_aps_seen": self._max_aps_seen,
            "session_duration": time.time() - self._start_time,
            "interface": self.interface,
        }