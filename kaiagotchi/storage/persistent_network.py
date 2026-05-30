from __future__ import annotations
import logging
import os
import shutil
import stat
import re
from typing import Any, Dict, Optional, List
from datetime import datetime
from pathlib import Path

from .file_io import atomically_save_data, load_data
from .utils_time import now_cst_iso, TZ

try:
    from kaiagotchi.network.pcap_parser import parse_pcap_comprehensive  # type: ignore
except Exception:
    parse_pcap_comprehensive = None

# Keep original for backward compatibility
try:
    from kaiagotchi.network.pcap_parser import parse_pcap  # type: ignore
except Exception:
    parse_pcap = None

LOGGER = logging.getLogger(__name__)

DEFAULT_FILENAME = "network_history.json"
PCAP_DIRNAME = "pcaps"
MAX_PCAP_STORAGE_BYTES = 100 * 1024 * 1024 * 1024  # 100 GB cap


def _earlier_ts(ts1: str, ts2: str) -> str:
    """Return the earlier of two ISO timestamp strings (best-effort compare)."""
    if not ts1:
        return ts2
    if not ts2:
        return ts1
    try:
        t1 = datetime.fromisoformat(ts1.replace("Z", ""))
        t2 = datetime.fromisoformat(ts2.replace("Z", ""))
        return ts1 if t1 <= t2 else ts2
    except Exception:
        # Fallback to lexicographic compare if parsing fails
        return min(ts1, ts2)


