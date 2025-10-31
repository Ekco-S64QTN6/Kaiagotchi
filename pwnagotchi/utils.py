import logging
import glob
import os
import subprocess
import json
import shutil
import sys
from typing import List, Dict, Any, Tuple, Union, Optional

import tomlkit
import requests
import toml
import yaml

from zipfile import ZipFile
from datetime import datetime
from enum import Enum

# Scapy imports used in extract_from_pcap
from scapy.all import sniff
from scapy.layers.dot11 import (
    Dot11, Dot11Beacon, Dot11ProbeResp, Dot11AssoReq,
    Dot11ReassoReq, Dot11Elt, RadioTap
)

def parse_version(version: str) -> Tuple[str, ...]:
    """
    Converts a version str to tuple, so that versions can be compared
    """
    return tuple(version.split('.'))


def remove_whitelisted(
    list_of_handshakes: List[str],
    list_of_whitelisted_strings: List[str],
    valid_on_error: bool = True
) -> List[str]:
    """
    Removes a given list of whitelisted handshakes from a path list
    """
    filtered: List[str] = list()

    def normalize(name: str) -> str:
        """
        Only allow alpha/nums
        """
        return str.lower(''.join(c for c in name if c.isalnum()))

    for handshake in list_of_handshakes:
        try:
            # Extract filename (e.g., 'BSSID_ESSID.pcap') and remove extension
            normalized_handshake = normalize(os.path.basename(handshake).rstrip('.pcap'))
            
            for whitelist in list_of_whitelisted_strings:
                normalized_whitelist = normalize(whitelist)
                if normalized_whitelist in normalized_handshake:
                    break
            else:
                filtered.append(handshake)
        except Exception:
            if valid_on_error:
                filtered.append(handshake)
    return filtered


def download_file(url: str, destination: str, chunk_size: int = 128):
    """
    Downloads a file from a URL to a specified destination.
    """
    resp = requests.get(url, stream=True)
    resp.raise_for_status()

    with open(destination, 'wb') as fd:
        for chunk in resp.iter_content(chunk_size):
            fd.write(chunk)


def unzip(file: str, destination: str, strip_dirs: int = 0):
    """
    Unzips a file to a destination, optionally stripping leading directory components.
    """
    os.makedirs(destination, exist_ok=True)
    with ZipFile(file, 'r') as zip_file:
        if strip_dirs:
            # Manually extract while stripping directories
            for info in zip_file.infolist():
                parts = info.filename.split('/', maxsplit=strip_dirs)
                new_filename = parts[-1] if len(parts) > strip_dirs else ''
                
                if new_filename:
                    # Create necessary directories for the stripped path
                    target_path = os.path.join(destination, new_filename)
                    if not target_path.endswith('/'):
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    
                    with zip_file.open(info) as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
        else:
            zip_file.extractall(destination)


