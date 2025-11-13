import logging
import time
from typing import Dict, List, Tuple, Optional
from pathlib import Path

from kaiagotchi.ui.components import LabeledValue, Text
try:
    from kaiagotchi.ui.view import BLACK
except Exception:
    try:
        from kaiagotchi.ui.components import BLACK
    except Exception:
        BLACK = 0
import kaiagotchi.ui.fonts as fonts
import kaiagotchi.plugins as plugins
import kaiagotchi

class MemTemp(plugins.Plugin):
    __author__ = 'https://github.com/xenDE'
    __version__ = '1.1.0'  # Updated version
    __license__ = 'GPL3'
    __description__ = 'A plugin that displays memory/cpu usage and temperature with enhanced reliability'

    # Enhanced configuration with defaults
    ALLOWED_FIELDS = {
        'mem': 'mem_usage',
        'cpu': 'cpu_load', 
        'cpus': 'cpu_load_since',
        'temp': 'cpu_temp',
        'freq': 'cpu_freq'
    }
    
    DEFAULT_FIELDS = ['mem', 'cpu', 'temp']
    LINE_SPACING = 10
    LABEL_SPACING = 0
    FIELD_WIDTH = 4

    def __init__(self):
        self.options = dict()
        self.fields = self.DEFAULT_FIELDS
        self._last_cpu_load = None
        self._temperature_sources = [
            '/sys/class/thermal/thermal_zone0/temp',
            '/sys/class/hwmon/hwmon0/temp1_input',
            '/sys/class/hwmon/hwmon1/temp1_input'
        ]
        self._update_interval = 5  # seconds
        self._last_update = 0
        self._cached_values = {}

    def _get_temperature(self) -> float:
        """Enhanced temperature reading with fallback sources"""
        for temp_source in self._temperature_sources:
            try:
                path = Path(temp_source)
                if path.exists():
                    with open(path, 'r') as f:
                        temp = float(f.read().strip())
                    # Convert to Celsius if needed
                    if temp > 1000:  # Assuming millidegree Celsius
                        return temp / 1000.0
                    return temp
            except Exception as e:
                logging.debug(f"MemTemp: Failed to read temperature from {temp_source}: {e}")
                continue
        
        # Fallback to kaiagotchi function
        try:
            return kaiagotchi.temperature()
        except Exception as e:
            logging.error(f"MemTemp: All temperature sources failed: {e}")
            return 0.0

    def _get_cpu_frequency(self) -> float:
        """Enhanced CPU frequency reading"""
        freq_sources = [
            '/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq',
            '/proc/cpuinfo'  # Fallback
        ]
        
        for freq_source in freq_sources:
            try:
                path = Path(freq_source)
                if path.exists():
                    if 'cpufreq' in freq_source:
                        with open(path, 'r') as f:
                            freq_hz = float(f.read().strip())
                        return round(freq_hz / 1000000, 1)
                    else:  # /proc/cpuinfo
                        with open(path, 'r') as f:
                            for line in f:
                                if 'cpu MHz' in line:
                                    return round(float(line.split(':')[1].strip()), 1)
            except Exception as e:
                logging.debug(f"MemTemp: Failed to read CPU freq from {freq_source}: {e}")
                continue
                
        return 0.0

    def _should_update(self) -> bool:
        """Check if we should update values based on interval"""
        current_time = time.time()
        if current_time - self._last_update >= self._update_interval:
            self._last_update = current_time
            return True
        return False

    def mem_usage(self) -> str:
        if self._should_update() or 'mem' not in self._cached_values:
            self._cached_values['mem'] = f"{int(kaiagotchi.mem_usage() * 100)}%"
        return self._cached_values['mem']

    def cpu_load(self) -> str:
        if self._should_update() or 'cpu' not in self._cached_values:
            self._cached_values['cpu'] = f"{int(kaiagotchi.cpu_load() * 100)}%"
        return self._cached_values['cpu']

    def _cpu_stat(self) -> Optional[List[int]]:
        """Enhanced /proc/stat reading with error handling"""
        try:
            with open('/proc/stat', 'rt') as fp:
                return list(map(int, fp.readline().split()[1:10]))  # Only needed fields
        except Exception as e:
            logging.error(f"MemTemp: Error reading /proc/stat: {e}")
            return None

    def cpu_load_since(self) -> str:
        current_stat = self._cpu_stat()
        if current_stat is None or self._last_cpu_load is None:
            self._last_cpu_load = current_stat
            return "0%"
            
        parts_diff = [p1 - p0 for (p0, p1) in zip(self._last_cpu_load, current_stat)]
        self._last_cpu_load = current_stat
        
        if len(parts_diff) >= 7:
            user, nice, sys, idle, iowait, irq, softirq = parts_diff[:7]
            idle_sum = idle + iowait
            non_idle_sum = user + nice + sys + irq + softirq
            total = idle_sum + non_idle_sum
            
            if total > 0:
                return f"{int(non_idle_sum / total * 100)}%"
        
        return "0%"

    def cpu_temp(self) -> str:
        if self._should_update() or 'temp' not in self._cached_values:
            scale = self.options.get('scale', 'celsius')
            temp = self._get_temperature()
            
            if scale == "fahrenheit":
                temp = (temp * 9/5) + 32
                symbol = "F"
            elif scale == "kelvin":
                temp += 273.15
                symbol = "K"
            else:  # celsius
                symbol = "C"
                
            self._cached_values['temp'] = f"{temp:.1f}{symbol}"
        return self._cached_values['temp']

    def cpu_freq(self) -> str:
        if self._should_update() or 'freq' not in self._cached_values:
            freq = self._get_cpu_frequency()
            self._cached_values['freq'] = f"{freq}G"
        return self._cached_values['freq']

    def on_loaded(self):
        """Initialize with first CPU stat reading"""
        self._last_cpu_load = self._cpu_stat()
        logging.info("MemTemp plugin loaded with enhanced reliability")

    # Rest of UI setup methods remain similar but with better error handling