import time
import os
import subprocess
import requests
import logging
import socket
from kaiagotchi.plugins import Plugin

class UploadConvertPlugin(Plugin):
    __author__ = 'Terminatoror'
    __version__ = '1.0.0'
    __license__ = 'GPL3'
    __description__ = 'Converts .pcap files to .hc22000 and uploads them to pwncrack.org when internet is available.'

    def __init__(self):
        self.server_url = 'http://pwncrack.org/upload_handshake'
        self.potfile_url = 'http://pwncrack.org/download_potfile_script'
        self.timewait = 600
        self.last_run_time = 0
        self.options = dict()
        # Enhanced: Add request timeout and retry configuration
        self.timeout = 30
        self.max_retries = 3
        self.retry_delay = 5

    def on_loaded(self):
        logging.info('[pwncrack] loading')

    def on_config_changed(self, config):
        self.handshake_dir = config["bettercap"].get("handshakes")
        self.key = self.options.get('key', "")
        self.whitelist = config["main"].get("whitelist", [])
        self.combined_file = os.path.join(self.handshake_dir, 'combined.hc22000')
        self.potfile_path = os.path.join(self.handshake_dir, 'cracked.pwncrack.potfile')

    def on_internet_available(self, agent):
        current_time = time.time()
        remaining_wait_time = self.timewait - (current_time - self.last_run_time)
        if remaining_wait_time > 0:
            logging.debug(f"[pwncrack] Waiting {remaining_wait_time:.1f} more seconds before next run.")
            return
        self.last_run_time = current_time
        logging.info(f"[pwncrack] Running upload process. Key: {self.key}, waiting: {self.timewait} seconds.")
        try:
            self._convert_and_upload()
            self._download_potfile()
        except Exception as e:
            logging.error(f"[pwncrack] Error occurred during upload process: {e}", exc_info=True)

    def _convert_and_upload(self):
        # Enhanced: Add file size validation and retry logic
        max_file_size = 100 * 1024 * 1024  # 100MB
        
        pcap_files = [f for f in os.listdir(self.handshake_dir)
                      if f.endswith('.pcap') and not any(item in f for item in self.whitelist)]
        
        if not pcap_files:
            logging.info("[pwncrack] No .pcap files found to convert (or all files are whitelisted).")
            return

        # Validate file sizes before processing
        valid_files = []
        for pcap_file in pcap_files:
            file_path = os.path.join(self.handshake_dir, pcap_file)
            if os.path.getsize(file_path) > max_file_size:
                logging.warning(f"[pwncrack] Skipping large file: {pcap_file}")
                continue
            valid_files.append(pcap_file)
        
        if not valid_files:
            return

        # Enhanced: Add retry logic with exponential backoff
        for attempt in range(self.max_retries):
            try:
                # Convert files
                for pcap_file in valid_files:
                    subprocess.run(['hcxpcapngtool', '-o', self.combined_file, 
                                  os.path.join(self.handshake_dir, pcap_file)], 
                                 check=True, timeout=300)

                # Ensure the combined file is created
                if not os.path.exists(self.combined_file):
                    open(self.combined_file, 'w').close()

                # Upload with session for connection pooling
                with requests.Session() as session:
                    with open(self.combined_file, 'rb') as file:
                        files = {'handshake': file}
                        data = {'key': self.key}
                        response = session.post(self.server_url, files=files, data=data, 
                                              timeout=self.timeout)
                        
                response.raise_for_status()
                logging.info(f"[pwncrack] Upload successful: {response.json()}")
                break  # Success, exit retry loop
                
            except (requests.RequestException, subprocess.TimeoutExpired, 
                    subprocess.CalledProcessError) as e:
                logging.warning(f"[pwncrack] Attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    logging.error("[pwncrack] All upload attempts failed")
                    raise
                time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
            finally:
                # Enhanced: Ensure cleanup happens even on failure
                if os.path.exists(self.combined_file):
                    os.remove(self.combined_file)

    def _download_potfile(self):
        # Enhanced: Add retry logic for downloads
        for attempt in range(self.max_retries):
            try:
                with requests.Session() as session:
                    response = session.get(self.potfile_url, params={'key': self.key}, 
                                         timeout=self.timeout)
                response.raise_for_status()
                
                with open(self.potfile_path, 'w') as file:
                    file.write(response.text)
                logging.info(f"[pwncrack] Potfile downloaded to {self.potfile_path}")
                break
                
            except requests.RequestException as e:
                logging.warning(f"[pwncrack] Download attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    logging.error(f"[pwncrack] Failed to download potfile: {response.status_code}")
                    if hasattr(response, 'json'):
                        logging.error(f"[pwncrack] {response.json()}")

    def on_unload(self, ui):
        logging.info('[pwncrack] unloading')