def merge_config(user: Dict[str, Any], default: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merges default configuration settings into the user configuration.
    User settings override defaults.
    """
    if isinstance(user, dict) and isinstance(default, dict):
        for k, v in default.items():
            if k not in user:
                user[k] = v
            else:
                user[k] = merge_config(user[k], v)
    return user


def keys_to_str(data: Union[List[Any], Dict[Any, Any]]) -> Union[List[Any], Dict[str, Any]]:
    """
    Recursively converts dictionary keys (e.g., int/float keys from YAML) to strings.
    """
    if isinstance(data, list):
        converted_list = list()
        for item in data:
            if isinstance(item, list) or isinstance(item, dict):
                converted_list.append(keys_to_str(item))
            else:
                converted_list.append(item)
        return converted_list

    converted_dict: Dict[str, Any] = dict()
    for key, value in data.items():
        if isinstance(value, list) or isinstance(value, dict):
            converted_dict[str(key)] = keys_to_str(value)
        else:
            converted_dict[str(key)] = value

    return converted_dict


def save_config(config: Dict[str, Any], target: str) -> bool:
    """
    Saves the TOML configuration to the specified target file using tomlkit.
    """
    with open(target, 'wt') as fp:
        # tomlkit is used for preserving structure and comments
        fp.write(tomlkit.dumps(config))
    return True


def load_toml_file(filename: str) -> Dict[str, Any]:
    """
    Loads TOML data from a file, handling migration from dotted TOML format
    (which lacks [main] header) to the preferred tomlkit format.
    """
    with open(filename) as fp:
        text = fp.read()
    
    # Check if it uses the modern, multi-table format (which includes "[main]")
    if text.find("[main]") != -1:
        return tomlkit.loads(text)
    else:
        # This is a legacy dotted TOML file, load with standard 'toml' library
        # and then convert to the modern format using tomlkit.
        sys.stderr.write(f"Converting dotted toml {filename}: {text[0:100]}...\n")
        
        # Load legacy format
        data = toml.loads(text)
        
        # Save original as a backup and convert to new format
        try:
            backup = filename + ".ORIG"
            os.rename(filename, backup)
            with open(filename, "w") as fp2:
                tomlkit.dump(data, fp2)
            sys.stderr.write(f"Converted to new format. Original saved at {backup}\n")
        except Exception as e:
            sys.stderr.write(f"Unable to convert {filename} to new format: {e}\n")
            
        return data


def load_config(args: Any) -> Dict[str, Any]:
    """
    Loads, migrates, and merges the default, user, and drop-in configurations.
    Handles configuration files found in /boot/firmware for first-time setup/migration.
    """
    default_config_path = os.path.dirname(args.config)
    if not os.path.exists(default_config_path):
        os.makedirs(default_config_path)

    import kaiagotchi # Use the new project name
    ref_defaults_file = os.path.join(os.path.dirname(kaiagotchi.__file__), 'defaults.toml')
    
    # 1. Check for config files in /boot/firmware for installation/migration
    for boot_conf in ['/boot/config.yml', '/boot/firmware/config.yml', '/boot/config.toml', '/boot/firmware/config.toml']:
        if os.path.exists(boot_conf):
            # Log to stderr since logging might not be fully configured yet
            sys.stderr.write(f"installing new {boot_conf} to {args.user_config} ...\n")
            
            # The original code had an invalid merge call here that passed file paths.
            # We skip merging here and rely on the full config merge later.
            
            # Move config from boot partition to user config location
            try:
                shutil.move(boot_conf, args.user_config)
            except OSError as e:
                # Handle cross-device link error (common when moving files across partitions)
                if e.errno == 18: 
                    shutil.copy(boot_conf, args.user_config)
                    os.remove(boot_conf)
                else:
                    raise
            break

    # 2. Check for an entire pwnagotchi folder on /boot/ (legacy migration)
    if os.path.isdir('/boot/firmware/pwnagotchi'):
        sys.stderr.write("installing /boot/firmware/pwnagotchi to /etc/pwnagotchi ...\n")
        shutil.rmtree('/etc/pwnagotchi', ignore_errors=True)
        shutil.move('/boot/firmware/pwnagotchi', '/etc/')

    # 3. Ensure the base defaults config exists
    if not os.path.exists(args.config):
        sys.stderr.write(f"copying {ref_defaults_file} to {args.config} ...\n")
        shutil.copy(ref_defaults_file, args.config)
    else:
        # Check if the user modified the base defaults file (should not happen if they use user_config)
        with open(ref_defaults_file) as fp:
            ref_defaults_data = fp.read()

        with open(args.config) as fp:
            defaults_data = fp.read()

        if ref_defaults_data != defaults_data:
            sys.stderr.write(f"!!! file in {args.config} is different than release defaults, overwriting !!!\n")
            shutil.copy(ref_defaults_file, args.config)


    # 4. Load the defaults config
    config = load_toml_file(args.config)

    # 5. Load the user config and merge it with defaults
    try:
        user_config: Optional[Dict[str, Any]] = None
        
        # Check for legacy YAML file for migration
        yaml_name = args.user_config.replace('.toml', '.yml')
        if not os.path.exists(args.user_config) and os.path.exists(yaml_name):
            # No TOML found; convert YAML
            logging.info('Old yaml-config found. Converting to toml...')
            with open(yaml_name) as yaml_file:
                user_config = yaml.safe_load(yaml_file)
            
            # Convert int/float keys to str (YAML spec allows non-string keys)
            user_config = keys_to_str(user_config)
            
            # Save converted config as TOML
            with open(args.user_config, 'w') as toml_file:
                 tomlkit.dump(user_config, toml_file)
            
        elif os.path.exists(args.user_config):
            # Load existing TOML user config
            user_config = load_toml_file(args.user_config)

        if user_config:
            # Merge user config over defaults
            config = merge_config(user_config, config)
            
    except Exception as ex:
        logging.error("There was an error processing the configuration file:\n%s ", ex)
        sys.exit(1)

    # 6. Load and merge drop-in config files
    dropin = config.get('main', {}).get('confd')
    if dropin and os.path.isdir(dropin):
        # Build glob pattern: 'path/to/conf.d/*.toml'
        dropin_pattern = os.path.join(dropin, '*.toml') if dropin.endswith('/') else f"{dropin}/*.toml"
        
        for conf in glob.glob(dropin_pattern):
            additional_config = load_toml_file(conf)
            # Drop-in config should override current config
            config = merge_config(additional_config, config)

    # 7. Apply mandatory normalization (forcing headless mode)
    display_type = config.get('ui', {}).get('display', {}).get('type')
    if display_type not in ('dummy', 'dummydisplay'):
        logging.debug(f"Display type '{display_type}' is not supported on this architecture. Forcing 'dummydisplay'.")
        config['ui']['display']['type'] = 'dummydisplay'

    return config


def secs_to_hhmmss(secs: Union[int, float]) -> str:
    """
    Converts seconds into HH:MM:SS format.
    """
    secs = int(secs)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
    return '%02d:%02d:%02d' % (hours, mins, secs)


def total_unique_handshakes(path: str) -> int:
    """
    Returns the count of unique handshakes (files ending in .pcap) in a directory.
    """
    expr = os.path.join(path, "*.pcap")
    return len(glob.glob(expr))


def iface_channels(ifname: str) -> List[int]:
    """
    Returns a list of available wireless channels for a given interface name,
    by parsing 'iw' output.
    """
    channels = []
    # Find the physical device name
    phy = subprocess.getoutput(f"/sbin/iw {ifname} info | grep wiphy | cut -d ' ' -f 2")
    
    # Get all non-disabled channels from iw output
    output = subprocess.getoutput(f"/sbin/iw phy{phy} channels | grep ' MHz' | grep -v disabled | sed 's/^.*\[//g' | sed s/\].*\$//g")
    
    for line in output.split("\n"):
        line = line.strip()
        try:
            channels.append(int(line))
        except Exception:
            # Ignore lines that aren't pure channel numbers
            pass
    return channels


class WifiInfo(Enum):
    """
    Fields you can extract from a pcap file
    """
    BSSID = 0
    ESSID = 1
    ENCRYPTION = 2
    CHANNEL = 3
    FREQUENCY = 4
    RSSI = 5


class FieldNotFoundError(Exception):
    pass


def md5(fname: str) -> str:
    """
    Calculates the MD5 checksum of a file.
    """
    import hashlib
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        # Read in chunks for large files
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def extract_from_pcap(path: str, fields: List[WifiInfo]) -> Dict[WifiInfo, Any]:
    """
    Search in pcap-file for specified information using scapy.

    path: Path to pcap file
    fields: Array of fields that should be extracted

    If a field is not found, FieldNotFoundError is raised
    """
    # NOTE: The dependency on pwnagotchi.mesh.wifi is still here.
    # Assuming it's now kaiagotchi.mesh.wifi
    try:
        from kaiagotchi.mesh.wifi import freq_to_channel
    except ImportError:
        logging.error("kaiagotchi.mesh.wifi not found, cannot calculate channel.")
        # Define a mock function if the import fails to prevent crash
        def freq_to_channel(freq):
            raise FieldNotFoundError(f"Missing dependency for channel conversion: {freq}")
            
    results: Dict[WifiInfo, Any] = dict()
    
    # BPF filters are constructed manually to specify management subtypes
    
    for field in fields:
        subtypes = set()
        bpf_filter = ""
        
        if field == WifiInfo.BSSID:
            # BSSID is found in Dot11.addr3 of Beacons
            subtypes.add('beacon')
            bpf_filter = f"wlan type mgt and wlan subtype {' or wlan subtype '.join(subtypes)}"
            packets = sniff(offline=path, filter=bpf_filter, timeout=1)
            
            try:
                for packet in packets:
                    if packet.haslayer(Dot11Beacon) and hasattr(packet[Dot11], 'addr3'):
                        results[field] = packet[Dot11].addr3
                        break
                else:
                    raise FieldNotFoundError("Could not find field [BSSID]")
            except Exception:
                raise FieldNotFoundError("Could not find field [BSSID]")

        elif field == WifiInfo.ESSID:
            # ESSID is found in the Dot11Elt layer of Beacons/AssocReq/ReassocReq
            subtypes.add('beacon')
            subtypes.add('assoc-req')
            subtypes.add('reassoc-req')
            bpf_filter = f"wlan type mgt and wlan subtype {' or wlan subtype '.join(subtypes)}"
            packets = sniff(offline=path, filter=bpf_filter, timeout=1)
            
            try:
                for packet in packets:
                    # Look for the information element (Dot11Elt) which contains the ESSID
                    if packet.haslayer(Dot11Elt) and hasattr(packet[Dot11Elt], 'info'):
                        essid_info = packet[Dot11Elt].info
                        # ESSID can be empty (hidden), check length before decoding
                        if essid_info:
                            results[field] = essid_info.decode('utf-8')
                            break
                else:
                    raise FieldNotFoundError("Could not find field [ESSID]")
            except Exception:
                raise FieldNotFoundError("Could not find field [ESSID]")

        elif field == WifiInfo.ENCRYPTION:
            # Encryption info is derived from Dot11Beacon
            subtypes.add('beacon')
            bpf_filter = f"wlan type mgt and wlan subtype {' or wlan subtype '.join(subtypes)}"
            packets = sniff(offline=path, filter=bpf_filter, timeout=1)
            
            try:
                for packet in packets:
                    if packet.haslayer(Dot11Beacon) and hasattr(packet[Dot11Beacon], 'network_stats'):
                        stats = packet[Dot11Beacon].network_stats()
                        if 'crypto' in stats:
                            results[field] = stats['crypto']  # set with encryption types
                            break
                else:
                    raise FieldNotFoundError("Could not find field [ENCRYPTION]")
            except Exception:
                raise FieldNotFoundError("Could not find field [ENCRYPTION]")

        elif field == WifiInfo.CHANNEL:
            # Channel is derived from frequency in RadioTap
            packets = sniff(offline=path, count=1, timeout=1)
            try:
                # Need the freq_to_channel function from the project's mesh.wifi
                results[field] = freq_to_channel(packets[0][RadioTap].ChannelFrequency)
            except IndexError:
                 raise FieldNotFoundError("Could not find any packets to read RadioTap data.")
            except Exception:
                raise FieldNotFoundError("Could not find field [CHANNEL]")

        elif field == WifiInfo.FREQUENCY:
            # Frequency is stored directly in RadioTap
            packets = sniff(offline=path, count=1, timeout=1)
            try:
                results[field] = packets[0][RadioTap].ChannelFrequency
            except IndexError:
                 raise FieldNotFoundError("Could not find any packets to read RadioTap data.")
            except Exception:
                raise FieldNotFoundError("Could not find field [FREQUENCY]")

        elif field == WifiInfo.RSSI:
            # RSSI (Antenna Signal Strength) is stored in RadioTap
            packets = sniff(offline=path, count=1, timeout=1)
            try:
                results[field] = packets[0][RadioTap].dBm_AntSignal
            except IndexError:
                 raise FieldNotFoundError("Could not find any packets to read RadioTap data.")
            except Exception:
                raise FieldNotFoundError("Could not find field [RSSI]")

        else:
            raise TypeError("Invalid field")
            
    return results


class StatusFile(object):
    """
    A utility class for managing simple status files, often used for caching data 
    that expires after a certain time (e.g., last update time, cached JSON data).
    """
    def __init__(self, path: str, data_format: str = 'raw'):
        self._path = path
        self._updated: Optional[datetime] = None
        self._format = data_format
        self.data: Any = None

        if os.path.exists(path):
            self._updated = datetime.fromtimestamp(os.path.getmtime(path))
            with open(path) as fp:
                if data_format == 'json':
                    try:
                        self.data = json.load(fp)
                    except json.JSONDecodeError:
                        logging.warning(f"StatusFile at {path} could not be decoded as JSON.")
                        self.data = None
                else:
                    self.data = fp.read()

    def data_field_or(self, name: str, default: Any = "") -> Any:
        """
        Retrieves a field from the loaded JSON data, or returns a default value.
        """
        if isinstance(self.data, dict) and name in self.data:
            return self.data[name]
        return default

    def newer_then_minutes(self, minutes: int) -> bool:
        """
        Checks if the file was modified more recently than 'minutes' ago.
        """
        return self._updated is not None and ((datetime.now() - self._updated).total_seconds() / 60) < minutes

    def newer_then_hours(self, hours: int) -> bool:
        """
        Checks if the file was modified more recently than 'hours' ago.
        """
        return self._updated is not None and ((datetime.now() - self._updated).total_seconds() / (60 * 60)) < hours

    def newer_then_days(self, days: int) -> bool:
        """
        Checks if the file was modified more recently than 'days' ago.
        """
        return self._updated is not None and (datetime.now() - self._updated).days < days

    def update(self, data: Any = None):
        """
        Writes the status or data to the file, updating the internal timestamp.
        """
        # Ensure we only try to import ensure_write once the environment is loaded
        try:
            from kaiagotchi.fs import ensure_write
        except ImportError:
            logging.error("Missing dependency: kaiagotchi.fs.ensure_write")
            return
            
        self._updated = datetime.now()
        self.data = data
        with ensure_write(self._path, 'w') as fp:
            if data is None:
                # If no data is passed, write the timestamp
                fp.write(str(self._updated))

            elif self._format == 'json':
                json.dump(self.data, fp)

            else:
                fp.write(data)
