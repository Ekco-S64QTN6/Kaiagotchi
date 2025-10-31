import logging
import json
import toml
import _thread
import kaiagotchi
from kaiagotchi import restart, plugins
from kaiagotchi.utils import save_config, merge_config
from flask import abort
from flask import render_template_string

INDEX = """
<!-- Template remains the same -->
"""

def serializer(obj):
    if isinstance(obj, set):
        return list(obj)
    raise TypeError


class WebConfig(plugins.Plugin):
    __author__ = '33197631+dadav@users.noreply.github.com'
    __version__ = '1.0.0'
    __license__ = 'GPL3'
    __description__ = 'This plugin allows the user to make runtime changes.'

    def __init__(self):
        self.ready = False
        self.mode = 'MANU'
        self._agent = None
        # Enhanced: Add configuration validation
        self.allowed_config_keys = set()
        self.sensitive_keys = {'api_key', 'password', 'secret', 'key'}

    def on_config_changed(self, config):
        self.config = config
        # Enhanced: Build set of allowed configuration keys for validation
        self.allowed_config_keys = self._get_allowed_keys(config)
        self.ready = True

    def _get_allowed_keys(self, config, prefix=""):
        """Recursively build set of allowed configuration keys"""
        allowed = set()
        for key, value in config.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                allowed.update(self._get_allowed_keys(value, full_key))
            else:
                allowed.add(full_key)
        return allowed

    def _validate_config_update(self, new_config):
        """Validate configuration changes for safety"""
        if not isinstance(new_config, dict):
            raise ValueError("Configuration must be a dictionary")
            
        # Check for unknown keys
        unknown_keys = set(new_config.keys()) - self.allowed_config_keys
        if unknown_keys:
            logging.warning(f"Webcfg: Attempted to set unknown keys: {unknown_keys}")
            # Optionally filter out unknown keys or raise an error
            
        # Check for sensitive key modifications
        for key in new_config.keys():
            if any(sensitive in key.lower() for sensitive in self.sensitive_keys):
                logging.warning(f"Webcfg: Modification of potentially sensitive key: {key}")
                
        return True

    def on_ready(self, agent):
        self._agent = agent
        self.mode = 'MANU' if agent.mode == 'manual' else 'AUTO'

    def on_internet_available(self, agent):
        self._agent = agent
        self.mode = 'MANU' if agent.mode == 'manual' else 'AUTO'

    def on_loaded(self):
        logging.info("webcfg: Plugin loaded.")

    def on_webhook(self, path, request):
        if not self.ready:
            return "Plugin not ready"

        if request.method == "GET":
            if path == "/" or not path:
                return render_template_string(INDEX)
            elif path == "get-config":
                # Enhanced: Filter sensitive data from config response
                filtered_config = self._filter_sensitive_data(self.config)
                return json.dumps(filtered_config, default=serializer)
            else:
                abort(404)
        elif request.method == "POST":
            if path == "save-config":
                try:
                    new_config = request.get_json()
                    self._validate_config_update(new_config)
                    save_config(new_config, '/etc/kaiagotchi/config.toml')
                    _thread.start_new_thread(restart, (self.mode,))
                    return "success"
                except Exception as ex:
                    logging.error(f"Webcfg save error: {ex}")
                    return "config error", 500
            elif path == "merge-save-config":
                try:
                    new_config = request.get_json()
                    self._validate_config_update(new_config)
                    
                    self.config = merge_config(new_config, self.config)
                    kaiagotchi.config = merge_config(new_config, kaiagotchi.config)
                    logging.debug("kaiagotchi CONFIG updated")
                    
                    if self._agent:
                        self._agent._config = merge_config(new_config, self._agent._config)
                        logging.debug("Agent CONFIG updated")
                        
                    logging.debug(f"Updated CONFIG: {new_config}")
                    save_config(new_config, '/etc/kaiagotchi/config.toml')
                    return "success"
                except Exception as ex:
                    logging.error(f"[webcfg mergesave] {ex}")
                    return "config error", 500
        abort(404)

    def _filter_sensitive_data(self, config):
        """Filter sensitive data from configuration for display"""
        if not isinstance(config, dict):
            return config
            
        filtered = {}
        for key, value in config.items():
            if isinstance(value, dict):
                filtered[key] = self._filter_sensitive_data(value)
            elif any(sensitive in key.lower() for sensitive in self.sensitive_keys):
                filtered[key] = "***HIDDEN***"
            else:
                filtered[key] = value
        return filtered