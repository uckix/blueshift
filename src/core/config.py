"""
BlueShift Configuration Manager
Handles persistent JSON settings in ~/.config/blueshift/config.json
"""

import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, Callable, List

logger = logging.getLogger("blueshift.config")

CONFIG_DIR = Path.home() / ".config" / "blueshift"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "role": "server",                   # 'server' or 'client'
    "host_name": "Parrot",              # Host PC label
    "client_name": "ArchLab",           # Client PC label
    "client_mac": "90:E8:68:95:76:DC",  # Target client Bluetooth MAC
    "keyboard_device": "",              # Event node or empty for auto-detect
    "mouse_device": "",                 # Event node or empty for auto-detect
    "hotkey": "scroll_lock",            # 'scroll_lock', 'ctrl_alt_s', 'right_alt'
    "auto_reconnect": True,             # Client mode auto-reconnection
    "notifications_enabled": True,      # Show desktop notifications
    "start_on_boot": False,             # Systemd / autostart enabled
    "start_minimized": False,           # Launch directly to tray
    "mouse_sensitivity": 1.0,           # Sensitivity factor (0.25 - 3.0)
    "server_autostart": True,           # Automatically start BLE server on app open
    "battery_level": 100,               # Simulated or reported battery %
}


class ConfigManager:
    """Manages application configuration with disk persistence and event dispatch."""

    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = Path(config_path)
        self._data: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._listeners: List[Callable[[str, Any], None]] = []
        self.load()

    def load(self) -> None:
        """Load settings from JSON file or create with defaults."""
        try:
            if self.config_path.is_file():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self._data.update(loaded)
                    logger.debug("Loaded config from %s", self.config_path)
            else:
                self.save()
        except Exception as e:
            logger.warning("Failed to load config, falling back to defaults: %s", e)
            self._data = dict(DEFAULT_CONFIG)

    def save(self) -> None:
        """Atomically persist current configuration to JSON file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.config_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            tmp_path.replace(self.config_path)
            logger.debug("Saved config to %s", self.config_path)
        except Exception as e:
            logger.error("Failed to save config to %s: %s", self.config_path, e)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        """Set a configuration value, optionally triggering listeners and disk save."""
        old_val = self._data.get(key)
        if old_val != value:
            self._data[key] = value
            for callback in self._listeners:
                try:
                    callback(key, value)
                except Exception as err:
                    logger.exception("Error in config listener callback: %s", err)
            if save:
                self.save()

    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        """Register a callback for configuration changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)


# Global singleton instance
config = ConfigManager()
