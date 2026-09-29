"""
BlueShift BlueZ DBus GATT HID Server and LE Advertising Engine.
Registers HID (0x1812), Device Information (0x180A), and Battery (0x180F) services,
and transmits standard 104-key Keyboard and 5-button Mouse reports via BLE notifications.
"""

import logging
import threading
from typing import Optional, Dict, Any, Callable, List

import dbus
import dbus.service

from .hid_constants import (
    UUID_HOGP, UUID_DIS, UUID_BAS,
    UUID_REPORT_MAP, UUID_REPORT, UUID_REPORT_REF,
    UUID_HID_INFO, UUID_HID_CP, UUID_PROTOCOL_MODE,
    UUID_PNP_ID, UUID_MFR_NAME, UUID_MODEL_NUM, UUID_SERIAL_NUM,
    UUID_BATTERY_LEVEL,
    BLUEZ_SERVICE_NAME, ADAPTER_IFACE,
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
        self.on_notify_changed: Optional[Callable[[bool], None]] = None
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
        self._set_notifying(True)

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self._set_notifying(False)

    def _set_notifying(self, value: bool):
        if self.notifying != value:
            self.notifying = value
            logger.debug("Notifications %s on %s", "enabled" if value else "disabled", self.path)
            if self.on_notify_changed:
                self.on_notify_changed(value)

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
            "Type": dbus.String("peripheral"),
            "ServiceUUIDs": dbus.Array(["1812", "180F", "180A"], signature="s"),
            "LocalName": dbus.String(self.local_name),
            "Appearance": dbus.UInt16(960),  # 0x03C0 = Generic HID
            "Discoverable": dbus.Boolean(True),
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
        super().__init__(bus, index, UUID_REPORT_MAP, ["encrypt-read"], service)
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
        super().__init__(bus, index, UUID_REPORT, ["encrypt-read", "notify"], service)
        self.value = dbus.ByteArray(bytes([0] * 8))
        self.add_descriptor(ReportReferenceDescriptor(bus, 0, self, REPORT_ID_KEYBOARD, REPORT_TYPE_INPUT))


class MouseInputReportCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_REPORT, ["encrypt-read", "notify"], service)
        self.value = dbus.ByteArray(bytes([0] * 7))
        self.add_descriptor(ReportReferenceDescriptor(bus, 0, self, REPORT_ID_MOUSE, REPORT_TYPE_INPUT))


