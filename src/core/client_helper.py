"""
BlueShift target side: keeps this PC linked to the host's BLE keyboard/mouse.

The two PCs are usually already bonded over *classic* Bluetooth. BlueZ then always
picks the classic bearer for Connect(), which never carries HID-over-GATT, so the
keyboard/mouse never appear. We therefore pair over LE explicitly (scan with an LE
transport filter, then Pair(): with a classic bond present BlueZ bonds the LE bearer)
and let BlueZ's HOG plugin auto-reconnect from then on.
"""

import glob
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any

import dbus
import dbus.service

from .hid_constants import BLUEZ_SERVICE_NAME, ADAPTER_IFACE, DEVICE_IFACE, DBUS_PROP_IFACE, DBUS_OM_IFACE
from .config import config

logger = logging.getLogger("blueshift.client")

AGENT_IFACE = "org.bluez.Agent1"
AGENT_MGR_IFACE = "org.bluez.AgentManager1"
AGENT_PATH = "/org/bluez/blueshift/agent"

STATE_NO_HOST = "no_host"
STATE_IDLE = "idle"
STATE_SEARCHING = "searching"
STATE_PAIRING = "pairing"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"

RETRY_INTERVAL = 20.0  # seconds between automatic reconnect attempts


def _mac_to_path_part(mac: str) -> str:
    return "dev_" + mac.upper().replace(":", "_")


def host_input_devices(host_mac: str) -> List[str]:
    """Names of input devices the kernel created for the host's BLE HID link."""
    if not host_mac:
        return []
    found = []
    for uniq_file in glob.glob("/sys/class/input/input*/uniq"):
        try:
            if Path(uniq_file).read_text().strip().upper() == host_mac.upper():
                found.append(Path(uniq_file).with_name("name").read_text().strip())
        except OSError:
            pass
    return found


def known_devices() -> List[Dict[str, Any]]:
    """Bluetooth devices BlueZ knows about (for the settings picker)."""
    from .bus import get_bus
    devices = []
    try:
        objects = dbus.Interface(get_bus().get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE).GetManagedObjects()
    except dbus.exceptions.DBusException as err:
        logger.debug("Cannot list devices: %s", err)
        return devices
    for _path, ifaces in objects.items():
        dev = ifaces.get(DEVICE_IFACE)
        if dev is None:
            continue
        devices.append({
            "address": str(dev.get("Address", "")),
            "name": str(dev.get("Alias", dev.get("Name", ""))),
            "paired": bool(dev.get("Paired", False)),
            "connected": bool(dev.get("Connected", False)),
            "icon": str(dev.get("Icon", "")),
        })
    devices.sort(key=lambda d: (d["icon"] != "computer", not d["paired"], d["name"].lower()))
    return devices


class PairingAgent(dbus.service.Object):
    """Auto-accepts pairing, but only with the configured host."""

    def _check(self, device):
        mac = config.get("host_mac", "")
        if not mac or not str(device).endswith(_mac_to_path_part(mac)):
            raise dbus.exceptions.DBusException("org.bluez.Error.Rejected", "Not the BlueShift host")

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        self._check(device)

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        self._check(device)
        return "0000"

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        self._check(device)
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        self._check(device)

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        self._check(device)

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self):
        pass


