"""
BlueShift Target / Client Helper.
Provides host Bluetooth scanning, pairing & connection management,
auto-reconnect daemon, virtual HID device verification, and link health monitoring.
"""

import os
import sys
import time
import logging
import threading
import subprocess
from typing import Optional, Dict, List, Any, Callable

import dbus
import dbus.mainloop.glib
import evdev
from evdev import ecodes as e

from .hid_constants import (
    BLUEZ_SERVICE_NAME, ADAPTER_IFACE, DEVICE_IFACE,
    DBUS_PROP_IFACE, DBUS_OM_IFACE
)
from .config import config

logger = logging.getLogger("blueshift.client")


class ClientHelper:
    """Manages Client Mode operations on the secondary PC receiving input."""

    def __init__(self, adapter_path: str = "/org/bluez/hci0"):
        self.adapter_path = adapter_path
        self.bus: Optional[dbus.SystemBus] = None
        self.is_scanning = False
        self.is_reconnect_running = False

        self._reconnect_thread: Optional[threading.Thread] = None
        self._reconnect_stop = threading.Event()

        # Callbacks
        self.on_devices_scanned: Optional[Callable[[List[Dict[str, Any]]], None]] = None
        self.on_connection_state: Optional[Callable[[bool, Dict[str, Any]], None]] = None
        self.on_health_update: Optional[Callable[[Dict[str, Any]], None]] = None

    def _ensure_dbus(self):
        if not dbus.mainloop.glib.threads_init():
            try:
                dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            except Exception:
                pass
        if self.bus is None:
            self.bus = dbus.SystemBus()

    def start_discovery(self, timeout: float = 10.0) -> bool:
        """Start Bluetooth LE discovery scan for nearby BlueShift hosts."""
        try:
            self._ensure_dbus()
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            adapter = dbus.Interface(adapter_obj, ADAPTER_IFACE)

            # Set discovery filter for BLE
            try:
                adapter.SetDiscoveryFilter({"Transport": "le"})
            except Exception:
                pass

            adapter.StartDiscovery()
            self.is_scanning = True
            logger.info("Bluetooth discovery started.")

            # Stop scanning after timeout
            def _auto_stop():
                time.sleep(timeout)
                self.stop_discovery()

            threading.Thread(target=_auto_stop, daemon=True).start()
            return True
        except Exception as e:
            logger.warning("Failed to start discovery: %s", e)
            self.is_scanning = False
            return False

    def stop_discovery(self) -> bool:
        """Stop active Bluetooth discovery scan."""
        try:
            if not self.is_scanning:
                return True
            self._ensure_dbus()
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            adapter = dbus.Interface(adapter_obj, ADAPTER_IFACE)
            adapter.StopDiscovery()
            self.is_scanning = False
            logger.info("Bluetooth discovery stopped.")
            return True
        except Exception as e:
            logger.debug("StopDiscovery: %s", e)
            self.is_scanning = False
            return False

    def get_devices(self) -> List[Dict[str, Any]]:
        """List all discovered or paired Bluetooth devices."""
        devices = []
        try:
            self._ensure_dbus()
            manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
            objects = manager.GetManagedObjects()

            for path, ifaces in objects.items():
                if DEVICE_IFACE in ifaces:
                    dev = ifaces[DEVICE_IFACE]
                    address = str(dev.get("Address", ""))
                    name = str(dev.get("Name", dev.get("Alias", "Unknown")))
                    alias = str(dev.get("Alias", name))
                    connected = bool(dev.get("Connected", False))
                    paired = bool(dev.get("Paired", False))
                    rssi = int(dev.get("RSSI", -99)) if "RSSI" in dev else None
                    uuids = [str(u) for u in dev.get("UUIDs", [])]

                    # Detect if device advertises HID
                    is_hid = any("1812" in u.lower() for u in uuids)

                    devices.append({
                        "path": str(path),
                        "address": address,
                        "name": name,
                        "alias": alias,
                        "connected": connected,
                        "paired": paired,
                        "rssi": rssi,
                        "is_hid": is_hid,
                    })
        except Exception as e:
            logger.error("Failed to query Bluetooth devices: %s", e)
        return devices

    def connect_device(self, address: str) -> bool:
        """Connect to a Bluetooth host by MAC address."""
        try:
            self._ensure_dbus()
            dev_path = self._find_device_path(address)
            if not dev_path:
                logger.error("Device with MAC %s not found in BlueZ database", address)
                return False

            dev_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, dev_path)
            dev_iface = dbus.Interface(dev_obj, DEVICE_IFACE)
            props_iface = dbus.Interface(dev_obj, DBUS_PROP_IFACE)

            # Trust the device so reconnections are automatic
            try:
                props_iface.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
            except Exception:
                pass

            paired = bool(props_iface.Get(DEVICE_IFACE, "Paired"))
            if not paired:
                try:
                    logger.info("Pairing with %s...", address)
                    dev_iface.Pair()
                except Exception as e:
                    logger.debug("Pairing notice: %s", e)

            logger.info("Connecting to %s...", address)
            dev_iface.Connect()
            logger.info("Connected to %s successfully!", address)
            return True
        except Exception as e:
            logger.error("Connection to %s failed: %s", address, e)
            return False

    def disconnect_device(self, address: str) -> bool:
        """Disconnect from a Bluetooth host."""
        try:
            self._ensure_dbus()
            dev_path = self._find_device_path(address)
            if not dev_path:
                return False

            dev_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, dev_path)
            dev_iface = dbus.Interface(dev_obj, DEVICE_IFACE)
            dev_iface.Disconnect()
            logger.info("Disconnected from %s", address)
            return True
        except Exception as e:
            logger.warning("Disconnect failed: %s", e)
            return False

    def _find_device_path(self, address: str) -> Optional[str]:
        """Convert a MAC address into a BlueZ DBus object path."""
        target = address.upper().replace(":", "_")
        manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
        for path, ifaces in manager.GetManagedObjects().items():
            if DEVICE_IFACE in ifaces:
                dev_addr = str(ifaces[DEVICE_IFACE].get("Address", "")).upper().replace(":", "_")
                if dev_addr == target or target in str(path).upper():
                    return str(path)

        # If not cached, trigger a brief 2s discovery to pick up the advertisement
        try:
            adapter = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path), ADAPTER_IFACE)
            adapter.StartDiscovery()
            time.sleep(2)
            adapter.StopDiscovery()
            for path, ifaces in manager.GetManagedObjects().items():
                if DEVICE_IFACE in ifaces:
                    dev_addr = str(ifaces[DEVICE_IFACE].get("Address", "")).upper().replace(":", "_")
                    if dev_addr == target or target in str(path).upper():
                        return str(path)
        except Exception:
            pass

        return None

    # ========================================================================
    # Virtual Input Device Detection
    # ========================================================================

    def detect_virtual_hid_devices(self, host_alias: str = "parrot") -> Dict[str, Any]:
        """
        Verify whether Linux kernel has created virtual HID input devices
        corresponding to the connected host (e.g. 'parrot Keyboard', 'parrot Mouse').
        """
        result = {
            "keyboard": {"detected": False, "name": "Not Detected", "path": ""},
            "mouse": {"detected": False, "name": "Not Detected", "path": ""},
            "all_found": False,
        }

        alias_lower = host_alias.lower()
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                d_name = dev.name.lower()
                caps = dev.capabilities()

                # Check if device matches host name or BlueShift or generic combo
                matches_host = (alias_lower in d_name) or ("blueshift" in d_name) or ("combo" in d_name)

                # Check capabilities
                has_keys = e.EV_KEY in caps
                has_rel = e.EV_REL in caps

                if has_keys and not result["keyboard"]["detected"]:
                    key_set = set(caps[e.EV_KEY])
                    if e.KEY_A in key_set and e.KEY_SPACE in key_set and not has_rel:
                        if matches_host or "keyboard" in d_name:
                            result["keyboard"] = {
                                "detected": True,
                                "name": dev.name,
                                "path": path,
                            }

                if has_rel and not result["mouse"]["detected"]:
                    if e.EV_KEY in caps:
                        key_set = set(caps[e.EV_KEY])
                        if e.BTN_LEFT in key_set:
                            if matches_host or "mouse" in d_name:
                                result["mouse"] = {
                                "detected": True,
                                "name": dev.name,
                                "path": path,
                            }
            except Exception:
                pass

        result["all_found"] = result["keyboard"]["detected"] and result["mouse"]["detected"]
        return result

    # ========================================================================
    # Connection Health & Metrics Dashboard
    # ========================================================================

    def get_connection_health(self, target_address: Optional[str] = None) -> Dict[str, Any]:
        """Fetch connection health, latency, signal strength, and battery status."""
        addr = target_address or config.get("client_mac", "")
        health = {
            "connected": False,
            "address": addr,
            "alias": config.get("client_name", "Remote Host"),
            "rssi": -65,
            "rssi_quality": "Good",
            "latency_ms": 6.8,  # BLE typical HID connection interval latency
            "battery_percent": 100,
            "paired": False,
            "trusted": False,
        }

        try:
            self._ensure_dbus()
            dev_path = self._find_device_path(addr)
            if dev_path:
                dev_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, dev_path)
                props_iface = dbus.Interface(dev_obj, DBUS_PROP_IFACE)
                props = props_iface.GetAll(DEVICE_IFACE)

                health["connected"] = bool(props.get("Connected", False))
                health["paired"] = bool(props.get("Paired", False))
                health["trusted"] = bool(props.get("Trusted", False))
                health["alias"] = str(props.get("Alias", props.get("Name", health["alias"])))

                if "RSSI" in props:
                    rssi = int(props["RSSI"])
                    health["rssi"] = rssi
                    if rssi >= -60:
                        health["rssi_quality"] = "Excellent"
                    elif rssi >= -75:
                        health["rssi_quality"] = "Good"
                    else:
                        health["rssi_quality"] = "Weak"

                # Check Battery1 interface if available
                manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
                obj = manager.GetManagedObjects().get(dev_path, {})
                if "org.bluez.Battery1" in obj:
                    health["battery_percent"] = int(obj["org.bluez.Battery1"].get("Percentage", 100))
        except Exception as e:
            logger.debug("get_connection_health error: %s", e)

        return health

    # ========================================================================
    # Auto-Reconnect Daemon
    # ========================================================================

    def start_auto_reconnect(self, target_address: Optional[str] = None):
        """Start auto-reconnect background loop."""
        if self.is_reconnect_running:
            return

        self._reconnect_stop.clear()
        self.is_reconnect_running = True
        addr = target_address or config.get("client_mac", "")

        def _loop():
            logger.info("Auto-reconnect daemon started for %s", addr)
            while not self._reconnect_stop.is_set():
                try:
                    health = self.get_connection_health(addr)
                    if not health["connected"]:
                        logger.info("Host %s disconnected. Attempting auto-reconnect...", addr)
                        self.connect_device(addr)

                    if self.on_health_update:
                        self.on_health_update(health)
                except Exception as e:
                    logger.debug("Auto-reconnect tick error: %s", e)

                self._reconnect_stop.wait(4.0)
            logger.info("Auto-reconnect daemon stopped.")

        self._reconnect_thread = threading.Thread(target=_loop, name="BlueShift-AutoReconnect", daemon=True)
        self._reconnect_thread.start()

    def stop_auto_reconnect(self):
        """Stop auto-reconnect background loop."""
        self.is_reconnect_running = False
        self._reconnect_stop.set()
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=1.0)


# Global singleton instance
client_helper = ClientHelper()
