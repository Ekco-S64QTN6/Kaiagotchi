import os
import logging
import json
import csv
import requests
import kaiagotchi
import re
import time
from glob import glob
from threading import Lock
from io import StringIO
from datetime import datetime, UTC
from dataclasses import dataclass

from flask import make_response, redirect
from kaiagotchi.utils import (
    WifiInfo,
    FieldNotFoundError,
    extract_from_pcap,
    StatusFile,
    remove_whitelisted,
)
from kaiagotchi import plugins
from kaiagotchi.plugins.default.cache import read_ap_cache
from kaiagotchi._version import __version__ as __kaiagotchi_version__

import kaiagotchi.ui.fonts as fonts
from kaiagotchi.ui.components import Text
from kaiagotchi.ui.view import BLACK

from scapy.all import Scapy_Exception


@dataclass
class WigleStatistics:
    ready: bool = False
    username: str = None
    rank: int = None
    monthrank: int = None
    discoveredwiFi: int = None
    last: str = None
    groupID: str = None
    groupname: str = None
    grouprank: int = None

    def update_user(self, json_res):
        self.ready = True
        self.username = json_res["user"]
        self.rank = json_res["rank"]
        self.monthrank = json_res["monthRank"]
        self.discoveredwiFi = json_res["statistics"]["discoveredWiFi"]
        last = json_res["statistics"]["last"]
        self.last = f"{last[6:8]}/{last[4:6]}/{last[0:4]}"

    def update_user_group(self, json_res):
        self.groupID = json_res["groupId"]
        self.groupname = json_res["groupName"]

    def update_group(self, json_res):
        rank = 1
        for group in json_res["groups"]:
            if group["groupId"] == self.groupID:
                self.grouprank = rank
            rank += 1


class Wigle(plugins.Plugin):
    __author__ = "Dadav and updated by Jayofelony and fmatray"
    __version__ = "4.1.0"
    __license__ = "GPL3"
    __description__ = "This plugin automatically uploads collected WiFi to wigle.net"
    LABEL_SPACING = 0

    def __init__(self):
        self.ready = False
        self.report = None
        self.skip = list()
        self.lock = Lock()
        self.options = dict()
        self.statistics = WigleStatistics()
        self.last_stat = datetime.now(tz=UTC)
        self.ui_counter = 0
        # Enhanced: Add performance and retry settings
        self.max_retries = 3
        self.retry_delay = 5
        self.max_files_per_batch = 100  # Prevent memory issues

    def on_loaded(self):
        logging.info("[WIGLE] plugin loaded.")

    def on_config_changed(self, config):
        self.api_key = self.options.get("api_key", None)
        if not self.api_key:
            logging.info("[WIGLE] api_key must be set.")
            return
            
        # Enhanced: Basic API key validation
        if len(self.api_key) < 10:
            logging.error("[WIGLE] API key appears invalid (too short).")
            return
            
        self.donate = self.options.get("donate", False)
        self.handshake_dir = config["bettercap"].get("handshakes")
        report_filename = os.path.join(self.handshake_dir, ".wigle_uploads")
        self.report = StatusFile(report_filename, data_format="json")
        self.cache_dir = os.path.join(self.handshake_dir, "cache")
        self.cvs_dir = self.options.get("cvs_dir", None)
        self.whitelist = config["main"].get("whitelist", [])
        self.timeout = self.options.get("timeout", 30)
        self.position = self.options.get("position", (10, 10))
        self.ready = True
        logging.info("[WIGLE] Ready for wardriving!!!")
        self.get_statistics(force=True)

    def on_webhook(self, path, request):
        return make_response(redirect("https://www.wigle.net/", code=302))

    def get_new_gps_files(self, reported):
        all_gps_files = glob(os.path.join(self.handshake_dir, "*.gps.json"))
        all_gps_files += glob(os.path.join(self.handshake_dir, "*.geo.json"))
        all_gps_files = remove_whitelisted(all_gps_files, self.whitelist)
        
        # Enhanced: Limit batch size for performance
        if len(all_gps_files) > self.max_files_per_batch:
            logging.warning(f"[WIGLE] Limiting batch from {len(all_gps_files)} to {self.max_files_per_batch} files")
            all_gps_files = all_gps_files[:self.max_files_per_batch]
            
        return set(all_gps_files) - set(reported) - set(self.skip)

    # Rest of the methods are already well-implemented, but add retry logic to API calls:
    
    def request_statistics(self, url):
        """Enhanced with retry logic"""
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    headers={
                        "Authorization": f"Basic {self.api_key}",
                        "Accept": "application/json",
                    },
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except (requests.exceptions.RequestException, OSError) as exp:
                logging.warning(f"[WIGLE] API request attempt {attempt + 1} failed: {exp}")
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(self.retry_delay * (2 ** attempt))
        return None

    def post_wigle(self, reported, cvs_filename, cvs_content, no_err_entries):
        """Enhanced with retry logic"""
        for attempt in range(self.max_retries):
            try:
                json_res = requests.post(
                    "https://api.wigle.net/api/v2/file/upload",
                    headers={
                        "Authorization": f"Basic {self.api_key}",
                        "Accept": "application/json",
                    },
                    data={"donate": "on" if self.donate else "false"},
                    files=dict(file=(cvs_filename, cvs_content, "text/csv")),
                    timeout=self.timeout
                ).json()
                
                if not json_res["success"]:
                    raise requests.exceptions.RequestException(json_res["message"])
                    
                reported += no_err_entries
                self.report.update(data={"reported": reported})
                logging.info(f"[WIGLE] Successfully uploaded {len(no_err_entries)} wifis")
                break  # Success, exit retry loop
                
            except (requests.exceptions.RequestException, OSError) as exp:
                logging.warning(f"[WIGLE] Upload attempt {attempt + 1} failed: {exp}")
                if attempt == self.max_retries - 1:
                    self.skip += no_err_entries
                    logging.error(f"[WIGLE] All upload attempts failed: {exp}")
                else:
                    time.sleep(self.retry_delay * (2 ** attempt))