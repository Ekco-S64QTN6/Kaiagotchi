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
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from kaiagotchi.storage.persistent_mood import PersistentMood
from kaiagotchi.storage.persistent_network import PersistentNetwork
from kaiagotchi.storage.utils_time import TZ
from kaiagotchi.ui.voice import Voice

_LOG = logging.getLogger("kaiagotchi.agent.monitoring")

# FIXED: Use absolute path based on project structure
PCAP_STORAGE_DIR = Path(__file__).parent.parent / "storage" / "pcaps"


class MonitoringAgent:
    def __init__(
        self,
        interface: str | None = None,
        view=None,
        config: dict[str, Any] | None = None,
        system_state: Any | None = None,
        state_lock: asyncio.Lock | None = None,
    ):
        self.view = view
        self.config = config or {}
        self.system_state = system_state if system_state is not None else {}
        self.state_lock = state_lock if state_lock is not None else asyncio.Lock()
        self._fallback_captures: list[dict[str, Any]] = []

        self.interface = (
            interface
            or (self.config.get("interface") if isinstance(self.config, dict) else None)
            or os.getenv("KAIAGOTCHI_INTERFACE")
            or "wlan1"
        )

        self._running = False
        self._process: asyncio.subprocess.Process | None = None
        self._csv_path: Path | None = None
        self._base_path: Path | None = None
        self._loop_task: asyncio.Task | None = None
        self._start_time = time.time()

        self._seen_bssids: set[str] = set()
        self._seen_stations: set[str] = set()
        # airodump CSV counters are cumulative for the current capture process;
        # retain the last observed values so each scan contributes only its delta.
        self._last_ap_counters: dict[str, dict[str, int]] = {}
        self._last_station_counters: dict[str, dict[str, int]] = {}
        self._last_persistence_save = 0.0
        self._session_pcap: Path | None = None
        self._capture_tmp_dir: Path | None = None

        self._max_aps_seen: int = 0

        ui_cfg = self.config.get("ui", {}) if isinstance(self.config, dict) else {}
        self._max_ap_records: int = int(ui_cfg.get("max_ap_records", 200))
        self._max_station_records: int = int(ui_cfg.get("max_station_records", 400))

        self.refresh_interval = float(
            self.config.get("monitor", {}).get("csv_poll", 1.0)
        ) or 1.0

        self.persistent_network: PersistentNetwork | None = None
        self.persistent_mood: PersistentMood | None = None
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
                self.system_state.recent_captures = []
                self.system_state.chatter_log = []
        except Exception:
            self._fallback_captures = []
            _LOG.debug("[monitoring] Could not attach recent_captures; using fallback list")

    def _get_recent_captures_list(self) -> list[dict[str, Any]]:
        if isinstance(self.system_state, dict):
            return self.system_state.setdefault("recent_captures", [])
        elif hasattr(self.system_state, "recent_captures"):
            return self.system_state.recent_captures
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
        except Exception as exc:
            _LOG.exception("[monitoring] monitor mode setup failed")
            self._running = False
            try:
                await self._restore_managed_mode()
            except Exception:
                _LOG.debug("[monitoring] Could not restore interface after setup failure", exc_info=True)
            raise RuntimeError(
                f"Could not configure capture interface {self.interface} for monitor mode"
            ) from exc

        if self.view:
            try:
                await self.view.async_update(
                    {"substatus": "Initializing packet capture...", "mode": "AUTO"}
                )
            except Exception:
                pass

        try:
            await self._launch_airodump()
        except Exception:
            # Do not leave the adapter in monitor mode when capture startup
            # fails (for example, airodump-ng missing or process creation denied).
            self._running = False
            try:
                await self._restore_managed_mode()
            except Exception:
                _LOG.debug(
                    "[monitoring] Could not restore interface after capture launch failure",
                    exc_info=True,
                )
            # _launch_airodump cleans an empty private temp directory on its
            # own; this is a second guarded cleanup for any setup residue.
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._cleanup_capture_temp_dir
                )
            except Exception:
                _LOG.debug(
                    "[monitoring] Could not clean capture temp directory after launch failure",
                    exc_info=True,
                )
            raise

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
        # A partial startup or an earlier shutdown error can clear _running
        # while still leaving a child process/task/temp capture directory to reap.
        if (
            not self._running
            and self._loop_task is None
            and self._process is None
            and self._capture_tmp_dir is None
        ):
            return

        _LOG.info("[monitoring] Stopping agent...")
        self._running = False

        loop_task = self._loop_task
        self._loop_task = None
        if loop_task is not None:
            if not loop_task.done():
                loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                _LOG.debug("[monitoring] Scan loop cancelled")
            except Exception as e:
                _LOG.error("[monitoring] Error stopping scan loop: %s", e)

        process = self._process
        if process is not None:
            try:
                _LOG.info("[monitoring] Terminating airodump process...")
                if process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        # It exited between the returncode check and terminate;
                        # still await it below so the child is reaped.
                        _LOG.debug("[monitoring] airodump exited during termination")
                    except Exception:
                        _LOG.warning(
                            "[monitoring] terminate() failed; still waiting for airodump",
                            exc_info=True,
                        )

                try:
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                except TimeoutError:
                    _LOG.info("[monitoring] Killing airodump process...")
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            _LOG.debug("[monitoring] airodump exited during kill")
                    await process.wait()

                _LOG.info("[monitoring] Airodump process stopped")
            except Exception as e:
                _LOG.error("[monitoring] Error stopping airodump: %s", e, exc_info=True)
            finally:
                # Retain the process handle if it could not be reaped; a later
                # stop() call can retry cleanup instead of silently losing it.
                if process.returncode is not None:
                    self._process = None

        try:
            await self._restore_managed_mode()
            _LOG.debug("[monitoring] Restored managed mode")
        except Exception as e:
            _LOG.error(f"[monitoring] Error restoring managed mode: {e}")

        # ARCHIVE PCAP BEFORE SAVING NETWORK HISTORY — run in executor so
        # synchronous Scapy parsing and file I/O don't stall the event loop
        await asyncio.get_running_loop().run_in_executor(None, self._archive_pcap_sync)
        # Remove private temporary files only after archiving. If archiving failed
        # and a PCAP remains, _cleanup_capture_temp_dir keeps it for recovery.
        await asyncio.get_running_loop().run_in_executor(
            None, self._cleanup_capture_temp_dir
        )

        try:
            if self.persistent_network:
                self.persistent_network.save()
                _LOG.debug("[monitoring] Saved network history")
        except Exception as e:
            _LOG.exception(f"[monitoring] Failed to save network history: {e}")

        if self.persistent_mood:
            try:
                if hasattr(self.persistent_mood, "update_mood"):
                    self.persistent_mood.update_mood("neutral")
                if hasattr(self.persistent_mood, "apply_reward"):
                    self.persistent_mood.apply_reward(-0.2, event="session_end")
                _LOG.debug("[monitoring] Updated mood for session end")
            except Exception as e:
                _LOG.debug(f"persistent_mood shutdown hooks failed: {e}")

        await self._emit_capture_summary("Monitoring stopped.")
        _LOG.info("[monitoring] Stopped cleanly.")

    # NEW: Public method to force PCAP archiving without full stop
    async def archive_current_pcap(self):
        """Force archiving of the current PCAP file without stopping monitoring."""
        _LOG.info("[monitoring] Force archiving current PCAP...")
        await asyncio.get_running_loop().run_in_executor(None, self._archive_pcap_sync)

    # ------------------------------------------------------------------
    async def _set_monitor_mode(self):
        # NetworkManager is optional. If it is installed, require it to release
        # only the configured capture interface before changing its mode.
        cmds = []
        if shutil.which("nmcli"):
            cmds.append(["nmcli", "device", "set", self.interface, "managed", "no"])
        else:
            _LOG.debug("[monitoring] nmcli not found; skipping unmanaged setting")

        # Use iw directly (also used by scripts/setup_wireless.sh) and check every
        # exit status. Silently ignoring a failed mode change can leave capture
        # running against a managed interface while the UI claims monitoring.
        cmds.extend([
            ["ip", "link", "set", "dev", self.interface, "down"],
            ["iw", "dev", self.interface, "set", "type", "monitor"],
            ["ip", "link", "set", "dev", self.interface, "up"],
        ])
        for cmd in cmds:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()
            except FileNotFoundError as exc:
                raise RuntimeError(f"Required command not found: {cmd[0]}") from exc

            if proc.returncode != 0:
                detail = stderr.decode(errors="replace").strip()
                raise RuntimeError(
                    f"Command {' '.join(cmd)!r} failed with exit code {proc.returncode}"
                    + (f": {detail}" if detail else "")
                )

        try:
            proc = await asyncio.create_subprocess_exec(
                "iw", "dev", self.interface, "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError as exc:
            raise RuntimeError("Required command not found: iw") from exc

        if proc.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"Could not verify monitor mode for {self.interface}"
                + (f": {detail}" if detail else "")
            )
        interface_info = stdout.decode(errors="replace").splitlines()
        if not any(line.strip() == "type monitor" for line in interface_info):
            raise RuntimeError(
                f"Interface {self.interface} did not enter monitor mode"
            )

    async def _restore_managed_mode(self):
        # Best-effort cleanup, still pinned to the capture adapter.
        cmds = [
            ["ip", "link", "set", "dev", self.interface, "down"],
            ["iw", "dev", self.interface, "set", "type", "managed"],
            ["ip", "link", "set", "dev", self.interface, "up"],
        ]
        if shutil.which("nmcli"):
            cmds.append(["nmcli", "device", "set", self.interface, "managed", "yes"])

        for cmd in cmds:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    _LOG.debug(
                        "[monitoring] Cleanup command %s failed: %s",
                        cmd[0],
                        stderr.decode(errors="replace").strip(),
                    )
            except FileNotFoundError:
                _LOG.debug("[monitoring] Command not found during cleanup: %s", cmd[0])
            except Exception as e:
                _LOG.debug("[monitoring] %s failed during cleanup: %s", cmd[0], e)

    # ------------------------------------------------------------------
    async def _launch_airodump(self):
        # Check if airodump-ng is installed
        if not shutil.which("airodump-ng"):
            raise RuntimeError(
                "airodump-ng not found. Install aircrack-ng: sudo pacman -S aircrack-ng"
            )

        # Don't lose access to a previous session if its PCAP archive failed.
        # Refuse to start a second session while an old capture remains private
        # and unarchived; the operator can retry archiving it first.
        if self._capture_tmp_dir is not None and self._capture_tmp_dir.exists():
            leftovers = [
                path
                for pattern in ("*.cap", "*.pcap", "*.pcapng")
                for path in self._capture_tmp_dir.glob(pattern)
            ]
            if leftovers:
                raise RuntimeError(
                    "Previous PCAP session is still unarchived in "
                    f"{self._capture_tmp_dir}; archive it before restarting"
                )
            self._cleanup_capture_temp_dir()

        # airodump writes sensitive capture data. Use a unique directory whose
        # permissions are private to the current user instead of predictable
        # filenames directly under shared /tmp.
        PCAP_STORAGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        # The fallback archive is used when PersistentNetwork isn't attached.
        # Enforce the same privacy boundary as the persistent archive.
        try:
            os.chmod(PCAP_STORAGE_DIR, 0o700)
        except OSError as exc:
            raise PermissionError(
                f"Could not secure PCAP storage directory {PCAP_STORAGE_DIR}"
            ) from exc
        _LOG.info("[monitoring] PCAP storage directory: %s", PCAP_STORAGE_DIR)

        capture_dir = Path(
            tempfile.mkdtemp(
                prefix=f"kaiagotchi_{os.getpid()}_",
                dir=tempfile.gettempdir(),
            )
        )
        try:
            # Track the directory before chmod/spawn so every failure path can
            # clean up an empty scratch directory safely.
            self._capture_tmp_dir = capture_dir
            os.chmod(capture_dir, 0o700)
            self._base_path = capture_dir / "capture"
            self._csv_path = Path(f"{self._base_path}-01.csv")
            self._session_pcap = Path(f"{self._base_path}-01.cap")

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

            _LOG.info("[monitoring] Launching airodump: %s", " ".join(args))
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception:
            # Avoid leaving empty temp folders behind if process launch fails.
            self._cleanup_capture_temp_dir()
            self._base_path = None
            self._csv_path = None
            self._session_pcap = None
            raise

        _LOG.info(
            "[monitoring] airodump started; CSV: %s, PCAP: %s",
            self._csv_path,
            self._session_pcap,
        )

    def _cleanup_capture_temp_dir(self) -> None:
        """Remove this session's private temp directory unless a PCAP remains."""
        capture_dir = self._capture_tmp_dir
        if capture_dir is None:
            return

        try:
            # Only clean a directory created by this code inside tempfile's
            # configured temp root; refuse to traverse unexpected paths/symlinks.
            temp_root = Path(tempfile.gettempdir()).resolve()
            if (
                capture_dir.is_symlink()
                or not capture_dir.name.startswith(f"kaiagotchi_{os.getpid()}_")
                or capture_dir.resolve(strict=True).parent != temp_root
            ):
                _LOG.error(
                    "[monitoring] Refusing to clean unexpected capture temp path: %s",
                    capture_dir,
                )
                return

            leftovers = [
                path
                for pattern in ("*.cap", "*.pcap", "*.pcapng")
                for path in capture_dir.glob(pattern)
            ]
            if leftovers:
                _LOG.warning(
                    "[monitoring] Keeping private capture directory because PCAPs remain unarchived: %s",
                    ", ".join(str(path) for path in leftovers),
                )
                return

            shutil.rmtree(capture_dir)
            self._capture_tmp_dir = None
            _LOG.debug("[monitoring] Removed temporary capture directory: %s", capture_dir)
        except FileNotFoundError:
            self._capture_tmp_dir = None
        except Exception:
            _LOG.exception(
                "[monitoring] Failed to clean temporary capture directory: %s",
                capture_dir,
            )

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
                    self.system_state.recent_captures = list(captures)
                    self.system_state.chatter_log = list(captures)

            if self.view:
                await self.view.async_update({
                    "recent_captures": list(captures),
                    "chatter_log": list(captures)
                })

        except Exception:
            _LOG.debug("[monitoring] Failed to emit capture summary", exc_info=True)

    # ------------------------------------------------------------------
    def _archive_pcap_sync(self):
        """Synchronous PCAP archive worker — run via run_in_executor to avoid blocking the event loop."""
        try:
            # Check both possible file extensions and use the session_pcap path
            possible_sources = [
                self._session_pcap,
                Path(f"{self._base_path}-01.cap"),
                Path(f"{self._base_path}-01.pcap")  # Some systems might create .pcap
            ]

            src = None
            for possible_src in possible_sources:
                if possible_src and possible_src.exists():
                    src = possible_src
                    _LOG.info(f"[monitoring] Found PCAP source: {src}")
                    break

            if not src or not src.exists():
                _LOG.warning(f"[monitoring] No .cap/.pcap file found to archive. Checked: {[str(p) for p in possible_sources if p]}")
                # Legacy fallback only applies to pre-private-directory sessions.
                # Never guess at a file in shared /tmp for a current session.
                fallback_files = []
                if self._capture_tmp_dir is None:
                    fallback_files = list(
                        Path("/tmp").glob(f"kaiagotchi_{os.getpid()}-*.cap")
                    )
                if fallback_files:
                    src = fallback_files[0]
                    _LOG.info("[monitoring] Using legacy fallback PCAP file: %s", src)
                else:
                    _LOG.error("[monitoring] No PCAP files found for archiving")
                    return

            src_size = src.stat().st_size
            _LOG.info(f"[monitoring] Found session PCAP: {src} ({src_size} bytes)")

            if self.persistent_network:
                try:
                    # Let PersistentNetwork handle copying and registering the file
                    copied_path = self.persistent_network.add_pcap_file(
                        str(src), bssid=None, src_name="airodump", analyze=True
                    )
                    if copied_path:
                        _LOG.info(f"[monitoring] PCAP successfully archived to: {copied_path}")
                    else:
                        _LOG.error("[monitoring] PersistentNetwork failed to archive PCAP.")
                        return  # Don't delete source if archive failed
                except Exception as e:
                    _LOG.error(f"[monitoring] persistent_network.add_pcap_file failed: {e}", exc_info=True)
                    return  # Don't delete source if archive failed
            else:
                # Fallback: copy manually to storage/pcaps if persistent_network is not available
                timestamp = datetime.now(TZ).strftime("%Y-%m-%dT%H-%M-%S")
                clean_filename = f"{timestamp}_airodump.pcap"
                clean_dest = PCAP_STORAGE_DIR / clean_filename

                try:
                    # Don't rely on _launch_airodump() having created the
                    # archive directory, and keep it private to this user.
                    PCAP_STORAGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
                    os.chmod(PCAP_STORAGE_DIR, 0o700)
                    # Create the destination as 0600 from the start so the
                    # capture is never readable by others, even briefly
                    # (copy2 would inherit the source's permissions).
                    fd = os.open(
                        clean_dest,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                    )
                    try:
                        with os.fdopen(fd, "wb") as dst, open(src, "rb") as srcf:
                            shutil.copyfileobj(srcf, dst)
                    except BaseException:
                        clean_dest.unlink(missing_ok=True)
                        raise
                except OSError as exc:
                    _LOG.error(
                        "Could not securely archive fallback PCAP to %s: %s; source kept",
                        clean_dest,
                        exc,
                    )
                    return
                if not clean_dest.exists():
                    _LOG.error("[monitoring] Manual PCAP copy did not produce a destination file; source kept")
                    return
                _LOG.info(f"[monitoring] PersistentNetwork not attached; manually copied PCAP to: {clean_dest}")

            # Only remove the temporary source file once the destination is confirmed to exist
            try:
                src.unlink()
                _LOG.info(f"[monitoring] Cleaned up temporary PCAP: {src}")
            except Exception as e:
                _LOG.debug(f"[monitoring] Could not remove temporary PCAP {src}: {e}")

        except Exception as e:
            _LOG.exception(f"[monitoring] Failed to archive PCAP: {e}")

    @staticmethod
    def _counter_value(value: Any) -> int | None:
        """Parse airodump's cumulative numeric counter; '-' and blanks are missing."""
        try:
            parsed = int(str(value).strip())
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None

    def _counter_delta(
        self,
        store: dict[str, dict[str, int]],
        identity: str,
        counter_name: str,
        raw_value: Any,
    ) -> int:
        """Return the newly observed count, handling missing values and counter resets."""
        current = self._counter_value(raw_value)
        if current is None:
            return 0

        counters = store.setdefault(identity.upper(), {})
        previous = counters.get(counter_name)
        counters[counter_name] = current
        # Airodump restarts/reset counters when its capture process or output
        # rolls over; in that case count from the new counter origin.
        if previous is None or current < previous:
            return current
        return current - previous

    def _persist_scan_counters(
        self, aps: list[dict[str, Any]], stations: list[dict[str, Any]]
    ) -> None:
        """Update persistent network state using per-scan counter deltas."""
        if self.persistent_network is None:
            return

        for ap in aps:
            bssid = str(ap.get("bssid") or "").strip()
            if not bssid:
                continue
            # airodump's "# IV" is its captured data/IV counter; "# beacons"
            # is separate. Do not treat cumulative beacons as packet totals.
            packet_delta = self._counter_delta(
                self._last_ap_counters, bssid, "iv", ap.get("iv")
            )
            beacon_delta = self._counter_delta(
                self._last_ap_counters, bssid, "beacons", ap.get("beacons")
            )
            self.persistent_network.update_bssid(
                bssid=bssid,
                essid=ap.get("essid", ""),
                packets=packet_delta,
                beacons=beacon_delta,
                channel=ap.get("channel", ""),
                encryption=ap.get("privacy", ""),
            )

        for station in stations:
            station_mac = str(station.get("station_mac") or "").strip()
            if not station_mac:
                continue
            packet_delta = self._counter_delta(
                self._last_station_counters, station_mac, "packets", station.get("packets")
            )
            self.persistent_network.update_station(
                sta_mac=station_mac,
                associated_bssid=station.get("bssid", ""),
                packets=packet_delta,
                essids=station.get("probed_essids", ""),
            )

    # ------------------------------------------------------------------
    async def _scan_loop(self):
        try:
            while self._running:
                await asyncio.sleep(self.refresh_interval)
                if not self._csv_path or not self._csv_path.exists():
                    _LOG.debug("[monitoring] CSV file not ready, waiting...")
                    continue

                aps, stations = self._parse_airodump_csv(self._csv_path)

                if len(aps) > self._max_ap_records:
                    aps = aps[: self._max_ap_records]
                if len(stations) > self._max_station_records:
                    stations = stations[: self._max_station_records]

                aps = sorted(aps, key=lambda a: self._parse_last_seen_for_sort(a.get("last_seen", "")), reverse=True)

                new_aps = [a for a in aps if a["bssid"] not in self._seen_bssids]
                new_stations = [s for s in stations if s["station_mac"] not in self._seen_stations]

                # Persist per-scan deltas, not airodump's cumulative totals.
                if self.persistent_network:
                    try:
                        self._persist_scan_counters(aps, stations)
                    except Exception as e:
                        _LOG.debug("Failed to update persistent network: %s", e, exc_info=True)

                    now = time.monotonic()
                    if aps or stations:
                        # Save newly discovered identities immediately and make
                        # periodic progress durable during long-running scans.
                        # Reports are throttled by PersistentNetwork.save().
                        if (
                            new_aps
                            or new_stations
                            or now - self._last_persistence_save >= 30.0
                        ):
                            try:
                                await asyncio.to_thread(
                                    self.persistent_network.save, force_reports=False
                                )
                                self._last_persistence_save = time.monotonic()
                            except Exception:
                                _LOG.warning("Failed to persist scan history", exc_info=True)

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
            _LOG.debug("[monitoring] Scan loop cancelled normally")
            raise
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
    async def _update_state(self, aps: list[dict[str, Any]], stations: list[dict[str, Any]]):
        ap_count = len(aps)
        self._max_aps_seen = max(self._max_aps_seen, ap_count)
        uptime = time.strftime("%H:%M:%S", time.gmtime(time.time() - self._start_time))

        # InterfaceActionManager publishes its successful channel hop to the
        # shared View. Copy that known value into the typed network state rather
        # than reporting a fabricated channel when no channel is known.
        current_channel: int | None = None
        view_state = getattr(self.view, "state", None)
        if isinstance(view_state, dict):
            try:
                candidate = int(view_state.get("channel"))
                if 1 <= candidate <= 165:
                    current_channel = candidate
            except (TypeError, ValueError):
                pass

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
                if current_channel is not None:
                    network = self.system_state.setdefault("network", {})
                    if isinstance(network, dict):
                        network["current_channel"] = current_channel
            else:
                for k, v in new_state.items():
                    setattr(self.system_state, k, v)
                network = getattr(self.system_state, "network", None)
                if current_channel is not None and network is not None:
                    network.current_channel = current_channel

        if self.view:
            try:
                await self.view.async_update({
                    "aps": ap_count,
                    "aps_max_seen": self._max_aps_seen,
                    "recent_captures": recent_captures,
                    # chatter_log is intentionally omitted: View.get_snapshot_dict()
                    # builds it from _chatter_lines, so setting it here is a no-op.
                    "aps_list": aps,
                    "stations_list": stations,
                    "mode": "MONITORING",
                    "uptime": uptime,
                })
            except Exception:
                _LOG.debug("view.async_update failed in monitoring _update_state", exc_info=True)

        if self.view and hasattr(self.view, "display"):
            disp = self.view.display
            if hasattr(disp, "update_table"):
                try:
                    disp.update_table(aps, stations)
                except Exception:
                    _LOG.debug("display.update_table failed", exc_info=True)

    # ------------------------------------------------------------------
    def get_network_summary(self) -> dict[str, Any]:
        """Get current network summary for debugging and UI."""
        return {
            "aps_count": len(self._seen_bssids),
            "stations_count": len(self._seen_stations),
            "max_aps_seen": self._max_aps_seen,
            "session_duration": time.time() - self._start_time,
            "interface": self.interface,
        }
