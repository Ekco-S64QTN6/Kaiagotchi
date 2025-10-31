# Based on UPS Lite v1.1 from https://github.com/xenDE
# Enhanced with better error handling and initialization

import logging
import struct
import time
import RPi.GPIO as GPIO

import kaiagotchi
import kaiagotchi.plugins as plugins
import kaiagotchi.ui.fonts as fonts
from kaiagotchi.ui.components import LabeledValue
from kaiagotchi.ui.view import BLACK

CW2015_ADDRESS = 0X62
CW2015_REG_VCELL = 0X02
CW2015_REG_SOC = 0X04
CW2015_REG_MODE = 0X0A


class UPS:
    def __init__(self):
        # Enhanced: Add initialization tracking
        self._bus = None
        self._initialized = False
        self._init_attempts = 0
        self._max_init_attempts = 3
        self._gpio_setup = False
        
    def _initialize(self):
        """Enhanced: Lazy initialization with retry logic"""
        if self._initialized or self._init_attempts >= self._max_init_attempts:
            return
            
        try:
            import smbus
            self._bus = smbus.SMBus(1)
            self._initialized = True
            logging.info("UPS Lite initialized successfully")
        except Exception as e:
            self._init_attempts += 1
            logging.error(f"UPS Lite initialization failed (attempt {self._init_attempts}): {e}")
            if self._init_attempts >= self._max_init_attempts:
                logging.error("UPS Lite: Maximum initialization attempts reached")

    def _setup_gpio(self):
        """Setup GPIO with error handling"""
        if self._gpio_setup:
            return True
            
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(4, GPIO.IN)
            self._gpio_setup = True
            return True
        except Exception as e:
            logging.error(f"UPS Lite GPIO setup failed: {e}")
            return False

    def voltage(self):
        if not self._initialized:
            self._initialize()
            if not self._initialized:
                return 0.0
        try:
            read = self._bus.read_word_data(CW2015_ADDRESS, CW2015_REG_VCELL)
            swapped = struct.unpack("<H", struct.pack(">H", read))[0]
            return swapped * 1.25 / 1000 / 16
        except Exception as e:
            logging.error(f"UPS Lite voltage read failed: {e}")
            return 0.0

    def capacity(self):
        if not self._initialized:
            self._initialize()
            if not self._initialized:
                return 0.0
        try:
            address = 0x36
            read = self._bus.read_word_data(CW2015_ADDRESS, CW2015_REG_SOC)
            swapped = struct.unpack("<H", struct.pack(">H", read))[0]
            return swapped / 256
        except Exception as e:
            logging.error(f"UPS Lite capacity read failed: {e}")
            return 0.0

    def charging(self):
        if not self._setup_gpio():
            return '-'
        try:
            return '+' if GPIO.input(4) == GPIO.HIGH else '-'
        except Exception as e:
            logging.error(f"UPS Lite charging status read failed: {e}")
            return '-'


class UPSLite(plugins.Plugin):
    __author__ = 'marbasec'
    __version__ = '1.3.0'
    __license__ = 'GPL3'
    __description__ = 'A plugin that will add a voltage indicator for the UPS Lite v1.3'

    def __init__(self):
        self.ups = None

    def on_loaded(self):
        self.ups = UPS()
        logging.info("UPS Lite plugin loaded")

    def on_ui_setup(self, ui):
        ui.add_element('ups', LabeledValue(color=BLACK, label='UPS', value='0%', position=(ui.width() / 2 + 15, 0),
                                           label_font=fonts.Bold, text_font=fonts.Medium))

    def on_unload(self, ui):
        with ui._lock:
            ui.remove_element('ups')
        # Enhanced: Cleanup GPIO
        try:
            GPIO.cleanup()
        except:
            pass

    def on_ui_update(self, ui):
        try:
            capacity = self.ups.capacity()
            charging = self.ups.charging()
            ui.set('ups', "%2i%s" % (capacity, charging))
        except Exception as e:
            logging.error(f"UPS Lite UI update failed: {e}")
            ui.set('ups', "ERR")