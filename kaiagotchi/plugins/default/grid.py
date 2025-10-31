import os
import logging
import time
import glob
import re
from typing import Tuple, List, Optional
from pathlib import Path

import kaiagotchi.grid as grid
import kaiagotchi.plugins as plugins
from kaiagotchi.utils import StatusFile, WifiInfo, extract_from_pcap
from threading import Lock, RLock


class Grid(plugins.Plugin):
    __author__ = 'evilsocket@gmail.com'
    __version__ = '1.2.0'  # Updated version
    __license__ = 'GPL3'
    __description__ = 'This plugin signals the unit cryptographic identity and list of pwned networks to opwngrid.xyz'

    def __init__(self):
        self.options = dict()
        self.report = StatusFile('/root/.api-report.json', data_format='json')
        self.unread_messages = 0
        self.total_messages = 0
        self.lock = RLock()  # Use RLock for nested operations
        self.last_upload_time = 0
        self.upload_cooldown = 300  # 5 minutes between uploads
        self.max_file_size = 100 * 1024 * 1024  # 100MB limit

    def _validate_pcap_file(self, filepath: str) -> bool:
        """Validate PCAP file before processing"""
        try:
            path = Path(filepath)
            if not path.exists():
                return False
            if path.stat().st_size > self.max_file_size:
                logging.warning(f"Grid: PCAP file too large: {filepath}")
                return False
            if path.stat().st_size == 0:
                logging.warning(f"Grid: Empty PCAP file: {filepath}")
                return False
            return True
        except Exception as e:
            logging.error(f"Grid: Error validating PCAP {filepath}: {e}")
            return False

    def _sanitize_network_id(self, net_id: str) -> Tuple[str, str]:
        """Safely extract ESSID and BSSID from filename"""
        try:
            if '_' in net_id:
                essid, bssid = net_id.split('_', 1)  # Only split on first underscore
            else:
                essid, bssid = '', net_id

            # Validate BSSID format
            mac_re = re.compile(r'^[0-9a-fA-F]{12}$')
            if not mac_re.match(bssid):
                return '', ''

            # Format BSSID with colons
            bssid = ':'.join(bssid[i:i+2] for i in range(0, 12, 2))
            
            return essid, bssid
        except Exception as e:
            logging.error(f"Grid: Error sanitizing network ID {net_id}: {e}")
            return '', ''

    def parse_pcap(self, filename: str) -> Tuple[str, str]:
        """Enhanced PCAP parsing with validation"""
        if not self._validate_pcap_file(filename):
            return '', ''

        logging.info("grid: parsing %s ..." % filename)
        net_id = os.path.basename(filename).replace('.pcap', '')
        
        essid, bssid = self._sanitize_network_id(net_id)
        if not bssid:
            return '', ''

        info = {
            WifiInfo.ESSID: essid,
            WifiInfo.BSSID: bssid,
        }

        try:
            extracted_info = extract_from_pcap(filename, [WifiInfo.BSSID, WifiInfo.ESSID])
            # Validate extracted data
            if WifiInfo.BSSID in extracted_info and extracted_info[WifiInfo.BSSID]:
                info = extracted_info
        except Exception as e:
            logging.error("grid: error parsing pcap %s: %s" % (filename, e))
            # Fall back to filename parsing if PCAP extraction fails

        return info.get(WifiInfo.ESSID, ''), info.get(WifiInfo.BSSID, '')

    def is_excluded(self, what, agent):
        config = agent.config()
        for skip in config['main']['whitelist']:
            skip = skip.lower()
            what = what.lower()
            if skip in what or skip.replace(':', '') in what:
                return True
        return False

    def set_reported(self, reported, net_id):
        if net_id not in reported:
            reported.append(net_id)
        self.report.update(data={'reported': reported})

    def check_inbox(self, agent):
        logging.debug("checking mailbox ...")
        messages = grid.inbox()
        self.total_messages = len(messages)
        self.unread_messages = len([m for m in messages if m['seen_at'] is None])

        if self.unread_messages:
            plugins.on('unread_inbox', self.unread_messages)
            logging.debug("[grid] unread:%d total:%d" % (self.unread_messages, self.total_messages))
            agent.view().on_unread_messages(self.unread_messages, self.total_messages)

    def check_handshakes(self, agent):
        """Enhanced handshake checking with rate limiting"""
        if time.time() - self.last_upload_time < self.upload_cooldown:
            logging.debug("Grid: Upload cooldown active, skipping")
            return

        logging.debug("checking pcap's")
        config = agent.config()

        try:
            handshake_dir = config['bettercap']['handshakes']
            pcap_files = glob.glob(os.path.join(handshake_dir, "*.pcap"))
            
            # Filter valid files
            valid_pcaps = [f for f in pcap_files if self._validate_pcap_file(f)]
            num_networks = len(valid_pcaps)
            
            reported = self.report.data_field_or('reported', default=[])
            num_reported = len(reported)
            num_new = num_networks - num_reported

            if num_new > 0 and self.options.get('report', True):
                logging.info("grid: %d new networks to report" % num_new)
                successful_uploads = 0

                for pcap_file in valid_pcaps:
                    net_id = os.path.basename(pcap_file).replace('.pcap', '')
                    if net_id in reported:
                        continue

                    if self.is_excluded(net_id, agent):
                        logging.debug("skipping %s due to exclusion filter" % pcap_file)
                        self.set_reported(reported, net_id)
                        continue

                    essid, bssid = self.parse_pcap(pcap_file)
                    if bssid and not (self.is_excluded(essid, agent) or self.is_excluded(bssid, agent)):
                        try:
                            if grid.report_ap(essid, bssid):
                                self.set_reported(reported, net_id)
                                successful_uploads += 1
                                # Rate limiting between uploads
                                time.sleep(2.0)
                            else:
                                logging.warning(f"Grid: Failed to report AP {essid}/{bssid}")
                        except Exception as e:
                            logging.error(f"Grid: Error reporting AP {essid}/{bssid}: {e}")
                    else:
                        logging.debug(f"Grid: Skipping invalid or excluded AP: {pcap_file}")

                self.last_upload_time = time.time()
                if successful_uploads > 0:
                    logging.info(f"Grid: Successfully reported {successful_uploads} new networks")
                    
        except Exception as e:
            logging.error(f"Grid: Error in check_handshakes: {e}")

    def on_loaded(self):
        logging.info("grid plugin loaded with enhanced security.")

    def on_webhook(self, path, request):
        from flask import make_response, redirect
        response = make_response(redirect("https://opwngrid.xyz", code=302))
        return response

    def on_internet_available(self, agent):
        logging.debug("internet available")

        if self.lock.locked():
            return

        with self.lock:
            try:
                grid.update_data(agent.last_session)
            except Exception as e:
                logging.error("error connecting to the pwngrid-peer service: %s" % e)
                logging.debug(e, exc_info=True)
                return

            try:
                self.check_inbox(agent)
            except Exception as e:
                logging.error("[grid] error while checking inbox: %s" % e)
                logging.debug(e, exc_info=True)

            try:
                self.check_handshakes(agent)
            except Exception as e:
                logging.error("[grid] error while checking pcaps: %s" % e)
                logging.debug(e, exc_info=True)