class KeyboardOutputReportCharacteristic(Characteristic):
    def __init__(self, bus: dbus.SystemBus, index: int, service: Service):
        super().__init__(bus, index, UUID_REPORT, ["encrypt-read", "encrypt-write", "write-without-response"], service)
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
    """BLE HID peripheral: registers the GATT app + advertisement and sends reports."""

    def __init__(self, adapter_path: str = "/org/bluez/hci0", local_name: str = "BlueShift"):
        self.adapter_path = adapter_path
        self.local_name = local_name
        self.is_running = False      # GATT app + advertisement registered with BlueZ
        self.last_error = ""

        self.packets_sent_kb = 0
        self.packets_sent_mouse = 0

        # Fired (from the GLib thread) when a target subscribes/unsubscribes to HID reports
        self.on_ready_changed: Optional[Callable[[bool], None]] = None

        self.bus: Optional[dbus.SystemBus] = None
        self.app: Optional[Application] = None
        self.adv: Optional[Advertisement] = None
        self.kb_char: Optional[KeyboardInputReportCharacteristic] = None
        self.mouse_char: Optional[MouseInputReportCharacteristic] = None
        self.battery_char: Optional[BatteryLevelCharacteristic] = None
        self._name_watch = None
        self._send_lock = threading.Lock()
        self._start_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        """True when a target is connected and subscribed to keyboard reports."""
        return bool(self.kb_char and self.kb_char.notifying)

    def _ensure_dbus(self):
        if self.bus is None:
            from .bus import get_bus
            self.bus = get_bus()

    def get_adapter_info(self) -> Dict[str, Any]:
        """Local Bluetooth adapter details."""
        try:
            self._ensure_dbus()
            props = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path), DBUS_PROP_IFACE
            ).GetAll(ADAPTER_IFACE)
            return {
                "path": self.adapter_path,
                "address": str(props.get("Address", "")),
                "alias": str(props.get("Alias", "")),
                "powered": bool(props.get("Powered", False)),
            }
        except dbus.exceptions.DBusException as e:
            logger.debug("Could not read adapter properties: %s", e)
            return {"path": self.adapter_path, "address": "", "alias": "", "powered": False}

    def _build_app(self):
        """Export the GATT object tree once per process."""
        self.app = Application(self.bus)

        hid_service = Service(self.bus, 0, UUID_HOGP, True)
        hid_service.add_characteristic(ProtocolModeCharacteristic(self.bus, 0, hid_service))
        hid_service.add_characteristic(ReportMapCharacteristic(self.bus, 1, hid_service))
        hid_service.add_characteristic(HidInformationCharacteristic(self.bus, 2, hid_service))
        hid_service.add_characteristic(HidControlPointCharacteristic(self.bus, 3, hid_service))
        self.kb_char = KeyboardInputReportCharacteristic(self.bus, 4, hid_service)
        self.kb_char.on_notify_changed = self._on_notify_changed
        hid_service.add_characteristic(self.kb_char)
        self.mouse_char = MouseInputReportCharacteristic(self.bus, 5, hid_service)
        hid_service.add_characteristic(self.mouse_char)
        hid_service.add_characteristic(KeyboardOutputReportCharacteristic(self.bus, 6, hid_service))
        self.app.add_service(hid_service)

        dis_service = Service(self.bus, 1, UUID_DIS, True)
        for i, (uuid, value) in enumerate([
            (UUID_PNP_ID, bytes([0x02, 0x5e, 0x04, 0x01, 0x00, 0x01, 0x00])),
            (UUID_MFR_NAME, b"BlueShift"),
            (UUID_MODEL_NUM, b"BlueShift BLE KVM"),
            (UUID_SERIAL_NUM, b"BS-2026"),
        ]):
            chrc = Characteristic(self.bus, i, uuid, ["read"], dis_service)
            chrc.value = dbus.ByteArray(value)
            dis_service.add_characteristic(chrc)
        self.app.add_service(dis_service)

        bas_service = Service(self.bus, 2, UUID_BAS, True)
        self.battery_char = BatteryLevelCharacteristic(self.bus, 0, bas_service)
        bas_service.add_characteristic(self.battery_char)
        self.app.add_service(bas_service)

        self.adv = Advertisement(self.bus, 0, self.local_name)

    def _call(self, method, *args) -> Optional[str]:
        """Run an async BlueZ registration call and wait for it; returns an error string or None."""
        done = threading.Event()
        err: List[str] = []

        def on_err(e):
            err.append(str(e))
            done.set()

        method(*args, reply_handler=done.set, error_handler=on_err)
        if not done.wait(timeout=5.0):
            return "timed out waiting for BlueZ"
        return err[0] if err else None

    def start(self) -> bool:
        """Register the HID GATT application and LE advertisement with BlueZ."""
        if not self._start_lock.acquire(blocking=False):
            return self.is_running  # another thread is already registering
        try:
            return self._start_locked()
        finally:
            self._start_lock.release()

    def _start_locked(self) -> bool:
        if self.is_running:
            return True
        try:
            self._ensure_dbus()
            if self.app is None:
                self._build_app()
            if self._name_watch is None:
                # bluetoothd restarts drop our registration: re-register when it comes back
                self._name_watch = self.bus.watch_name_owner(BLUEZ_SERVICE_NAME, self._on_bluez_owner)

            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
            if not bool(props.Get(ADAPTER_IFACE, "Powered")):
                props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))

            error = self._call(dbus.Interface(adapter_obj, GATT_MGR_IFACE).RegisterApplication,
                               self.app.get_path(), {})
            if error:
                raise RuntimeError(f"GATT registration failed: {error}")
            error = self._call(dbus.Interface(adapter_obj, LE_ADV_MGR_IFACE).RegisterAdvertisement,
                               self.adv.get_path(), {})
            if error:
                self._unregister_app()
                raise RuntimeError(f"Advertising failed: {error}")

            self.is_running = True
            self.last_error = ""
            logger.info("BLE HID server running (advertising as %r).", self.local_name)
            return True
        except (dbus.exceptions.DBusException, RuntimeError) as e:
            self.last_error = str(e)
            logger.error("Could not start BLE server: %s", e)
            return False

    def _unregister_app(self):
        try:
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            dbus.Interface(adapter_obj, GATT_MGR_IFACE).UnregisterApplication(self.app.get_path())
        except dbus.exceptions.DBusException as e:
            logger.debug("UnregisterApplication: %s", e)

    def stop(self):
        """Unregister from BlueZ (objects stay exported so start() can re-register)."""
        if not self.is_running:
            return
        self.is_running = False
        try:
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            dbus.Interface(adapter_obj, LE_ADV_MGR_IFACE).UnregisterAdvertisement(self.adv.get_path())
        except dbus.exceptions.DBusException as e:
            logger.debug("UnregisterAdvertisement: %s", e)
        self._unregister_app()
        if self.kb_char:
            self.kb_char._set_notifying(False)
        logger.info("BLE HID server stopped.")

    def _on_bluez_owner(self, owner: str):
        if not owner:
            if self.is_running:
                logger.warning("bluetoothd went away; will re-register when it returns.")
            self.is_running = False
            if self.kb_char:
                self.kb_char._set_notifying(False)
            return
        if not self.is_running and self.app is not None:
            logger.info("bluetoothd is available; registering BLE server.")
            threading.Thread(target=self.start, daemon=True).start()

    def _on_notify_changed(self, subscribed: bool):
        logger.info("Target %s HID reports.", "subscribed to" if subscribed else "unsubscribed from")
        if self.on_ready_changed:
            try:
                self.on_ready_changed(subscribed)
            except Exception:
                logger.exception("on_ready_changed callback failed")

    # ========================================================================
    # HID Report Transmission
    # ========================================================================

    def send_keyboard_report(self, modifiers: int, keys: List[int]):
        """Send an 8-byte HID keyboard report (up to 6 simultaneous keys)."""
        if not self.kb_char:
            return
        slots = list(keys[:6]) + [0] * (6 - len(keys[:6]))
        report = bytes([modifiers & 0xFF, 0x00] + [k & 0xFF for k in slots])
        try:
            with self._send_lock:
                self.kb_char.notify_value(report)
            self.packets_sent_kb += 1
        except Exception as e:
            logger.debug("Failed to send keyboard report: %s", e)

    def send_mouse_report(self, buttons: int, dx: int, dy: int, wheel: int = 0, hwheel: int = 0):
        """Send a 7-byte mouse report: buttons, X/Y (16-bit), wheel, pan."""
        if not self.mouse_char:
            return
        dx = max(-32767, min(32767, int(dx)))
        dy = max(-32767, min(32767, int(dy)))
        wheel = max(-127, min(127, int(wheel)))
        hwheel = max(-127, min(127, int(hwheel)))
        report = (bytes([buttons & 0x1F])
                  + dx.to_bytes(2, "little", signed=True)
                  + dy.to_bytes(2, "little", signed=True)
                  + wheel.to_bytes(1, "little", signed=True)
                  + hwheel.to_bytes(1, "little", signed=True))
        try:
            with self._send_lock:
                self.mouse_char.notify_value(report)
            self.packets_sent_mouse += 1
        except Exception as e:
            logger.debug("Failed to send mouse report: %s", e)


# Global singleton instance
ble_server = BleServer()
