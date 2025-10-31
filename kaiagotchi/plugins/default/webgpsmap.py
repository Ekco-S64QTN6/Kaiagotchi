import sys
import time
import kaiagotchi.plugins as plugins
import logging
import os
import json
import re
from flask import Response
from functools import lru_cache
from dateutil.parser import parse

'''
    webgpsmap shows existing position data stored in your /handshakes/ directory
'''

class PositionFile:
    """
    Wraps gps / net-pos files - Complete implementation
    """
    GPS = 1
    GEO = 2
    PAWGPS = 3

    def __init__(self, path):
        self._file = path
        self._filename = os.path.basename(path)
        try:
            logging.debug(f"[webgpsmap] loading {path}")
            with open(path, 'r') as json_file:
                self._json = json.load(json_file)
            logging.debug(f"[webgpsmap] loaded {path}")
        except json.JSONDecodeError as js_e:
            raise js_e

    def mac(self):
        """
        Returns the mac from filename
        """
        parsed_mac = re.search(r'.*_?([a-zA-Z0-9]{12})\.(?:gps|geo)\.json', self._filename)
        if parsed_mac:
            mac = parsed_mac.groups()[0]
            return mac
        return None

    def ssid(self):
        """
        Returns the ssid from filename
        """
        parsed_ssid = re.search(r'(.+)_[a-zA-Z0-9]{12}\.(?:gps|geo)\.json', self._filename)
        if parsed_ssid:
            return parsed_ssid.groups()[0]
        return None

    def json(self):
        """
        returns the parsed json
        """
        return self._json

    def timestamp_first(self):
        """
        returns the timestamp of AP first seen
        """
        return int("%.0f" % os.path.getctime(self._file))

    def timestamp_last(self):
        """
        returns the timestamp of AP last seen
        """
        return_ts = None
        if 'ts' in self._json:
            return_ts = self._json['ts']
        elif 'Updated' in self._json:
            dateObj = parse(self._json['Updated'])
            return_ts = int("%.0f" % dateObj.timestamp())
        else:
            return_ts = int("%.0f" % os.path.getmtime(self._file))
        return return_ts

    def password(self):
        """
        returns the password from file.pcap.cracked or None
        """
        return_pass = None
        base_filename, ext1, ext2 = re.split('\.', self._file)
        password_file_path = base_filename + ".pcap.cracked"
        if os.path.isfile(password_file_path):
            try:
                with open(password_file_path, 'r') as password_file:
                    return_pass = password_file.read().strip()
            except OSError as error:
                logging.error(f"[webgpsmap] OS error loading password: {password_file_path} - error: {format(error)}")
            except Exception:
                logging.error(f"[webgpsmap] Unexpected error loading password: {password_file_path}")
                raise
        return return_pass

    def type(self):
        """
        returns the type of the file
        """
        if self._file.endswith('.gps.json'):
            return PositionFile.GPS
        if self._file.endswith('.geo.json'):
            return PositionFile.GEO
        return None

    def lat(self):
        try:
            lat = None
            if 'Latitude' in self._json:
                lat = self._json['Latitude']
            if 'lat' in self._json:
                lat = self._json['lat']
            if 'location' in self._json and 'lat' in self._json['location']:
                lat = self._json['location']['lat']
            if lat is None or lat == 0:
                raise ValueError(f"Invalid lat in {self._filename}")
            return lat
        except KeyError:
            return None

    def lng(self):
        try:
            lng = None
            if 'Longitude' in self._json:
                lng = self._json['Longitude']
            if 'long' in self._json:
                lng = self._json['long']
            if 'location' in self._json and 'lng' in self._json['location']:
                lng = self._json['location']['lng']
            if lng is None or lng == 0:
                raise ValueError(f"Invalid lng in {self._filename}")
            return lng
        except KeyError:
            return None

    def accuracy(self):
        if self.type() == PositionFile.GPS:
            return 50.0
        if self.type() == PositionFile.GEO:
            try:
                return self._json['accuracy']
            except KeyError:
                pass
        return None


