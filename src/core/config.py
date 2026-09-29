"""
BlueShift Configuration Manager
Persistent JSON settings in ~/.config/blueshift/config.json
"""

import json
import socket
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("blueshift.config")

CONFIG_DIR = Path.home() / ".config" / "blueshift"
CONFIG_FILE = CONFIG_DIR / "config.json"

ROLE_SERVER = "server"   # this PC shares its keyboard & mouse
ROLE_CLIENT = "client"   # this PC receives them

HOTKEYS = {
    "ctrl_alt_s": "Ctrl + Alt + S",
    "scroll_lock": "Scroll Lock",
    "pause": "Pause / Break",
    "right_alt": "Right Alt",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "role": ROLE_SERVER,
    "host_name": socket.gethostname(),  # the PC that owns the keyboard
    "client_name": "Other PC",          # the PC that receives input
    "host_mac": "",                     # Bluetooth MAC of the host (used by the client)
    "client_mac": "",                   # Bluetooth MAC of the client (informational on host)
    "hotkey": "ctrl_alt_s",
    "notifications_enabled": True,
    "mouse_sensitivity": 1.0,
    "auto_reconnect": True,
    "le_paired": False,                 # client: an LE bond with the host exists
    "exclude_devices": ["yubikey", "onlykey", "nitrokey", "solokey", "smartcard", "blueshift"],
}

_ROLE_ALIASES = {"host": ROLE_SERVER, "target": ROLE_CLIENT}


class ConfigManager:
    """Loads/saves configuration; unknown keys on disk are preserved."""

    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = Path(config_path)
        self._data: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        self._data = dict(DEFAULT_CONFIG)
        try:
            if self.config_path.is_file():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._data.update(loaded)
            else:
                self.save()
        except (OSError, ValueError) as e:
            logger.warning("Config unreadable (%s), using defaults.", e)
        role = self._data.get("role")
        self._data["role"] = _ROLE_ALIASES.get(role, role)
        if self._data["role"] not in (ROLE_SERVER, ROLE_CLIENT):
            self._data["role"] = ROLE_SERVER
        if self._data.get("hotkey") not in HOTKEYS:
            self._data["hotkey"] = DEFAULT_CONFIG["hotkey"]

    def save(self) -> None:
        """Atomically persist configuration."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.config_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            tmp_path.replace(self.config_path)
        except OSError as e:
            logger.error("Failed to save config to %s: %s", self.config_path, e)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        if self._data.get(key) != value:
            self._data[key] = value
            if save:
                self.save()

    def update(self, values: Dict[str, Any]) -> None:
        self._data.update(values)
        self.save()

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    @property
    def peer_name(self) -> str:
        return self.get("client_name") if self.get("role") == ROLE_SERVER else self.get("host_name")


# Global singleton instance
config = ConfigManager()
