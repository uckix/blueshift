"""
BlueShift BlueZ DBus GATT HID Server and LE Advertising Engine.
Registers HID (0x1812), Device Information (0x180A), and Battery (0x180F) services,
and transmits standard 104-key Keyboard and 5-button Mouse reports via BLE notifications.
"""

import sys
import logging
import threading
import time
from typing import Optional, Dict, Any, Callable, List

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

from .hid_constants import (
    UUID_HOGP, UUID_DIS, UUID_BAS,
    UUID_REPORT_MAP, UUID_REPORT, UUID_REPORT_REF,
    UUID_HID_INFO, UUID_HID_CP, UUID_PROTOCOL_MODE,
    UUID_PNP_ID, UUID_MFR_NAME, UUID_MODEL_NUM, UUID_SERIAL_NUM,
    UUID_BATTERY_LEVEL,
    BLUEZ_SERVICE_NAME, ADAPTER_IFACE, DEVICE_IFACE,
    GATT_MGR_IFACE, GATT_SERVICE_IFACE, GATT_CHRC_IFACE, GATT_DESC_IFACE,
    LE_ADV_MGR_IFACE, LE_ADV_IFACE,
    DBUS_PROP_IFACE, DBUS_OM_IFACE,
    REPORT_TYPE_INPUT, REPORT_TYPE_OUTPUT,
    REPORT_ID_KEYBOARD, REPORT_ID_MOUSE,
    REPORT_MAP_BYTES,
)

logger = logging.getLogger("blueshift.ble_server")


# ============================================================================
# DBus GATT Building Blocks
# ============================================================================

class Characteristic(dbus.service.Object):
    """GATT Characteristic representation for BlueZ DBus."""

    def __init__(self, bus: dbus.SystemBus, index: int, uuid: str, flags: List[str], service: "Service"):
        self.path = f"{service.path}/char{index}"
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.descriptors: List["Descriptor"] = []
        self.value = dbus.ByteArray(b"")
        self.notifying = False
        super().__init__(bus, self.path)

    def get_properties(self) -> Dict[str, Any]:
        return {
            GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
                "Descriptors": dbus.Array([d.get_path() for d in self.descriptors], signature="o"),
                "Value": self.value,
            }
        }

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def add_descriptor(self, descriptor: "Descriptor"):
        self.descriptors.append(descriptor)

    def get_descriptors(self) -> List["Descriptor"]:
        return self.descriptors

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> Dict[str, Any]:
        if interface != GATT_CHRC_IFACE:
            raise dbus.exceptions.DBusException("Invalid interface")
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options: Dict[str, Any]) -> dbus.ByteArray:
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value: dbus.ByteArray, options: Dict[str, Any]):
        self.value = value

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True
        logger.debug("Notifications enabled on %s", self.path)

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False
        logger.debug("Notifications disabled on %s", self.path)

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface: str, changed: Dict[str, Any], invalidated: List[str]):
        pass

    def notify_value(self, new_value: bytes):
        """Update value and emit PropertiesChanged DBus signal."""
        byte_arr = dbus.ByteArray(new_value)
        self.value = byte_arr
        self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": byte_arr}, [])


class Descriptor(dbus.service.Object):
    """GATT Descriptor representation for BlueZ DBus."""

    def __init__(self, bus: dbus.SystemBus, index: int, uuid: str, flags: List[str], characteristic: Characteristic):
        self.path = f"{characteristic.path}/desc{index}"
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.chrc = characteristic
        self.value = dbus.ByteArray(b"")
        super().__init__(bus, self.path)

    def get_properties(self) -> Dict[str, Any]:
        return {
            GATT_DESC_IFACE: {
                "Characteristic": self.chrc.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
                "Value": self.value,
            }
        }

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> Dict[str, Any]:
        if interface != GATT_DESC_IFACE:
            raise dbus.exceptions.DBusException("Invalid interface")
        return self.get_properties()[GATT_DESC_IFACE]

    @dbus.service.method(GATT_DESC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options: Dict[str, Any]) -> dbus.ByteArray:
        return self.value


