import os
import logging
import requests
import time
import hashlib
from datetime import datetime
from threading import Lock
from pathlib import Path
from typing import List, Tuple, Optional

from kaiagotchi.utils import StatusFile
import kaiagotchi.plugins as plugins
from kaiagotchi import security

class OHCAPI(plugins.Plugin):  # Fixed class name convention
    __author__ = 'Rohan Dayaram'
    __version__ = '1.2.0'  # Updated version
    __license__ = 'GPL3'
    __description__ = 'Uploads WPA/WPA2 handshakes to OnlineHashCrack.com using API V2 with enhanced security'

    def __init__(self):
        self.ready = False
        self.lock = Lock()
        self.status_file_path = '/root/handshakes/.ohc_uploads'
        
        # Enhanced initialization with backup
        try:
            self.report = StatusFile(self.status_file_path, data_format='json')
        except Exception as e:
            logging.warning(f"OHCAPI: Corrupted status file, resetting: {e}")
            backup_path = f"{self.status_file_path}.backup.{int(time.time())}"
            try:
                if os.path.exists(self.status_file_path):
                    os.rename(self.status_file_path, backup_path)
            except:
                pass
            self.report = StatusFile(self.status_file_path, data_format='json')
            
        self.skip = set()  # Use set for faster lookups
        self.last_run = 0
        self.internet_active = False
        self.max_file_size = 100 * 1024 * 1024  # 100MB
        self.retry_count = 0
        self.max_retries = 3

    def _validate_api_key(self, api_key: str) -> bool:
        """Validate API key format"""
        if not api_key or not isinstance(api_key, str):
            return False
        if len(api_key) < 10:  # Basic length check
            return False
        # Add more validation as per OHC API key format
        return True

    def _validate_file(self, filepath: str) -> bool:
        """Enhanced file validation"""
        try:
            path = Path(filepath)
            if not path.exists():
                return False
            if path.stat().st_size > self.max_file_size:
                logging.warning(f"OHCAPI: File too large: {filepath}")
                return False
            if path.stat().st_size == 0:
                logging.warning(f"OHCAPI: Empty file: {filepath}")
                return False
            return True
        except Exception as e:
            logging.error(f"OHCAPI: File validation error for {filepath}: {e}")
            return False

    def on_loaded(self):
        """Enhanced plugin loading with validation"""
        required_fields = ['api_key']
        missing = [field for field in required_fields if field not in self.options or not self.options[field]]
        
        if missing:
            logging.error(f"OHCAPI: Missing required config fields: {missing}")
            return

        # Validate API key
        if not self._validate_api_key(self.options['api_key']):
            logging.error("OHCAPI: Invalid API key format")
            return

        # Set defaults with validation
        self.options.setdefault('receive_email', 'yes')
        self.options.setdefault('sleep', 3600)  # 1 hour
        self.options.setdefault('max_batch_size', 50)
        
        # Validate sleep interval
        if self.options['sleep'] < 300:  # Minimum 5 minutes
            logging.warning("OHCAPI: Sleep interval too short, setting to 300s")
            self.options['sleep'] = 300

        self.ready = True
        logging.info("OHCAPI: Plugin loaded with enhanced security")

    def _extract_hashes_from_handshake(self, pcap_path: str) -> Optional[List[str]]:
        """Enhanced hash extraction with better error handling"""
        if not self._validate_file(pcap_path):
            return None

        hcxpcapngtool = '/usr/bin/hcxpcapngtool'
        hccapx_path = pcap_path.replace('.pcap', '.22000')
        
        # Validate tool exists
        if not os.path.exists(hcxpcapngtool):
            logging.error("OHCAPI: hcxpcapngtool not found")
            return None

        try:
            # Use subprocess with timeout for security
            import subprocess
            result = subprocess.run(
                [hcxpcapngtool, '-o', hccapx_path, pcap_path],
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            if result.returncode != 0:
                logging.error(f"OHCAPI: hcxpcapngtool failed: {result.stderr}")
                return None
                
            if os.path.exists(hccapx_path) and os.path.getsize(hccapx_path) > 0:
                with open(hccapx_path, 'r', encoding='utf-8', errors='ignore') as f:
                    hashes = [line.strip() for line in f if line.strip()]
                # Clean up temporary file
                os.remove(hccapx_path)
                return hashes
            else:
                logging.debug(f"OHCAPI: No hashes extracted from {pcap_path}")
                return None
                
        except subprocess.TimeoutExpired:
            logging.error(f"OHCAPI: hcxpcapngtool timeout for {pcap_path}")
            return None
        except Exception as e:
            logging.error(f"OHCAPI: Error extracting hashes from {pcap_path}: {e}")
            return None

    def _add_tasks(self, hashes: List[str], timeout: int = 30) -> bool:
        """Enhanced task submission with retry logic"""
        if not hashes:
            return True

        clean_hashes = [h.strip() for h in hashes if h.strip()]
        if not clean_hashes:
            return True

        payload = {
            'api_key': self.options['api_key'],
            'agree_terms': "yes",
            'action': 'add_tasks',
            'algo_mode': 22000,
            'hashes': clean_hashes,
            'receive_email': self.options['receive_email']
        }

        for attempt in range(self.max_retries):
            try:
                # Create session for connection reuse
                with requests.Session() as session:
                    session.headers.update({
                        'User-Agent': 'Kaiagotchi-Plugin/1.2.0',
                        'Content-Type': 'application/json'
                    })
                    
                    response = session.post(
                        'https://api.onlinehashcrack.com/v2',
                        json=payload,
                        timeout=timeout,
                        verify=True  # Enable SSL verification
                    )
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    logging.info(f"OHCAPI: Batch upload successful - {len(clean_hashes)} hashes")
                    return True
                    
            except requests.exceptions.RequestException as e:
                logging.warning(f"OHCAPI: Upload attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) * 5  # Exponential backoff
                    logging.info(f"OHCAPI: Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logging.error(f"OHCAPI: All upload attempts failed for batch")
                    return False

        return False

    # Rest of methods with similar enhanced error handling and security