class PersistentNetwork:
    """
    Rolling scoreboard for BSSIDs, Stations, and PCAPs.
      - bssids: per-BSSID info (essid history, first_seen, last_seen, stats)
      - stations: per-station MAC info
      - pcaps: metadata + optional parsed analysis from pcap_parser
    """

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir:
            self.storage_dir = os.path.expanduser(storage_dir)
        else:
            self.storage_dir = os.path.dirname(__file__)

        self.filepath = os.path.join(self.storage_dir, DEFAULT_FILENAME)
        self.pcaps_dir = os.path.join(self.storage_dir, PCAP_DIRNAME)
        
        # Ensure directories exist with proper permissions
        self._ensure_directory_permissions()
        
        self._data: Dict[str, Any] = {"bssids": {}, "stations": {}, "pcaps": {}}
        self.load()
        
        # Sync pcap records with filesystem on initialization
        self._sync_pcaps_with_filesystem()
        
        # Generate initial handshake and SSID summary reports
        self.generate_reports()

    def _ensure_directory_permissions(self):
        """Ensure storage directories exist with proper permissions."""
        try:
            # Create directories if they don't exist
            os.makedirs(self.storage_dir, exist_ok=True)
            os.makedirs(self.pcaps_dir, exist_ok=True)
            
            # Set proper permissions (read/write for user, read for group/others)
            os.chmod(self.storage_dir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
            os.chmod(self.pcaps_dir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
            
            LOGGER.debug(f"Ensured directory permissions for {self.storage_dir}")
        except Exception as e:
            LOGGER.error(f"Failed to set directory permissions: {e}")

    def _ensure_file_permissions(self, filepath: str):
        """Ensure file has proper read/write permissions."""
        try:
            if os.path.exists(filepath):
                os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                LOGGER.debug(f"Set permissions for {filepath}")
        except Exception as e:
            LOGGER.error(f"Failed to set file permissions for {filepath}: {e}")

    def load(self) -> None:
        try:
            raw = load_data(self.filepath, default={})
            # Ensure file permissions after loading
            self._ensure_file_permissions(self.filepath)
        except Exception:
            LOGGER.exception("Failed to load network history file; starting fresh")
            raw = {}

        if not isinstance(raw, dict):
            LOGGER.warning("network_history file invalid or corrupted; creating new.")
            raw = {}

        self._data = {
            "bssids": raw.get("bssids", {}),
            "stations": raw.get("stations", {}),
            "pcaps": raw.get("pcaps", {}),
        }

    def save(self) -> bool:
        try:
            payload = dict(self._data)
            payload["_last_saved"] = now_cst_iso()
            success = atomically_save_data(self.filepath, payload, fmt="json")
            if success:
                # Ensure proper permissions after saving
                self._ensure_file_permissions(self.filepath)
                # Generate handshake and SSID summary reports
                self.generate_reports()
            return success
        except Exception:
            LOGGER.exception("Failed to save network history")
            return False

    # -------------------------
    # Enhanced PCAP filesystem sync with better BSSID extraction
    # -------------------------
    def _sync_pcaps_with_filesystem(self) -> None:
        """Sync pcap records with actual files in the pcaps directory."""
        try:
            # Get all pcap files in the directory
            pcap_files = list(Path(self.pcaps_dir).glob("*.pcap"))
            existing_filenames = {f.name for f in pcap_files}
            
            # Remove records for files that don't exist
            for filename in list(self._data.get("pcaps", {}).keys()):
                if filename not in existing_filenames:
                    LOGGER.info(f"Removing pcap record for deleted file: {filename}")
                    del self._data["pcaps"][filename]
            
            # Add records for files that exist but aren't in our records
            for pcap_file in pcap_files:
                if pcap_file.name not in self._data.get("pcaps", {}):
                    LOGGER.info(f"Adding pcap record for existing file: {pcap_file.name}")
                    stat = pcap_file.stat()
                    # ENHANCED: Better BSSID extraction that handles various filename formats
                    bssid = self._extract_bssid_from_filename(pcap_file.name)
                    
                    record: Dict[str, Any] = {
                        "bssid": bssid,
                        "created": datetime.fromtimestamp(stat.st_mtime, tz=TZ).isoformat(),
                        "size": stat.st_size,
                        "path": str(pcap_file),
                    }
                    
                    # Try to analyze the pcap to extract BSSID and other info
                    if parse_pcap_comprehensive is not None:
                        try:
                            self._analyze_pcap_into_record(pcap_file, record)
                            # Update BSSID from analysis if found
                            if record.get("analysis"):
                                for capture in record["analysis"]:
                                    if capture.get("bssid"):
                                        record["bssid"] = capture["bssid"].upper()
                                        break
                        except Exception:
                            LOGGER.debug(f"Could not analyze existing pcap {pcap_file.name}")
                    
                    self._data.setdefault("pcaps", {})[pcap_file.name] = record
            
            # Save the synced state
            if pcap_files:
                self.save()
                LOGGER.info(f"Synced {len(pcap_files)} pcap files with filesystem")
                
        except Exception:
            LOGGER.exception("Failed to sync pcaps with filesystem")

    def _extract_bssid_from_filename(self, filename: str) -> str:
        """Extract BSSID from filename using multiple pattern matching strategies."""
        # Remove file extension
        stem = Path(filename).stem
        
        # Strategy 1: Look for MAC address patterns (XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX)
        mac_patterns = [
            r'([0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2})',
            r'([0-9A-Fa-f]{2}[-][0-9A-Fa-f]{2}[-][0-9A-Fa-f]{2}[-][0-9A-Fa-f]{2}[-][0-9A-Fa-f]{2}[-][0-9A-Fa-f]{2})'
        ]
        
        for pattern in mac_patterns:
            match = re.search(pattern, stem)
            if match:
                # Convert to standard MAC format (uppercase with colons)
                mac = match.group(1).replace('-', ':').upper()
                return mac
        
        # Strategy 2: Split by common separators and look for MAC-like segments
        for separator in ['_', '-', '.']:
            parts = stem.split(separator)
            for part in parts:
                if len(part) == 17 and (part.count(':') == 5 or part.count('-') == 5):
                    return part.replace('-', ':').upper()
        
        return "UNKNOWN"

    # -------------------------
    # BSSID helpers
    # -------------------------
    def get_first_seen(self, mac: str) -> Optional[str]:
        if not mac:
            return None
        mac = mac.upper()
        entry = self._data["bssids"].get(mac) or self._data["stations"].get(mac)
        return entry.get("first_seen") if entry else None

    def update_bssid(
        self,
        bssid: str,
        essid: Optional[str] = None,
        packets: int = 0,
        beacons: int = 0,
        seen_iso: Optional[str] = None,
        channel: Optional[str] = None,
        encryption: Optional[str] = None,
    ) -> None:
        """Merge or create entry for a BSSID and update stats while preserving earliest first_seen."""
        try:
            if not bssid:
                return
            bssid = bssid.upper()
            now = seen_iso or now_cst_iso()

            # Create or get the BSSID entry with all needed fields
            store = self._data["bssids"].setdefault(
                bssid,
                {
                    "bssid": bssid,
                    "essid": essid or "",
                    "essid_history": [],
                    "first_seen": now,
                    "last_seen": now,
                    "packets": 0,
                    "beacons": 0,
                    "channel": channel or "",
                    "encryption": encryption or "",
                },
            )

            # Preserve earliest first_seen
            existing_first = store.get("first_seen")
            store["first_seen"] = _earlier_ts(existing_first, now)
            store["last_seen"] = now

            # Update current ESSID if provided and different
            if essid:
                essid = essid.strip()
                current_essid = store.get("essid", "")
                if essid and essid != current_essid:
                    store["essid"] = essid
                    # Add to history if not already present and not empty
                    if essid and essid not in store["essid_history"]:
                        store["essid_history"].append(essid)

            # Update channel and encryption if provided
            if channel:
                store["channel"] = channel
            if encryption:
                store["encryption"] = encryption

            # Update counters
            for key, val in {"packets": packets, "beacons": beacons}.items():
                try:
                    store[key] = int(store.get(key, 0)) + int(val)
                except Exception:
                    LOGGER.exception("Error incrementing %s for %s", key, bssid)
                    
            LOGGER.debug(f"Updated BSSID {bssid}: first_seen={store['first_seen']}, last_seen={store['last_seen']}")
        except Exception:
            LOGGER.exception("update_bssid failed for %s", bssid)

    # -------------------------
    # Station helpers
    # -------------------------
    def update_station(
        self,
        sta_mac: str,
        associated_bssid: Optional[str] = None,
        packets: int = 0,
        seen_iso: Optional[str] = None,
        essids: Optional[str] = None,
    ) -> None:
        """Merge or create entry for a station MAC and update stats while preserving earliest first_seen."""
        try:
            if not sta_mac:
                return
            sta_mac = sta_mac.upper()
            now = seen_iso or now_cst_iso()

            store = self._data["stations"].setdefault(
                sta_mac,
                {
                    "station_mac": sta_mac,
                    "associated_bssid": associated_bssid.upper()
                    if associated_bssid
                    else None,
                    "first_seen": now,
                    "last_seen": now,
                    "packets": 0,
                    "essids": essids or "",
                },
            )

            existing_first = store.get("first_seen")
            store["first_seen"] = _earlier_ts(existing_first, now)
            store["last_seen"] = now

            if associated_bssid:
                store["associated_bssid"] = associated_bssid.upper()

            if essids is not None:
                store["essids"] = essids

            try:
                store["packets"] = int(store.get("packets", 0)) + int(packets)
            except Exception:
                LOGGER.exception("Error incrementing station packets for %s", sta_mac)
        except Exception:
            LOGGER.exception("update_station failed for %s", sta_mac)

    # -------------------------
    # Methods for terminal display compatibility
    # -------------------------
    def get_bssid_history(self, bssid: str) -> Optional[Dict[str, Any]]:
        """Get historical data for a BSSID in terminal display format."""
        if not bssid:
            return None
        bssid = bssid.upper()
        entry = self._data["bssids"].get(bssid)
        if not entry:
            return None
            
        # Convert to terminal display format
        return {
            "bssid": entry.get("bssid", bssid),
            "essid": entry.get("essid", ""),
            "channel": entry.get("channel", ""),
            "encryption": entry.get("encryption", ""),
            "first_seen": entry.get("first_seen", ""),
            "last_seen": entry.get("last_seen", ""),
            "beacons": entry.get("beacons", 0),
            "packets": entry.get("packets", 0)
        }

    def get_all_bssids(self) -> Dict[str, Any]:
        """Get all BSSID history in terminal display format."""
        result = {}
        for bssid, entry in self._data["bssids"].items():
            result[bssid] = {
                "bssid": entry.get("bssid", bssid),
                "essid": entry.get("essid", ""),
                "channel": entry.get("channel", ""),
                "encryption": entry.get("encryption", ""),
                "first_seen": entry.get("first_seen", ""),
                "last_seen": entry.get("last_seen", ""),
                "beacons": entry.get("beacons", 0),
                "packets": entry.get("packets", 0)
            }
        return result

    def get_station_history(self, station_mac: str) -> Optional[Dict[str, Any]]:
        """Get historical data for a station in terminal display format."""
        if not station_mac:
            return None
        station_mac = station_mac.upper()
        entry = self._data["stations"].get(station_mac)
        if not entry:
            return None
            
        return {
            "station_mac": entry.get("station_mac", station_mac),
            "bssid": entry.get("associated_bssid", ""),
            "essids": entry.get("essids", ""),
            "first_seen": entry.get("first_seen", ""),
            "last_seen": entry.get("last_seen", ""),
            "packets": entry.get("packets", 0)
        }

    def get_all_stations(self) -> Dict[str, Any]:
        """Get all station history in terminal display format."""
        result = {}
        for station_mac, entry in self._data["stations"].items():
            result[station_mac] = {
                "station_mac": entry.get("station_mac", station_mac),
                "bssid": entry.get("associated_bssid", ""),
                "essids": entry.get("essids", ""),
                "first_seen": entry.get("first_seen", ""),
                "last_seen": entry.get("last_seen", ""),
                "packets": entry.get("packets", 0)
            }
        return result

    # -------------------------
    # Batch update methods for monitoring agent
    # -------------------------
    def update_from_scan_results(self, aps: List[Dict[str, Any]], stations: List[Dict[str, Any]]) -> None:
        """Update persistence from a full scan result set."""
        current_time = now_cst_iso()
        
        for ap in aps:
            self.update_bssid(
                bssid=ap.get("bssid", ""),
                essid=ap.get("essid", ""),
                packets=ap.get("packets", 0),
                beacons=ap.get("beacons", 0),
                seen_iso=current_time,
                channel=ap.get("channel", ""),
                encryption=ap.get("privacy", "")
            )
            
        for station in stations:
            self.update_station(
                sta_mac=station.get("station_mac", ""),
                associated_bssid=station.get("bssid", ""),
                packets=station.get("packets", 0),
                seen_iso=current_time,
                essids=station.get("essids", "")
            )
            
        self.save()
        LOGGER.debug(f"Updated persistence with {len(aps)} APs and {len(stations)} stations")

    # -------------------------
    # Enhanced PCAP analysis to extract ALL networks and devices
    # -------------------------
    def _analyze_pcap_into_record(self, dst_path: Path, record: Dict[str, Any]) -> None:
        """Enhanced analysis that extracts ALL BSSIDs and stations from PCAP, not just handshakes."""
        if parse_pcap_comprehensive is None:
            LOGGER.debug("pcap_parser not available; skipping analysis for %s", dst_path)
            return

        try:
            # Use the comprehensive parser to extract ALL network data
            network_data = parse_pcap_comprehensive(str(dst_path))
            
            if not network_data.bssids and not network_data.stations:
                LOGGER.debug(f"No network data found in {dst_path}")
                return

            analysis = []
            pmkid_count = 0
            handshake_count = 0
            bssids_updated = set()
            stations_updated = set()
            
            # Use the pcap file's modification time as the seen time
            pcap_time = datetime.fromtimestamp(dst_path.stat().st_mtime, tz=TZ).isoformat()
            
            # Process ALL BSSIDs found in the PCAP
            for bssid, bssid_info in network_data.bssids.items():
                self.update_bssid(
                    bssid=bssid,
                    essid=bssid_info.get('essid'),
                    packets=bssid_info.get('packets', 0),
                    beacons=bssid_info.get('beacons', 0),
                    seen_iso=pcap_time,
                    channel=bssid_info.get('channel'),
                    encryption=bssid_info.get('encryption')
                )
                bssids_updated.add(bssid.upper())
            
            # Process ALL stations found in the PCAP
            for station_mac, station_info in network_data.stations.items():
                self.update_station(
                    sta_mac=station_mac,
                    associated_bssid=station_info.get('associated_bssid'),
                    packets=station_info.get('packets', 0),
                    seen_iso=pcap_time
                )
                stations_updated.add(station_mac.upper())
            
            # Process handshakes for the analysis record
            for capture in network_data.handshakes:
                entry = {
                    "type": capture.type,
                    "bssid": capture.bssid,
                    "ssid": capture.ssid,
                    "client_mac": capture.client_mac,
                    "handshake_complete": bool(capture.handshake_complete),
                    "pmkid": capture.pmkid,
                }
                analysis.append(entry)
                
                if capture.pmkid:
                    pmkid_count += 1
                if capture.handshake_complete:
                    handshake_count += 1

            record["analysis"] = analysis
            
            # Save after updating ALL BSSIDs and stations
            self.save()
            
            LOGGER.info(
                "[pcap] Comprehensive analysis of %s → %d BSSIDs, %d stations, %d handshakes (%d complete, %d PMKID)",
                os.path.basename(str(dst_path)),
                len(bssids_updated),
                len(stations_updated),
                len(analysis),
                handshake_count,
                pmkid_count
            )
        except Exception:
            LOGGER.exception("Error analyzing PCAP %s", dst_path)

    def _make_pcap_filename(self, base_name: str, bssid: Optional[str] = None) -> str:
        """Generate a proper PCAP filename without asterisks."""
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        
        if bssid and bssid != "UNKNOWN":
            # Clean BSSID for filename (replace colons with dashes)
            clean_bssid = bssid.replace(':', '-').upper()
            return f"{timestamp}_{clean_bssid}_airodump.pcap"
        else:
            return f"{timestamp}_airodump.pcap"

    def add_pcap_file(
        self,
        src_path: str,
        bssid: Optional[str] = None,
        src_name: Optional[str] = None,
        analyze: bool = True,
    ) -> Optional[str]:
        """Add PCAP file by copying from source - use add_pcap_record for existing files."""
        try:
            src = Path(src_path)
            if not src.exists():
                LOGGER.error("PCAP source not found: %s", src)
                return None

            filename = self._make_pcap_filename(src_name or src.stem, bssid)
            dst = Path(self.pcaps_dir) / filename
            
            # Check if file already exists to avoid duplicates
            if dst.exists():
                LOGGER.warning(f"PCAP file already exists: {dst}, skipping copy")
                return str(dst)
                
            shutil.copy2(src, dst)

            stat = dst.stat()
            record: Dict[str, Any] = {
                "bssid": (bssid or "UNKNOWN").upper(),
                "created": now_cst_iso(),
                "size": stat.st_size,
                "path": str(dst),
            }

            if analyze:
                self._analyze_pcap_into_record(dst, record)

            self._data.setdefault("pcaps", {})[filename] = record
            self.enforce_storage_limit()
            self.save()
            LOGGER.info("Archived PCAP %s for BSSID %s", filename, bssid)
            return str(dst)
        except Exception:
            LOGGER.exception("Failed to add PCAP file")
            return None

    def add_pcap_record(self, path: Path, bssid: str, size: int, timestamp: str, analyze: bool = True) -> None:
        """Register existing PCAP file without copying - for files already in storage."""
        try:
            # Use absolute path to ensure consistency
            abs_path = path.absolute()
            filename = os.path.basename(str(abs_path))
            
            # Check if record already exists to avoid duplicates
            if filename in self._data.get("pcaps", {}):
                LOGGER.warning(f"PCAP record already exists for {filename}, updating instead")
                
            record: Dict[str, Any] = {
                "bssid": bssid.upper(),
                "created": timestamp,
                "size": size,
                "path": str(abs_path),
            }

            if analyze and parse_pcap_comprehensive is not None and abs_path.exists():
                self._analyze_pcap_into_record(abs_path, record)

            self._data.setdefault("pcaps", {})[filename] = record
            self.enforce_storage_limit()
            self.save()
            LOGGER.info("Registered PCAP record for %s (%s bytes)", bssid, size)
        except Exception:
            LOGGER.exception("Failed to add PCAP record (metadata only)")

    # -------------------------
    # NEW: Force re-analysis of all pcaps to ingest BSSIDs and stations
    # -------------------------
    def reanalyze_all_pcaps(self) -> None:
        """Re-analyze all pcap files to extract and update BSSID and station information."""
        try:
            LOGGER.info("Re-analyzing all pcap files to extract comprehensive BSSID and station data...")
            for filename, record in list(self._data.get("pcaps", {}).items()):
                pcap_path = Path(record.get("path", ""))
                if pcap_path.exists():
                    LOGGER.info(f"Re-analyzing pcap: {filename}")
                    self._analyze_pcap_into_record(pcap_path, record)
            self.save()
            LOGGER.info("Completed re-analysis of all pcap files")
        except Exception:
            LOGGER.exception("Failed to re-analyze pcaps")

    # -------------------------
    # Generate Reconnaissance & Handshake summary reports
    # -------------------------
    def generate_reports(self) -> None:
        """Generate handshakes_summary.md and handshakes_summary.json in storage_dir."""
        try:
            # 1. Gather all unique SSIDs ever seen
            unique_ssids: Dict[str, List[Dict[str, Any]]] = {}
            for bssid, entry in self._data.get("bssids", {}).items():
                ssid = entry.get("essid", "") or "Hidden or Unknown"
                if ssid not in unique_ssids:
                    unique_ssids[ssid] = []
                unique_ssids[ssid].append(entry)

            # Sort SSIDs alphabetically
            sorted_ssids = sorted(unique_ssids.keys())

            # 2. Gather all handshakes and PMKIDs
            handshakes_list = []
            for filename, record in self._data.get("pcaps", {}).items():
                analysis = record.get("analysis", []) or []
                created = record.get("created", "")
                for capture in analysis:
                    bssid = (capture.get("bssid") or "").upper()
                    ssid = capture.get("ssid") or ""
                    client_mac = (capture.get("client_mac") or "").upper()
                    pmkid = capture.get("pmkid") or ""
                    handshake_complete = capture.get("handshake_complete", False)
                    cap_type = capture.get("type") or "WPA Handshake"

                    # Normalize MACs
                    bssid_clean = bssid.replace(":", "").lower()
                    client_clean = client_mac.replace(":", "").lower() if client_mac else "ffffffffffff"
                    ssid_hex = ssid.encode("utf-8", errors="ignore").hex()

                    hashcat_22000 = ""
                    hashcat_16800 = ""
                    if pmkid:
                        hashcat_22000 = f"WPA*01*{pmkid}*{bssid_clean}*{client_clean}*{ssid_hex}"
                        hashcat_16800 = f"{pmkid}*{bssid_clean}*{client_clean}*{ssid_hex}"

                    handshakes_list.append({
                        "pcap_file": filename,
                        "timestamp": created,
                        "type": cap_type,
                        "ssid": ssid,
                        "bssid": bssid,
                        "client_mac": client_mac or "Unknown",
                        "handshake_complete": handshake_complete,
                        "pmkid": pmkid or None,
                        "hashcat_22000": hashcat_22000,
                        "hashcat_16800": hashcat_16800
                    })

            # Sort handshakes by timestamp descending
            handshakes_list.sort(key=lambda x: x["timestamp"], reverse=True)

            # JSON Report payload
            json_report = {
                "summary": {
                    "total_unique_ssids_seen": len(unique_ssids),
                    "total_handshakes_captured": len(handshakes_list),
                    "total_complete_handshakes": sum(1 for h in handshakes_list if h["handshake_complete"]),
                    "total_pmkids": sum(1 for h in handshakes_list if h["pmkid"]),
                    "generated_at": now_cst_iso()
                },
                "ssids": {
                    ssid: [
                        {
                            "bssid": entry.get("bssid"),
                            "channel": entry.get("channel"),
                            "encryption": entry.get("encryption"),
                            "first_seen": entry.get("first_seen"),
                            "last_seen": entry.get("last_seen"),
                            "packets": entry.get("packets"),
                            "beacons": entry.get("beacons")
                        }
                        for entry in entries
                    ]
                    for ssid, entries in unique_ssids.items()
                },
                "handshakes": handshakes_list
            }

            # Save JSON report
            json_path = os.path.join(self.storage_dir, "handshakes_summary.json")
            atomically_save_data(json_path, json_report, fmt="json")
            self._ensure_file_permissions(json_path)            # Save MD report
            md_path = os.path.join(self.storage_dir, "handshakes_summary.md")
            
            md_lines = []
            md_lines.append("# 📶 Kaiagotchi Wi-Fi Reconnaissance & Security Audit Summary")
            md_lines.append(f"Generated at: `{json_report['summary']['generated_at']}`\n")
            
            # --- Scoreboard ---
            md_lines.append("## 📊 Scoreboard")
            md_lines.append(f"- **Total Unique SSIDs Seen:** {json_report['summary']['total_unique_ssids_seen']}")
            md_lines.append(f"- **Total Handshakes/PMKIDs Captured:** {json_report['summary']['total_handshakes_captured']}")
            md_lines.append(f"- **Total Complete Handshakes:** {json_report['summary']['total_complete_handshakes']}")
            md_lines.append(f"- **Total PMKIDs Captured:** {json_report['summary']['total_pmkids']}\n")

            # --- ASCII Channel Load Distribution ---
            md_lines.append("## 📈 Wi-Fi Channel Load & Density Distribution")
            md_lines.append("Visual distribution of active Access Points (APs) across Wi-Fi frequency bands:\n")
            
            # Group channels
            chan_map: Dict[int, int] = {}
            for entry in self._data.get("bssids", {}).values():
                ch_val = entry.get("channel")
                if ch_val:
                    try:
                        c_int = int(ch_val)
                        chan_map[c_int] = chan_map.get(c_int, 0) + 1
                    except ValueError:
                        pass

            # Divide channels into 2.4GHz and 5GHz/6GHz lists
            chans_24 = sorted([c for c in chan_map.keys() if c <= 14])
            chans_5 = sorted([c for c in chan_map.keys() if c > 14])
            
            max_ap_count = max(chan_map.values()) if chan_map else 0
            bar_width = 30

            def make_ascii_bar(count: int, max_val: int) -> str:
                if max_val == 0:
                    return "░" * bar_width
                filled_len = int(round((count / max_val) * bar_width))
                filled_len = max(0, min(bar_width, filled_len))
                unfilled_len = bar_width - filled_len
                return "█" * filled_len + "░" * unfilled_len

            md_lines.append("### 2.4 GHz Band")
            if not chans_24:
                md_lines.append("No active 2.4 GHz channels detected.\n")
            else:
                md_lines.append("```")
                for ch in chans_24:
                    count = chan_map[ch]
                    bar_str = make_ascii_bar(count, max_ap_count)
                    md_lines.append(f"Channel {ch:02d} : {bar_str} [{count:2d} APs]")
                md_lines.append("```\n")

            md_lines.append("### 5 GHz / 6 GHz Bands")
            if not chans_5:
                md_lines.append("No active 5 GHz / 6 GHz channels detected.\n")
            else:
                md_lines.append("```")
                for ch in chans_5:
                    count = chan_map[ch]
                    bar_str = make_ascii_bar(count, max_ap_count)
                    md_lines.append(f"Channel {ch:03d} : {bar_str} [{count:2d} APs]")
                md_lines.append("```\n")

            # --- Captured Handshakes & Crackable Hashes ---
            md_lines.append("## 🔑 Captured Handshakes & Crackable Hashes")
            if not handshakes_list:
                md_lines.append("No handshakes or PMKIDs have been captured yet.\n")
            else:
                md_lines.append("| SSID | BSSID | Client MAC | Type | Complete | Source PCAP | Hashcat Mode 22000 / 16800 |")
                md_lines.append("| --- | --- | --- | --- | --- | --- | --- |")
                for h in handshakes_list:
                    h_link = "`WPA*02` (MIC needed)"
                    if h["pmkid"]:
                        h_link = f"**Mode 22000:**<br>`{h['hashcat_22000']}`<br><br>**Mode 16800:**<br>`{h['hashcat_16800']}`"
                    
                    complete_str = "✅ Yes" if h["handshake_complete"] else "❌ No"
                    ssid_display = h["ssid"] if h["ssid"] != "Hidden or Unknown" else "*Hidden/Unknown*"
                    md_lines.append(
                        f"| {ssid_display} | `{h['bssid']}` | `{h['client_mac']}` | {h['type']} | {complete_str} | `{h['pcap_file']}` | {h_link} |"
                    )
                md_lines.append("\n")

            # --- Open & Vulnerable Networks Audit ---
            md_lines.append("## ⚠️ Wi-Fi Security Vulnerability Audit")
            md_lines.append("Identified Open or insecure legacy networks in the wireless vicinity:\n")
            
            vulnerable_networks = []
            for bssid, entry in self._data.get("bssids", {}).items():
                enc = (entry.get("encryption") or "").upper()
                if "OPEN" in enc or "WEP" in enc or "WPA" in enc or not enc:
                    vulnerable_networks.append(entry)

            if not vulnerable_networks:
                md_lines.append("✨ **Excellent! No unencrypted (Open) or legacy WEP/WPA1 networks detected in this area.**\n")
            else:
                md_lines.append("| SSID | BSSID | Channel | Encryption Profile | Security Status |")
                md_lines.append("| --- | --- | --- | --- | --- |")
                for entry in vulnerable_networks:
                    ssid_display = entry.get("essid", "") or "*Hidden/Unknown*"
                    enc_profile = entry.get("encryption") or "Open / Unencrypted"
                    enc_upper = enc_profile.upper()
                    
                    if "WEP" in enc_upper:
                        status = "🛑 HIGHLY INSECURE"
                    elif "OPEN" in enc_upper or not enc_upper or enc_upper == "OPEN / UNENCRYPTED":
                        status = "⚠️ UNENCRYPTED / OPEN"
                    elif "WPA2" in enc_upper and "WPA" in enc_upper:
                        # WPA2 Mixed Mode with legacy TKIP compatibility
                        status = "ℹ️ WPA2/WPA MIXED MODE"
                    elif "WPA2" not in enc_upper and "WPA" in enc_upper:
                        # True WPA1 only
                        status = "⚠️ LEGACY WPA1"
                    else:
                        status = f"ℹ️ {enc_profile}"
                        
                    md_lines.append(
                        f"| {ssid_display} | `{entry.get('bssid')}` | {entry.get('channel') or '-'} | `{enc_profile}` | **{status}** |"
                    )
                md_lines.append("\n")

            # --- Hidden SSID & Client Association Tracker ---
            md_lines.append("## 🕵️ Hidden & Masked Access Points")
            md_lines.append("Access points broadcasting in stealth mode (Hidden SSIDs):\n")
            
            hidden_aps = []
            for bssid, entry in self._data.get("bssids", {}).items():
                ssid = entry.get("essid", "")
                if ssid == "Hidden or Unknown" or not ssid or ssid.strip() == "":
                    hidden_aps.append(entry)

            if not hidden_aps:
                md_lines.append("No active hidden networks detected in this area.\n")
            else:
                md_lines.append("| BSSID | Channel | Packets | Beacons | Last Seen | Security |")
                md_lines.append("| --- | --- | --- | --- | --- | --- |")
                for entry in hidden_aps:
                    md_lines.append(
                        f"| `{entry.get('bssid')}` | {entry.get('channel') or '-'} | {entry.get('packets', 0)} | {entry.get('beacons', 0)} | {entry.get('last_seen')[:19]} | {entry.get('encryption') or '-'} |"
                    )
                md_lines.append("\n")

            # --- Multi-BSSID Virtualization & Spoofing Diagnostics ---
            md_lines.append("## 🧬 Multi-BSSID Virtualization & Spoofing Diagnostics")
            md_lines.append("Detects potential physical network mapping, multi-SSID enterprise virtualization, or BSSID cloning/spoofing anomalies:\n")
            
            multi_bssid_groups: Dict[str, List[Dict[str, Any]]] = {}
            for ssid, entries in unique_ssids.items():
                if ssid != "Hidden or Unknown" and len(entries) > 1:
                    multi_bssid_groups[ssid] = entries

            if not multi_bssid_groups:
                md_lines.append("No duplicate SSIDs mapping to multiple distinct MACs found.\n")
            else:
                md_lines.append("| SSID Name | BSSIDs Detected | Associated Channels | Deployment Profile |")
                md_lines.append("| --- | --- | --- | --- |")
                for ssid, entries in multi_bssid_groups.items():
                    bssid_list = ", ".join([f"`{e.get('bssid')}`" for e in entries])
                    channel_list = ", ".join(list(set([str(e.get('channel')) for e in entries if e.get('channel')])))
                    profile = "🏢 Enterprise Virtualization / Roaming" if len(entries) >= 3 else "👥 Dual-Band / Multi-AP Network"
                    md_lines.append(
                        f"| **{ssid}** | {bssid_list} | {channel_list} | {profile} |"
                    )
                md_lines.append("\n")

            # --- All Unique SSIDs Seen ---
            md_lines.append("## 📝 Complete Wireless Reconnaissance History")
            if not sorted_ssids:
                md_lines.append("No SSIDs have been observed yet.\n")
            else:
                md_lines.append("| SSID | BSSID | Channel | Encryption | Packets | Beacons | Last Seen |")
                md_lines.append("| --- | --- | --- | --- | --- | --- | --- |")
                for ssid in sorted_ssids:
                    entries = unique_ssids[ssid]
                    for entry in entries:
                        ssid_display = ssid if ssid != "Hidden or Unknown" else "*Hidden/Unknown*"
                        md_lines.append(
                            f"| {ssid_display} | `{entry.get('bssid')}` | {entry.get('channel') or '-'} | {entry.get('encryption') or '-'} | {entry.get('packets', 0)} | {entry.get('beacons', 0)} | {entry.get('last_seen')[:19]} |"
                        )
                md_lines.append("\n")

            with open(md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))
            self._ensure_file_permissions(md_path)
            LOGGER.info(f"Successfully generated summary reports at {md_path} and {json_path}")
        except Exception:
            LOGGER.exception("Failed to generate handshakes/SSID summary reports")

    # -------------------------
    # Retention / Storage Management
    # -------------------------
    def _calculate_pcap_storage(self) -> int:
        total = 0
        for rec in self._data.get("pcaps", {}).values():
            try:
                p = Path(rec["path"])
                if p.exists():
                    total += p.stat().st_size
            except Exception:
                continue
        return total

    def _prune_old_pcaps(self) -> None:
        total = self._calculate_pcap_storage()
        if total <= MAX_PCAP_STORAGE_BYTES:
            return

        LOGGER.warning(
            "PCAP storage exceeds limit (%.2f GB). Initiating cleanup...",
            total / (1024**3),
        )

        pcaps_sorted = sorted(
            self._data.get("pcaps", {}).items(),
            key=lambda kv: kv[1].get("created", ""),
        )

        for filename, record in pcaps_sorted:
            try:
                path = Path(record.get("path", ""))
                if path.exists():
                    try:
                        path.unlink()
                        LOGGER.info("Deleted old PCAP file: %s", path)
                    except Exception:
                        LOGGER.exception("Failed to delete PCAP file %s", path)
                self._data.get("pcaps", {}).pop(filename, None)
                total = self._calculate_pcap_storage()
                if total <= MAX_PCAP_STORAGE_BYTES:
                    break
            except Exception:
                LOGGER.exception("Error pruning PCAP %s", filename)

        LOGGER.info("Cleanup complete. Current usage: %.2f GB", self._calculate_pcap_storage() / (1024**3))
        self.save()

    def enforce_storage_limit(self) -> None:
        try:
            total = self._calculate_pcap_storage()
            if total > MAX_PCAP_STORAGE_BYTES:
                self._prune_old_pcaps()
        except Exception:
            LOGGER.exception("Storage enforcement failed")

    # -------------------------
    # Utilities / Introspection
    # -------------------------
    def list_known_bssids(self) -> List[str]:
        return list(self._data.get("bssids", {}).keys())

    def list_known_stations(self) -> List[str]:
        return list(self._data.get("stations", {}).keys())

    def get_bssid_record(self, bssid: str) -> Optional[Dict[str, Any]]:
        return self._data.get("bssids", {}).get(bssid.upper())

    def get_station_record(self, sta_mac: str) -> Optional[Dict[str, Any]]:
        return self._data.get("stations", {}).get(sta_mac.upper())

    def get_pcap_records(self) -> Dict[str, Any]:
        return dict(self._data.get("pcaps", {}))

    def get_analysis_for_bssid(self, bssid: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            for rec in self._data.get("pcaps", {}).values():
                if rec.get("bssid", "").upper() == bssid.upper():
                    results.extend(rec.get("analysis", []) or [])
        except Exception:
            LOGGER.exception("get_analysis_for_bssid failed for %s", bssid)
        return results