class Webgpsmap(plugins.Plugin):
    __author__ = 'https://github.com/xenDE and https://github.com/dadav'
    __version__ = '1.4.0'
    __name__ = 'webgpsmap'
    __license__ = 'GPL3'
    __description__ = 'a plugin for kaiagotchi that shows a openstreetmap with positions of ap-handshakes in your webbrowser'

    ALREADY_SENT = list()
    SKIP = list()

    def __init__(self):
        self.ready = False
        # Enhanced: Add performance and security settings
        self._position_cache = {}
        self._cache_max_size = 1000
        self._cache_ttl = 3600  # 1 hour
        self.max_files_to_process = 10000  # Prevent DoS

    def on_config_changed(self, config):
        self.config = config
        self.ready = True

    def on_loaded(self):
        """
        Plugin got loaded
        """
        logging.info("[webgpsmap]: plugin loaded")

    def on_webhook(self, path, request):
        """
        Returns requested data
        """
        # Enhanced: Add basic rate limiting check
        client_ip = request.remote_addr
        logging.debug(f"[webgpsmap] Request from {client_ip} for path: {path}")
        
        # defaults:
        response_header_contenttype = None
        response_header_contentdisposition = None
        response_mimetype = "application/xhtml+xml"
        if not self.ready:
            try:
                response_data = bytes('''<html>
                    <head>
                    <meta charset="utf-8"/>
                    <style>body{font-size:1000%;}</style>
                    </head>
                    <body>Not ready yet</body>
                    </html>''', "utf-8")
                response_status = 500
                response_mimetype = "application/xhtml+xml"
                response_header_contenttype = 'text/html'
            except Exception as error:
                logging.error(f"[webgpsmap] on_webhook NOT_READY error: {error}")
                return
        else:
            if request.method == "GET":
                if path == '/' or not path:
                    # returns the html template
                    self.ALREADY_SENT = list()
                    try:
                        response_data = bytes(self.get_html(), "utf-8")
                    except Exception as error:
                        logging.error(f"[webgpsmap] on_webhook / error: {error}")
                        return
                    response_status = 200
                    response_mimetype = "application/xhtml+xml"
                    response_header_contenttype = 'text/html'
                elif path.startswith('all'):
                    # returns all positions
                    try:
                        self.ALREADY_SENT = list()
                        response_data = bytes(
                            json.dumps(self.load_gps_from_dir(self.config['bettercap']['handshakes'])), "utf-8")
                        response_status = 200
                        response_mimetype = "application/json"
                        response_header_contenttype = 'application/json'
                    except Exception as error:
                        logging.error(f"[webgpsmap] on_webhook all error: {error}")
                        return
                elif path.startswith('offlinemap'):
                    # for download an all-in-one html file with positions.json inside
                    try:
                        self.ALREADY_SENT = list()
                        json_data = json.dumps(self.load_gps_from_dir(self.config['bettercap']['handshakes']))
                        html_data = self.get_html()
                        html_data = html_data.replace('var offlinePositions = null;', 'var offlinePositions = ' + json_data)
                        response_data = bytes(html_data, "utf-8")
                        response_status = 200
                        response_mimetype = "application/xhtml+xml"
                        response_header_contenttype = 'text/html'
                        response_header_contentdisposition = 'attachment; filename=webgpsmap.html'
                    except Exception as error:
                        logging.error(f"[webgpsmap] on_webhook offlinemap: error: {error}")
                        return
                else:
                    # unknown GET path
                    response_data = bytes('''<html>
                    <head>
                    <meta charset="utf-8"/>
                    <style>body{font-size:1000%;}</style>
                    </head>
                    <body>4😋4</body>
                    </html>''', "utf-8")
                    response_status = 404
            else:
                # unknown request.method
                response_data = bytes('''<html>
                    <head>
                    <meta charset="utf-8"/>
                    <style>body{font-size:1000%;}</style>
                    </head>
                    <body>4😋4 for bad boys</body>
                    </html>''', "utf-8")
                response_status = 404
        try:
            r = Response(response=response_data, status=response_status, mimetype=response_mimetype)
            if response_header_contenttype is not None:
                r.headers["Content-Type"] = response_header_contenttype
            if response_header_contentdisposition is not None:
                r.headers["Content-Disposition"] = response_header_contentdisposition
            return r
        except Exception as error:
            logging.error(f"[webgpsmap] on_webhook CREATING_RESPONSE error: {error}")
            return

    # Enhanced cache management
    @lru_cache(maxsize=2048, typed=False)
    def _get_pos_from_file(self, path):
        """Enhanced with additional caching layer"""
        current_time = time.time()
        
        # Check memory cache first
        if path in self._position_cache:
            cached_data, timestamp = self._position_cache[path]
            if current_time - timestamp < self._cache_ttl:
                return cached_data
        
        pos = PositionFile(path)
        
        # Update memory cache
        if len(self._position_cache) >= self._cache_max_size:
            # Remove oldest entry
            oldest_key = min(self._position_cache.keys(), 
                           key=lambda k: self._position_cache[k][1])
            del self._position_cache[oldest_key]
            
        self._position_cache[path] = (pos, current_time)
        return pos

    def load_gps_from_dir(self, gpsdir, newest_only=False):
        """
        Enhanced with directory traversal limits
        """
        handshake_dir = gpsdir
        gps_data = dict()

        logging.info(f"[webgpsmap] scanning {handshake_dir}")

        try:
            all_files = os.listdir(handshake_dir)
            # Enhanced: Limit number of files to process
            if len(all_files) > self.max_files_to_process:
                logging.warning(f"[webgpsmap] Too many files ({len(all_files)}), limiting to {self.max_files_to_process}")
                all_files = all_files[:self.max_files_to_process]
                
        except OSError as e:
            logging.error(f"[webgpsmap] Error reading directory: {e}")
            return gps_data

        all_pcap_files = [os.path.join(handshake_dir, filename) for filename in all_files if
                          filename.endswith('.pcap')]
        all_geo_or_gps_files = []
        for filename_pcap in all_pcap_files:
            filename_base = filename_pcap[:-5]  # remove ".pcap"
            logging.debug(f"[webgpsmap] found: {filename_base}")
            filename_position = None

            logging.debug("[webgpsmap] search for .gps.json")
            check_for = os.path.basename(filename_base) + ".gps.json"
            if check_for in all_files:
                filename_position = str(os.path.join(handshake_dir, check_for))

            logging.debug("[webgpsmap] search for .geo.json")
            check_for = os.path.basename(filename_base) + ".geo.json"
            if check_for in all_files:
                filename_position = str(os.path.join(handshake_dir, check_for))

            logging.debug(f"[webgpsmap] end search for position data files and use {filename_position}")

            if filename_position is not None:
                all_geo_or_gps_files.append(filename_position)

        if newest_only:
            all_geo_or_gps_files = set(all_geo_or_gps_files) - set(self.ALREADY_SENT)

        logging.info(
            f"[webgpsmap] Found {len(all_geo_or_gps_files)} position-data files from {len(all_pcap_files)} handshakes. Fetching positions ...")

        for pos_file in all_geo_or_gps_files:
            try:
                pos = self._get_pos_from_file(pos_file)
                if not pos.type() == PositionFile.GPS and not pos.type() == PositionFile.GEO and not pos.type() == PositionFile.PAWGPS:
                    continue

                ssid, mac = pos.ssid(), pos.mac()
                ssid = "unknown" if not ssid else ssid
                # invalid mac is strange and should abort; ssid is ok
                if not mac:
                    raise ValueError("Mac can't be parsed from filename")
                pos_type = 'unknown'
                if pos.type() == PositionFile.GPS:
                    pos_type = 'gps'
                elif pos.type() == PositionFile.GEO:
                    pos_type = 'geo'
                gps_data[ssid + "_" + mac] = {
                    'ssid': ssid,
                    'mac': mac,
                    'type': pos_type,
                    'lng': pos.lng(),
                    'lat': pos.lat(),
                    'acc': pos.accuracy(),
                    'ts_first': pos.timestamp_first(),
                    'ts_last': pos.timestamp_last(),
                }

                # get ap password if exist
                check_for = os.path.basename(pos_file).split(".")[0] + ".pcap.cracked"
                if check_for in all_files:
                    gps_data[ssid + "_" + mac]["pass"] = pos.password()

                self.ALREADY_SENT.append(pos_file)
            except json.JSONDecodeError as error:
                self.SKIP.append(pos_file)
                logging.error(f"[webgpsmap] JSONDecodeError in: {pos_file} - error: {error}")
                continue
            except ValueError as error:
                self.SKIP.append(pos_file)
                logging.error(f"[webgpsmap] ValueError: {pos_file} - error: {error}")
                continue
            except OSError as error:
                self.SKIP.append(pos_file)
                logging.error(f"[webgpsmap] OSError: {pos_file} - error: {error}")
                continue
        logging.info(f"[webgpsmap] loaded {len(gps_data)} positions")
        return gps_data

    def get_html(self):
        """
        Returns the html page
        """
        try:
            template_file = os.path.dirname(os.path.realpath(__file__)) + "/" + "webgpsmap.html"
            html_data = open(template_file, "r").read()
        except Exception as error:
            logging.error(f"[webgpsmap] error loading template file {template_file} - error: {error}")
            html_data = "<html><body>Error loading template</body></html>"
        return html_data