class Service(dbus.service.Object):
    """GATT Service representation for BlueZ DBus."""

    def __init__(self, bus: dbus.SystemBus, index: int, uuid: str, primary: bool):
        self.path = f"/org/bluez/blueshift/service{index}"
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics: List[Characteristic] = []
        super().__init__(bus, self.path)

    def get_properties(self) -> Dict[str, Any]:
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array([c.get_path() for c in self.characteristics], signature="o"),
            }
        }

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic: Characteristic):
        self.characteristics.append(characteristic)

    def get_characteristics(self) -> List[Characteristic]:
        return self.characteristics

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> Dict[str, Any]:
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException("Invalid interface")
        return self.get_properties()[GATT_SERVICE_IFACE]


class Application(dbus.service.Object):
    """Top-level GATT Application implementing org.freedesktop.DBus.ObjectManager."""

    def __init__(self, bus: dbus.SystemBus):
        self.path = "/org/bluez/blueshift"
        self.services: List[Service] = []
        super().__init__(bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def add_service(self, service: Service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self) -> Dict[str, Any]:
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for chrc in service.get_characteristics():
                response[chrc.get_path()] = chrc.get_properties()
                for desc in chrc.get_descriptors():
                    response[desc.get_path()] = desc.get_properties()
        return response


class Advertisement(dbus.service.Object):
    """BlueZ LE Advertisement object."""

    def __init__(self, bus: dbus.SystemBus, index: int, local_name: str = "BlueShift"):
        self.path = f"/org/bluez/blueshift/adv{index}"
        self.bus = bus
        self.local_name = local_name
        self.service_uuids = [UUID_HOGP, UUID_DIS, UUID_BAS]
        super().__init__(bus, self.path)

    def get_properties(self) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "Type": "peripheral",
            "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
            "LocalName": dbus.String(self.local_name),
            "Appearance": dbus.UInt16(0x03C0),  # Generic Human Interface Device
            "Discoverable": dbus.Boolean(True),
            "Includes": dbus.Array(["tx-power", "appearance", "local-name"], signature="s"),
        }
        return {LE_ADV_IFACE: props}

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> Dict[str, Any]:
        if interface != LE_ADV_IFACE:
            raise dbus.exceptions.DBusException("Invalid interface")
        return self.get_properties()[LE_ADV_IFACE]

    @dbus.service.method(LE_ADV_IFACE)
    def Release(self):
        logger.info("Advertisement %s released by BlueZ", self.path)


# ============================================================================
# Specific Characteristics for HOGP, DIS, and Battery
# ============================================================================

class ReportReferenceDescriptor(Descriptor):
    """Report Reference Descriptor (UUID 0x2908): associates report ID & type."""

    def __init__(self, bus: dbus.SystemBus, index: int, characteristic: Characteristic, report_id: int, report_type: int):
        super().__init__(bus, index, UUID_REPORT_REF, ["read"], characteristic)
        self.value = dbus.ByteArray(bytes([report_id, report_type]))


class ProtocolModeCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_PROTOCOL_MODE, ["read", "write-without-response"], service)
        self.value = dbus.ByteArray(bytes([0x01]))  # 0x01 = Report Protocol Mode


class ReportMapCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_REPORT_MAP, ["read"], service)
        self.value = dbus.ByteArray(REPORT_MAP_BYTES)


class HidInformationCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_HID_INFO, ["read"], service)
        # bcdHID (0x0111), bCountryCode (0x00), Flags (0x02: NormallyConnectable)
        self.value = dbus.ByteArray(bytes([0x11, 0x01, 0x00, 0x02]))


class HidControlPointCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_HID_CP, ["write-without-response"], service)
        self.value = dbus.ByteArray(bytes([0x00]))


class KeyboardInputReportCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_REPORT, ["read", "notify"], service)
        self.value = dbus.ByteArray(bytes([0] * 8))
        self.add_descriptor(ReportReferenceDescriptor(bus, 0, self, REPORT_ID_KEYBOARD, REPORT_TYPE_INPUT))


class MouseInputReportCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_REPORT, ["read", "notify"], service)
        self.value = dbus.ByteArray(bytes([0] * 7))
        self.add_descriptor(ReportReferenceDescriptor(bus, 0, self, REPORT_ID_MOUSE, REPORT_TYPE_INPUT))


class KeyboardOutputReportCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_REPORT, ["read", "write", "write-without-response"], service)
        self.value = dbus.ByteArray(bytes([0x00]))
        self.add_descriptor(ReportReferenceDescriptor(bus, 0, self, REPORT_ID_KEYBOARD, REPORT_TYPE_OUTPUT))


class BatteryLevelCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_BATTERY_LEVEL, ["read", "notify"], service)
        self.value = dbus.ByteArray(bytes([100]))


# ============================================================================
# BlueShift BLE Server Manager
# ============================================================================

class BleServer:
    """Complete BlueShift BLE HID Server and Manager."""

    def __init__(self, adapter_path: str = "/org/bluez/hci0", local_name: str = "BlueShift"):
        self.adapter_path = adapter_path
        self.local_name = local_name
        self.is_running = False
        self.connected_device: Optional[Dict[str, Any]] = None

        # Stats
        self.packets_sent_kb = 0
        self.packets_sent_mouse = 0
        self.last_event_time = 0.0

        # Callbacks
        self.on_connection_changed: Optional[Callable[[bool, Optional[Dict[str, Any]]], None]] = None
        self.on_stats_updated: Optional[Callable[[int, int], None]] = None

        # Internal DBus objects
        self.bus: Optional[dbus.SystemBus] = None
        self.app: Optional[Application] = None
        self.adv: Optional[Advertisement] = None
        self.kb_char: Optional[KeyboardInputReportCharacteristic] = None
        self.mouse_char: Optional[MouseInputReportCharacteristic] = None
        self.battery_char: Optional[BatteryLevelCharacteristic] = None

        # GLib mainloop thread
        self._loop: Optional[GLib.MainLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

    def _ensure_dbus(self):
        """Initialize DBus GLib mainloop if not already setup."""
        if not dbus.mainloop.glib.threads_init():
            try:
                dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            except Exception:
                pass
        if self.bus is None:
            self.bus = dbus.SystemBus()

    def get_adapter_info(self) -> Dict[str, Any]:
        """Fetch local Bluetooth adapter details."""
        try:
            self._ensure_dbus()
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props_iface = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
            props = props_iface.GetAll(ADAPTER_IFACE)
            return {
                "path": self.adapter_path,
                "address": str(props.get("Address", "Unknown")),
                "name": str(props.get("Name", "BlueShift")),
                "alias": str(props.get("Alias", "BlueShift")),
                "powered": bool(props.get("Powered", False)),
            }
        except Exception as e:
            logger.warning("Could not read adapter properties: %s", e)
            return {
                "path": self.adapter_path,
                "address": "Unknown",
                "name": "Bluetooth Adapter",
                "alias": "parrot",
                "powered": False,
            }

    def start(self) -> bool:
        """Start the BlueZ GATT HID application and LE Advertisement."""
        if self.is_running:
            logger.info("BLE Server is already active.")
            return True

        logger.info("Starting BlueShift BLE GATT HID Server...")
        try:
            self._ensure_dbus()

            # 1. Start background GLib main loop thread
            self._loop = GLib.MainLoop()
            self._loop_thread = threading.Thread(target=self._loop.run, name="BlueShift-GLib", daemon=True)
            self._loop_thread.start()

            # 2. Construct GATT Application & Services
            self.app = Application(self.bus)

            # --- HID Service (0x1812) ---
            hid_service = Service(self.bus, 0, UUID_HOGP, True)
            hid_service.add_characteristic(ProtocolModeCharacteristic(self.bus, 0, hid_service))
            hid_service.add_characteristic(ReportMapCharacteristic(self.bus, 1, hid_service))
            hid_service.add_characteristic(HidInformationCharacteristic(self.bus, 2, hid_service))
            hid_service.add_characteristic(HidControlPointCharacteristic(self.bus, 3, hid_service))

            self.kb_char = KeyboardInputReportCharacteristic(self.bus, 4, hid_service)
            hid_service.add_characteristic(self.kb_char)

            self.mouse_char = MouseInputReportCharacteristic(self.bus, 5, hid_service)
            hid_service.add_characteristic(self.mouse_char)

            hid_service.add_characteristic(KeyboardOutputReportCharacteristic(self.bus, 6, hid_service))
            self.app.add_service(hid_service)

            # --- Device Information Service (0x180A) ---
            dis_service = Service(self.bus, 1, UUID_DIS, True)
            pnp_char = Characteristic(self.bus, 0, UUID_PNP_ID, ["read"], dis_service)
            pnp_char.value = dbus.ByteArray(bytes([0x02, 0x5e, 0x04, 0x01, 0x00, 0x01, 0x00]))
            dis_service.add_characteristic(pnp_char)

            mfr_char = Characteristic(self.bus, 1, UUID_MFR_NAME, ["read"], dis_service)
            mfr_char.value = dbus.ByteArray(b"BlueShift")
            dis_service.add_characteristic(mfr_char)

            model_char = Characteristic(self.bus, 2, UUID_MODEL_NUM, ["read"], dis_service)
            model_char.value = dbus.ByteArray(b"BlueShift BLE KVM")
            dis_service.add_characteristic(model_char)

            serial_char = Characteristic(self.bus, 3, UUID_SERIAL_NUM, ["read"], dis_service)
            serial_char.value = dbus.ByteArray(b"BS-2026")
            dis_service.add_characteristic(serial_char)
            self.app.add_service(dis_service)

            # --- Battery Service (0x180F) ---
            bas_service = Service(self.bus, 2, UUID_BAS, True)
            self.battery_char = BatteryLevelCharacteristic(self.bus, 0, bas_service)
            bas_service.add_characteristic(self.battery_char)
            self.app.add_service(bas_service)

            # 3. Register Application with BlueZ
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            gatt_mgr = dbus.Interface(adapter_obj, GATT_MGR_IFACE)

            reg_event = threading.Event()
            reg_error: List[str] = []

            def on_gatt_ok():
                logger.info("GATT application registered with BlueZ successfully")
                reg_event.set()

            def on_gatt_err(err):
                logger.error("Failed to register GATT application: %s", err)
                reg_error.append(str(err))
                reg_event.set()

            gatt_mgr.RegisterApplication(
                self.app.get_path(),
                {},
                reply_handler=on_gatt_ok,
                error_handler=on_gatt_err,
            )
            reg_event.wait(timeout=3.0)

            # 4. Construct & Register LE Advertisement
            self.adv = Advertisement(self.bus, 0, self.local_name)
            adv_mgr = dbus.Interface(adapter_obj, LE_ADV_MGR_IFACE)

            adv_event = threading.Event()

            def on_adv_ok():
                logger.info("LE Advertisement registered with BlueZ successfully")
                adv_event.set()

            def on_adv_err(err):
                logger.warning("Failed to register LE Advertisement: %s", err)
                adv_event.set()

            adv_mgr.RegisterAdvertisement(
                self.adv.get_path(),
                {},
                reply_handler=on_adv_ok,
                error_handler=on_adv_err,
            )
            adv_event.wait(timeout=3.0)

            # 5. Attach BlueZ Device connection monitor
            self._setup_connection_monitoring()

            self.is_running = True
            logger.info("BlueShift BLE Server is RUNNING.")
            return True

        except Exception as e:
            logger.exception("Error starting BlueShift BLE Server: %s", e)
            self.stop()
            return False

    def stop(self):
        """Unregister services, release advertisement, and shutdown GLib thread."""
        logger.info("Stopping BlueShift BLE Server...")
        self.is_running = False

        if self.bus and self.app:
            try:
                adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
                gatt_mgr = dbus.Interface(adapter_obj, GATT_MGR_IFACE)
                gatt_mgr.UnregisterApplication(self.app.get_path())
            except Exception as e:
                logger.debug("UnregisterApplication: %s", e)

        if self.bus and self.adv:
            try:
                adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
                adv_mgr = dbus.Interface(adapter_obj, LE_ADV_MGR_IFACE)
                adv_mgr.UnregisterAdvertisement(self.adv.get_path())
            except Exception as e:
                logger.debug("UnregisterAdvertisement: %s", e)

        if self._loop and self._loop.is_running():
            self._loop.quit()

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)

        self.app = None
        self.adv = None
        self.kb_char = None
        self.mouse_char = None
        logger.info("BlueShift BLE Server stopped.")

    def _setup_connection_monitoring(self):
        """Monitor connected devices and signal changes."""
        try:
            # Query existing devices
            manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
            objects = manager.GetManagedObjects()
            for path, ifaces in objects.items():
                if DEVICE_IFACE in ifaces:
                    dev = ifaces[DEVICE_IFACE]
                    if bool(dev.get("Connected", False)):
                        self.connected_device = {
                            "path": str(path),
                            "address": str(dev.get("Address", "")),
                            "name": str(dev.get("Name", "Remote Peer")),
                            "alias": str(dev.get("Alias", "Remote Peer")),
                            "paired": bool(dev.get("Paired", False)),
                            "rssi": int(dev.get("RSSI", -65)) if "RSSI" in dev else -60,
                        }
                        logger.info("Existing client connected: %s (%s)", self.connected_device["alias"], self.connected_device["address"])
                        if self.on_connection_changed:
                            self.on_connection_changed(True, self.connected_device)
                        break

            # Listen for device connection signals
            def on_prop_changed(iface, changed, invalidated, path=None):
                if iface == DEVICE_IFACE and "Connected" in changed:
                    connected = bool(changed["Connected"])
                    logger.info("Device %s connection state changed: %s", path, connected)
                    if connected:
                        dev_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, path)
                        dev_props = dbus.Interface(dev_obj, DBUS_PROP_IFACE).GetAll(DEVICE_IFACE)
                        self.connected_device = {
                            "path": str(path),
                            "address": str(dev_props.get("Address", "")),
                            "name": str(dev_props.get("Name", "Remote Peer")),
                            "alias": str(dev_props.get("Alias", "Remote Peer")),
                            "paired": bool(dev_props.get("Paired", False)),
                            "rssi": int(dev_props.get("RSSI", -65)) if "RSSI" in dev_props else -60,
                        }
                    else:
                        self.connected_device = None

                    if self.on_connection_changed:
                        self.on_connection_changed(connected, self.connected_device)

            self.bus.add_signal_receiver(
                on_prop_changed,
                signal_name="PropertiesChanged",
                dbus_interface=DBUS_PROP_IFACE,
                arg0=DEVICE_IFACE,
                path_keyword="path",
            )
        except Exception as e:
            logger.warning("Error setting up connection monitor: %s", e)

    # ========================================================================
    # HID Report Transmission
    # ========================================================================

    def send_keyboard_report(self, modifiers: int, keys: List[int]):
        """Send an 8-byte HID keyboard report to subscribed BLE clients."""
        if not self.kb_char:
            return

        # Up to 6 concurrent keycodes
        key_slots = (keys[:6] + [0] * (6 - len(keys[:6])))
        report = bytes([modifiers & 0xFF, 0x00] + [k & 0xFF for k in key_slots])
        try:
            self.kb_char.notify_value(report)
            self.packets_sent_kb += 1
            self.last_event_time = time.time()
            if self.on_stats_updated:
                self.on_stats_updated(self.packets_sent_kb, self.packets_sent_mouse)
        except Exception as e:
            logger.debug("Failed to send keyboard report: %s", e)

    def send_mouse_report(self, buttons: int, dx: int, dy: int, wheel: int = 0, hwheel: int = 0):
        """Send a 7-byte frame-synced HID mouse report to subscribed BLE clients."""
        if not self.mouse_char:
            return

        # Clamp relative movements to signed 16-bit range (-32767 to 32767)
        dx_clamped = max(-32767, min(32767, int(dx)))
        dy_clamped = max(-32767, min(32767, int(dy)))
        wheel_clamped = max(-127, min(127, int(wheel)))
        hwheel_clamped = max(-127, min(127, int(hwheel)))

        dx_bytes = dx_clamped.to_bytes(2, byteorder="little", signed=True)
        dy_bytes = dy_clamped.to_bytes(2, byteorder="little", signed=True)
        wheel_byte = wheel_clamped.to_bytes(1, byteorder="little", signed=True)
        hwheel_byte = hwheel_clamped.to_bytes(1, byteorder="little", signed=True)

        report = bytes([buttons & 0x1F]) + dx_bytes + dy_bytes + wheel_byte + hwheel_byte
        try:
            self.mouse_char.notify_value(report)
            self.packets_sent_mouse += 1
            self.last_event_time = time.time()
            if self.on_stats_updated:
                self.on_stats_updated(self.packets_sent_kb, self.packets_sent_mouse)
        except Exception as e:
            logger.debug("Failed to send mouse report: %s", e)

    def send_battery_level(self, level: int):
        """Update and notify battery percentage (0-100)."""
        if not self.battery_char:
            return
        level_byte = bytes([max(0, min(100, int(level)))])
        try:
            self.battery_char.notify_value(level_byte)
        except Exception as e:
            logger.debug("Failed to notify battery level: %s", e)


# Global singleton instance
ble_server = BleServer()
