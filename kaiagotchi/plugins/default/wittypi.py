# Witty Pi 4 L3V7
#
import logging
import time
import kaiagotchi.plugins as plugins
import kaiagotchi.ui.fonts as fonts
from kaiagotchi.ui.components import LabeledValue
from kaiagotchi.ui.view import BLACK

class UPS:
    I2C_MC_ADDRESS = 0x08
    I2C_VOLTAGE_IN_I = 1
    I2C_VOLTAGE_IN_D = 2
    I2C_CURRENT_OUT_I = 5
    I2C_CURRENT_OUT_D = 6
    I2C_POWER_MODE = 7

    def __init__(self):
        # Enhanced: Add initialization tracking
        self._bus = None
        self._initialized = False
        self._init_attempts = 0
        self._max_init_attempts = 3
        
    def _initialize(self):
        """Enhanced: Lazy initialization with retry logic"""
        if self._initialized or self._init_attempts >= self._max_init_attempts:
            return
            
        try:
            # only import when the module is loaded and enabled
            import smbus
            # 0 = /dev/i2c-0 (port I2C0), 1 = /dev/i2c-1 (port I2C1)
            self._bus = smbus.SMBus(1)
            self._initialized = True
            logging.info("WittyPi UPS initialized successfully")
        except Exception as e:
            self._init_attempts += 1
            logging.error(f"WittyPi UPS initialization failed (attempt {self._init_attempts}): {e}")
            if self._init_attempts >= self._max_init_attempts:
                logging.error("WittyPi UPS: Maximum initialization attempts reached")

    def voltage(self):
        if not self._initialized:
            self._initialize()
            if not self._initialized:
                return 0.0
        try:
            i = self._bus.read_byte_data(self.I2C_MC_ADDRESS, self.I2C_VOLTAGE_IN_I)
            d = self._bus.read_byte_data(self.I2C_MC_ADDRESS, self.I2C_VOLTAGE_IN_D)
            return (i + d / 100)
        except Exception as e:
            logging.error(f"WittyPi voltage read failed: {e}")
            return 0.0

    def current(self):
        if not self._initialized:
            self._initialize()
            if not self._initialized:
                return 0.0
        try:
            i = self._bus.read_byte_data(self.I2C_MC_ADDRESS, self.I2C_CURRENT_OUT_I)
            d = self._bus.read_byte_data(self.I2C_MC_ADDRESS, self.I2C_CURRENT_OUT_D)
            return (i + d / 100)
        except Exception as e:
            logging.error(f"WittyPi current read failed: {e}")
            return 0.0

    def capacity(self):
        voltage = max(3.1, min(self.voltage(), 4.2)) # Clamp voltage
        return round((voltage - 3.1) / (4.2 - 3.1) * 100)

    def charging(self):
        if not self._initialized:
            self._initialize()
            if not self._initialized:
                return '-'
        try:
            dc = self._bus.read_byte_data(self.I2C_MC_ADDRESS, self.I2C_POWER_MODE)
            return '+' if dc == 0 else '-'
        except Exception as e:
            logging.error(f"WittyPi charging status read failed: {e}")
            return '-'

class WittyPi(plugins.Plugin):
    __author__ = 'https://github.com/krishenriksen'
    __version__ = '1.0.0'
    __license__ = 'GPL3'
    __description__ = 'A plugin that will display battery info from Witty Pi 4 L3V7'

    def __init__(self):
        self.ups = None

    def on_loaded(self):
        self.ups = UPS()
        logging.info("wittypi plugin loaded.")

    def on_ui_setup(self, ui):
        ui.add_element('ups', LabeledValue(color=BLACK, label='UPS', value='0%', position=(ui.width() / 2 + 15, 0), label_font=fonts.Bold, text_font=fonts.Medium))

    def on_unload(self, ui):
        with ui._lock:
            ui.remove_element('ups')

    def on_ui_update(self, ui):
        try:
            capacity = self.ups.capacity()
            charging = self.ups.charging()
            ui.set('ups', "%2i%s" % (capacity, charging))
        except Exception as e:
            logging.error(f"WittyPi UI update failed: {e}")
            ui.set('ups', "ERR")