class ClientLink:
    """Background worker that gets and keeps the host's keyboard/mouse on this PC."""

    def __init__(self, adapter_path: str = "/org/bluez/hci0"):
        self.adapter_path = adapter_path
        self.bus = None
        self.state = STATE_IDLE
        self.message = ""
        self.devices: List[str] = []
        self._agent: Optional[PairingAgent] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._repair_requested = False
        self._last_attempt = 0.0

    # ------------------------------------------------------------------ lifecycle

    def start(self):
        from .bus import get_bus
        self.bus = get_bus()
        self._register_agent()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="BlueShift-Client", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._kick.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def connect_now(self, repair: bool = False):
        self._repair_requested = self._repair_requested or repair
        self._last_attempt = 0.0
        self._kick.set()

    def status(self) -> Dict[str, Any]:
        return {"state": self.state, "message": self.message, "devices": self.devices}

    # ------------------------------------------------------------------ internals

    def _register_agent(self):
        try:
            if self._agent is None:
                self._agent = PairingAgent(self.bus, AGENT_PATH)
            mgr = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez"), AGENT_MGR_IFACE)
            mgr.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
        except dbus.exceptions.DBusException as err:
            if "AlreadyExists" not in str(err):
                logger.warning("Could not register pairing agent: %s", err)

    def _set(self, state: str, message: str = ""):
        if (state, message) != (self.state, self.message):
            logger.info("Link: %s %s", state, message)
        self.state, self.message = state, message

    def _loop(self):
        while not self._stop.is_set():
            host = config.get("host_mac", "")
            self.devices = host_input_devices(host)
            if not host:
                self._set(STATE_NO_HOST, "Choose the host PC in Settings")
            elif self.devices and not self._repair_requested:
                if not config.get("le_paired"):
                    config.set("le_paired", True)
                self._set(STATE_CONNECTED)
            else:
                due = time.monotonic() - self._last_attempt >= RETRY_INTERVAL
                if self._repair_requested or (due and config.get("auto_reconnect", True)):
                    self._last_attempt = time.monotonic()
                    repair, self._repair_requested = self._repair_requested, False
                    try:
                        self._attempt(host, repair)
                    except dbus.exceptions.DBusException as err:
                        self._set(STATE_IDLE, f"Bluetooth error: {err.get_dbus_message() or err}")
                    self._last_attempt = time.monotonic()
                elif self.state in (STATE_CONNECTED, STATE_NO_HOST):
                    self._set(STATE_IDLE, "Waiting for the host…")
            self._kick.wait(2.0)
            self._kick.clear()

    def _adapter(self):
        return self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)

    def _device_path(self, mac: str) -> str:
        return f"{self.adapter_path}/{_mac_to_path_part(mac)}"

    def _device_props(self, mac: str) -> Optional[Dict[str, Any]]:
        try:
            return dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, self._device_path(mac)),
                                  DBUS_PROP_IFACE).GetAll(DEVICE_IFACE)
        except dbus.exceptions.DBusException:
            return None

    def _wait_for_input(self, mac: str, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._stop.is_set():
            self.devices = host_input_devices(mac)
            if self.devices:
                return True
            time.sleep(0.5)
        return False

    def _scan_le(self, mac: str, seconds: float = 12.0) -> bool:
        """LE-only discovery until the host's advertisement is seen."""
        adapter = dbus.Interface(self._adapter(), ADAPTER_IFACE)
        try:
            adapter.SetDiscoveryFilter({"Transport": "le", "DuplicateData": dbus.Boolean(True)})
        except dbus.exceptions.DBusException as err:
            logger.debug("SetDiscoveryFilter: %s", err)
        started = False
        try:
            adapter.StartDiscovery()
            started = True
        except dbus.exceptions.DBusException as err:
            if "InProgress" not in str(err):
                raise
        try:
            end = time.monotonic() + seconds
            while time.monotonic() < end and not self._stop.is_set():
                props = self._device_props(mac)
                if props is not None and "RSSI" in props:
                    return True
                time.sleep(0.5)
            return False
        finally:
            if started:
                try:
                    adapter.StopDiscovery()
                except dbus.exceptions.DBusException:
                    pass

    def _attempt(self, mac: str, repair: bool):
        name = config.get("host_name") or mac
        props = dbus.Interface(self._adapter(), DBUS_PROP_IFACE)
        if not bool(props.Get(ADAPTER_IFACE, "Powered")):
            props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))

        if repair:
            self._set(STATE_SEARCHING, f"Forgetting old pairing with {name}…")
            try:
                dbus.Interface(self._adapter(), ADAPTER_IFACE).RemoveDevice(self._device_path(mac))
            except dbus.exceptions.DBusException:
                pass
            config.set("le_paired", False)
            time.sleep(1.0)

        self._set(STATE_SEARCHING, f"Looking for {name}…")
        if not self._scan_le(mac):
            self._set(STATE_IDLE, f"Can't see {name}. Is BlueShift running there, with Bluetooth on?")
            return

        dev_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self._device_path(mac))
        dev = dbus.Interface(dev_obj, DEVICE_IFACE)
        dbus.Interface(dev_obj, DBUS_PROP_IFACE).Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))

        if not config.get("le_paired"):
            self._set(STATE_PAIRING, f"Pairing with {name}… accept the request on {name} if asked")
            try:
                dev.Pair(timeout=60)
            except dbus.exceptions.DBusException as err:
                if "AlreadyExists" not in (err.get_dbus_name() or ""):
                    self._set(STATE_IDLE, f"Pairing failed ({err.get_dbus_message()}). "
                                          f"Accept the pairing prompt on {name}, or press Re-pair.")
                    return

        self._set(STATE_CONNECTING, f"Connecting to {name}…")
        try:
            dev.Connect(timeout=30)
        except dbus.exceptions.DBusException as err:
            logger.debug("Connect: %s", err)
        if self._wait_for_input(mac, 15.0):
            config.set("le_paired", True)
            self._set(STATE_CONNECTED)
        else:
            self._set(STATE_IDLE, f"Linked to {name} but no keyboard appeared yet. Press Re-pair if this persists.")


# Global singleton instance
client_link = ClientLink()
