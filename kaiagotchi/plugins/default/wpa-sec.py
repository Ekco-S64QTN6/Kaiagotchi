import os
import logging
import re
import requests
import sqlite3
import time
from datetime import datetime
from enum import Enum
from threading import Lock
from kaiagotchi.utils import remove_whitelisted
from kaiagotchi import plugins
from kaiagotchi.ui.components import LabeledValue
from kaiagotchi.ui.view import BLACK
import kaiagotchi.ui.fonts as fonts


class WpaSec(plugins.Plugin):
    __author__ = '33197631+dadav@users.noreply.github.com'
    __editor__ = 'jayofelony'
    __version__ = '2.1.2'
    __license__ = 'GPL3'
    __description__ = 'This plugin automatically uploads handshakes to https://wpa-sec.stanev.org'
    
    class Status(Enum):
        TOUPLOAD = 0
        INVALID = 1
        SUCCESSFULL = 2

    def __init__(self):
        self.ready = False
        self.lock = Lock()
        self.options = dict()
        # Enhanced: Add retry configuration
        self.max_retries = 3
        self.retry_delay = 5
        
        self._init_db()
        
    def _init_db(self):
        # Enhanced: Better database path handling
        db_path = '/home/pi/.wpa_sec_db'
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        db_conn = sqlite3.connect(db_path)
        db_conn.execute('pragma journal_mode=wal')
        with db_conn:
            db_conn.execute('''
                CREATE TABLE IF NOT EXISTS handshakes (
                    path TEXT PRIMARY KEY,
                    status INTEGER,
                    last_attempt REAL DEFAULT 0,
                    attempt_count INTEGER DEFAULT 0
                )
            ''')
            db_conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_handshakes_status
                ON handshakes (status)
            ''')
        db_conn.close()

    def on_loaded(self):
        """
        Gets called when the plugin gets loaded
        """
        # Enhanced: Better API key validation
        if 'api_key' not in self.options or not self.options['api_key']:
            logging.error("WPA_SEC: API-KEY isn't set. Can't upload.")
            return

        if 'api_url' not in self.options or not self.options['api_url']:
            logging.error("WPA_SEC: API-URL isn't set. Can't upload.")
            return

        # Enhanced: Validate URL format
        if not self.options['api_url'].startswith(('http://', 'https://')):
            logging.error("WPA_SEC: Invalid API URL format.")
            return

        self.skip_until_reload = set()
        self.ready = True
        logging.info("WPA_SEC: plugin loaded.")
        
    def on_handshake(self, agent, filename, access_point, client_station):
        config = agent.config()
        
        if not remove_whitelisted([filename], config['main']['whitelist']):
            return
        
        db_conn = sqlite3.connect('/home/pi/.wpa_sec_db')
        with db_conn:
            db_conn.execute('''
                INSERT INTO handshakes (path, status, last_attempt, attempt_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET status = excluded.status
                WHERE handshakes.status = ?
            ''', (filename, self.Status.TOUPLOAD.value, 0, 0, self.Status.INVALID.value))
        db_conn.close()

    def on_internet_available(self, agent):
        """
        Called when there's internet connectivity
        """
        if not self.ready or self.lock.locked():
            return

        with self.lock:
            display = agent.view()
            
            try:
                db_conn = sqlite3.connect('/home/pi/.wpa_sec_db')
                cursor = db_conn.cursor()
                
                # Enhanced: Add rate limiting for failed uploads
                cursor.execute('''
                    SELECT path FROM handshakes 
                    WHERE status = ? 
                    AND (last_attempt < ? OR attempt_count < ?)
                ''', (self.Status.TOUPLOAD.value, 
                      time.time() - 3600,  # 1 hour cooldown
                      self.max_retries))
                      
                handshakes_toupload = [row[0] for row in cursor.fetchall()]
                handshakes_toupload = set(handshakes_toupload) - self.skip_until_reload

                if handshakes_toupload:
                    logging.info("WPA_SEC: Internet connectivity detected. Uploading new handshakes...")
                    for idx, handshake in enumerate(handshakes_toupload):
                        display.on_uploading(f"WPA-SEC ({idx + 1}/{len(handshakes_toupload)})")
                        logging.info("WPA_SEC: Uploading %s...", handshake)

                        try:
                            upload_response = self._upload_to_wpasec(handshake)
                            
                            if upload_response.startswith("hcxpcapngtool"):
                                logging.info(f"WPA_SEC: {handshake} successfully uploaded.")
                                new_status = self.Status.SUCCESSFULL.value
                                # Reset attempt count on success
                                cursor.execute('UPDATE handshakes SET attempt_count = 0 WHERE path = ?', (handshake,))
                            else:
                                logging.info(f"WPA_SEC: {handshake} uploaded, but it was invalid.")
                                new_status = self.Status.INVALID.value

                            cursor.execute('''
                                INSERT INTO handshakes (path, status)
                                VALUES (?, ?)
                                ON CONFLICT(path) DO UPDATE SET status = excluded.status
                            ''', (handshake, new_status))
                            db_conn.commit()
                            
                        except requests.exceptions.RequestException as e:
                            logging.error(f"WPA_SEC: RequestException uploading {handshake}: {e}")
                            # Enhanced: Track failed attempts
                            cursor.execute('''
                                UPDATE handshakes 
                                SET last_attempt = ?, attempt_count = attempt_count + 1 
                                WHERE path = ?
                            ''', (time.time(), handshake))
                            db_conn.commit()
                            self.skip_until_reload.add(handshake)
                        except OSError as e:
                            logging.error(f"WPA_SEC: OSError uploading {handshake}: {e}")
                            cursor.execute('DELETE FROM handshakes WHERE path = ?', (handshake,))
                            db_conn.commit()
                        except Exception as e:
                            logging.error(f"WPA_SEC: Exception uploading {handshake}: {e}")

                    display.on_normal()
                    
                cursor.close()
                db_conn.close()
            except Exception as e:
                logging.error(f"WPA_SEC: Exception in upload process: {e}")

            try:
                if 'download_results' in self.options and self.options['download_results']:
                    config = agent.config()
                    handshake_dir = config['bettercap']['handshakes']
                    
                    cracked_file_path = os.path.join(handshake_dir, 'wpa-sec.cracked.potfile')

                    if os.path.exists(cracked_file_path):
                        last_check = datetime.fromtimestamp(os.path.getmtime(cracked_file_path))
                        download_interval = int(self.options.get('download_interval', 3600))
                        if last_check is not None and ((datetime.now() - last_check).seconds / download_interval) < 1:
                            return

                    self._download_from_wpasec(cracked_file_path)
                    if 'single_files' in self.options and self.options['single_files']:
                        self._write_cracked_single_files(cracked_file_path, handshake_dir)
            except Exception as e:
                logging.error(f"WPA_SEC: Exception downloading results: {e}")

    def _upload_to_wpasec(self, path, timeout=30):
        """
        Uploads the file to wpasec with enhanced error handling
        """
        # Enhanced: File validation
        if not os.path.exists(path):
            raise FileNotFoundError(f"Handshake file not found: {path}")
            
        if os.path.getsize(path) == 0:
            raise ValueError(f"Handshake file is empty: {path}")

        for attempt in range(self.max_retries):
            try:
                with open(path, 'rb') as file_to_upload:
                    cookie = {'key': self.options['api_key']}
                    payload = {'file': file_to_upload}
                    headers = {"HTTP_USER_AGENT": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:15.0) Gecko/20100101 Firefox/15.0.1"}

                    result = requests.post(
                        self.options['api_url'],
                        cookies=cookie,
                        files=payload,
                        headers=headers,
                        timeout=timeout
                    )
                    result.raise_for_status()
                    
                    response = result.text.partition('\n')[0]
                    logging.debug("WPA_SEC: Response uploading %s: %s.", path, response)
                    return response
                    
            except requests.exceptions.RequestException as e:
                logging.warning(f"WPA_SEC: Upload attempt {attempt + 1} failed for {path}: {e}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff

    # Rest of the methods remain the same as they're already well-implemented
    # _download_from_wpasec, _write_cracked_single_files, on_webhook, etc.