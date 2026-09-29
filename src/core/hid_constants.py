"""
BlueShift HID and Bluetooth GATT Constants
Defines standard Bluetooth UUIDs, HID Report Map descriptors, and evdev-to-HID key mappings.
"""

import evdev.ecodes as e

# Bluetooth GATT Service UUIDs
UUID_HOGP = "00001812-0000-1000-8000-00805f9b34fb"  # Human Interface Device
UUID_DIS = "0000180a-0000-1000-8000-00805f9b34fb"   # Device Information Service
UUID_BAS = "0000180f-0000-1000-8000-00805f9b34fb"   # Battery Service

# HID Characteristics
UUID_REPORT_MAP = "00002a4b-0000-1000-8000-00805f9b34fb"
UUID_REPORT = "00002a4d-0000-1000-8000-00805f9b34fb"
UUID_REPORT_REF = "00002908-0000-1000-8000-00805f9b34fb"
UUID_HID_INFO = "00002a4a-0000-1000-8000-00805f9b34fb"
UUID_HID_CP = "00002a4c-0000-1000-8000-00805f9b34fb"
UUID_PROTOCOL_MODE = "00002a4e-0000-1000-8000-00805f9b34fb"

# DIS Characteristics
UUID_PNP_ID = "00002a50-0000-1000-8000-00805f9b34fb"
UUID_MFR_NAME = "00002a29-0000-1000-8000-00805f9b34fb"
UUID_MODEL_NUM = "00002a24-0000-1000-8000-00805f9b34fb"
UUID_SERIAL_NUM = "00002a25-0000-1000-8000-00805f9b34fb"

# Battery Characteristic
UUID_BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"

# BlueZ DBus Interfaces
BLUEZ_SERVICE_NAME = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
GATT_MGR_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
GATT_DESC_IFACE = "org.bluez.GattDescriptor1"
LE_ADV_MGR_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADV_IFACE = "org.bluez.LEAdvertisement1"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"

# Report Types (defined in HOGP)
REPORT_TYPE_INPUT = 0x01
REPORT_TYPE_OUTPUT = 0x02
REPORT_TYPE_FEATURE = 0x03

# Report IDs
REPORT_ID_KEYBOARD = 0x01
REPORT_ID_MOUSE = 0x02

# Combined HID Report Map (Keyboard ID 1 + Mouse ID 2)
REPORT_MAP_BYTES = bytes([
    # --- Keyboard Input & Output Report (Report ID 1) ---
    0x05, 0x01,        # Usage Page (Generic Desktop Ctrls)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x01,        #   Report ID (1)
    0x05, 0x07,        #   Usage Page (Kbrd/Keypad)
    0x19, 0xE0,        #   Usage Minimum (0xE0: Left Ctrl)
    0x29, 0xE7,        #   Usage Maximum (0xE7: Right GUI)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data,Var,Abs) - Modifier Byte
    0x95, 0x01,        #   Report Count (1)
    0x75, 0x08,        #   Report Size (8)
    0x81, 0x01,        #   Input (Const,Array,Abs) - Reserved Byte
    0x95, 0x05,        #   Report Count (5)
    0x75, 0x01,        #   Report Size (1)
    0x05, 0x08,        #   Usage Page (LEDs)
    0x19, 0x01,        #   Usage Minimum (Num Lock)
    0x29, 0x05,        #   Usage Maximum (Kana)
    0x91, 0x02,        #   Output (Data,Var,Abs) - LED outputs
    0x95, 0x01,        #   Report Count (1)
    0x75, 0x03,        #   Report Size (3)
    0x91, 0x01,        #   Output (Const,Array,Abs) - LED padding
    0x95, 0x06,        #   Report Count (6)
    0x75, 0x08,        #   Report Size (8)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x65,        #   Logical Maximum (101 keys)
    0x05, 0x07,        #   Usage Page (Kbrd/Keypad)
    0x19, 0x00,        #   Usage Minimum (0)
    0x29, 0x65,        #   Usage Maximum (101)
    0x81, 0x00,        #   Input (Data,Array,Abs) - 6 Key Array
    0xC0,              # End Collection

    # --- Mouse Input Report (Report ID 2) ---
    0x05, 0x01,        # Usage Page (Generic Desktop Ctrls)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x02,        #   Report ID (2)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    0x05, 0x09,        #     Usage Page (Button)
    0x19, 0x01,        #     Usage Minimum (Button 1)
    0x29, 0x05,        #     Usage Maximum (Button 5)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x95, 0x05,        #     Report Count (5)
    0x75, 0x01,        #     Report Size (1)
    0x81, 0x02,        #     Input (Data,Var,Abs) - 5 Buttons
    0x95, 0x01,        #     Report Count (1)
    0x75, 0x03,        #     Report Size (3)
    0x81, 0x01,        #     Input (Const,Array,Abs) - Button padding
    0x05, 0x01,        #     Usage Page (Generic Desktop Ctrls)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x16, 0x01, 0x80,  #     Logical Minimum (-32767)
    0x26, 0xFF, 0x7F,  #     Logical Maximum (32767)
    0x75, 0x10,        #     Report Size (16 bits)
    0x95, 0x02,        #     Report Count (2: X and Y)
    0x81, 0x06,        #     Input (Data,Var,Rel)
    0x09, 0x38,        #     Usage (Wheel)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8 bits)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x06,        #     Input (Data,Var,Rel)
    0x05, 0x0C,        #     Usage Page (Consumer Devices)
    0x0A, 0x38, 0x02,  #     Usage (AC Pan / Horizontal Wheel)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8 bits)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x06,        #     Input (Data,Var,Rel)
    0xC0,              #   End Collection
    0xC0               # End Collection
])

# Modifier key bits (first byte of keyboard report)
MODIFIER_MASKS = {
    e.KEY_LEFTCTRL: 0x01,
    e.KEY_LEFTSHIFT: 0x02,
    e.KEY_LEFTALT: 0x04,
    e.KEY_LEFTMETA: 0x08,
    e.KEY_RIGHTCTRL: 0x10,
    e.KEY_RIGHTSHIFT: 0x20,
    e.KEY_RIGHTALT: 0x40,
    e.KEY_RIGHTMETA: 0x80,
}

# Mouse button masks (first byte of mouse report)
MOUSE_BUTTON_MASKS = {
    e.BTN_LEFT: 0x01,
    e.BTN_RIGHT: 0x02,
    e.BTN_MIDDLE: 0x04,
    e.BTN_SIDE: 0x08,
    e.BTN_EXTRA: 0x10,
    getattr(e, 'BTN_BACK', 0x116): 0x08,
    getattr(e, 'BTN_FORWARD', 0x117): 0x10,
}

# Mapping of Linux evdev keycodes to standard USB HID Keyboard codes (0x07 Usage Page)
EVDEV_TO_HID_KEY = {
    # Letters
    e.KEY_A: 0x04,
    e.KEY_B: 0x05,
    e.KEY_C: 0x06,
    e.KEY_D: 0x07,
    e.KEY_E: 0x08,
    e.KEY_F: 0x09,
    e.KEY_G: 0x0A,
    e.KEY_H: 0x0B,
    e.KEY_I: 0x0C,
    e.KEY_J: 0x0D,
    e.KEY_K: 0x0E,
    e.KEY_L: 0x0F,
    e.KEY_M: 0x10,
    e.KEY_N: 0x11,
    e.KEY_O: 0x12,
    e.KEY_P: 0x13,
    e.KEY_Q: 0x14,
    e.KEY_R: 0x15,
    e.KEY_S: 0x16,
    e.KEY_T: 0x17,
    e.KEY_U: 0x18,
    e.KEY_V: 0x19,
    e.KEY_W: 0x1A,
    e.KEY_X: 0x1B,
    e.KEY_Y: 0x1C,
    e.KEY_Z: 0x1D,

    # Numbers
    e.KEY_1: 0x1E,
    e.KEY_2: 0x1F,
    e.KEY_3: 0x20,
    e.KEY_4: 0x21,
    e.KEY_5: 0x22,
    e.KEY_6: 0x23,
    e.KEY_7: 0x24,
    e.KEY_8: 0x25,
    e.KEY_9: 0x26,
    e.KEY_0: 0x27,

    # Control / Whitespace
    e.KEY_ENTER: 0x28,
    e.KEY_ESC: 0x29,
    e.KEY_BACKSPACE: 0x2A,
    e.KEY_TAB: 0x2B,
    e.KEY_SPACE: 0x2C,

    # Punctuation / Symbols
    e.KEY_MINUS: 0x2D,
    e.KEY_EQUAL: 0x2E,
    e.KEY_LEFTBRACE: 0x2F,
    e.KEY_RIGHTBRACE: 0x30,
    e.KEY_BACKSLASH: 0x31,
    e.KEY_SEMICOLON: 0x33,
    e.KEY_APOSTROPHE: 0x34,
    e.KEY_GRAVE: 0x35,
    e.KEY_COMMA: 0x36,
    e.KEY_DOT: 0x37,
    e.KEY_SLASH: 0x38,
    e.KEY_CAPSLOCK: 0x39,

    # Function Keys
    e.KEY_F1: 0x3A,
    e.KEY_F2: 0x3B,
    e.KEY_F3: 0x3C,
    e.KEY_F4: 0x3D,
    e.KEY_F5: 0x3E,
    e.KEY_F6: 0x3F,
    e.KEY_F7: 0x40,
    e.KEY_F8: 0x41,
    e.KEY_F9: 0x42,
    e.KEY_F10: 0x43,
    e.KEY_F11: 0x44,
    e.KEY_F12: 0x45,

    # Navigation & System
    e.KEY_PRINT: 0x46,
    e.KEY_SYSRQ: 0x46,       # PrintScreen reports as SYSRQ on PC keyboards
    e.KEY_SCROLLLOCK: 0x47,
    e.KEY_PAUSE: 0x48,
    e.KEY_INSERT: 0x49,
    e.KEY_HOME: 0x4A,
    e.KEY_PAGEUP: 0x4B,
    e.KEY_DELETE: 0x4C,
    e.KEY_END: 0x4D,
    e.KEY_PAGEDOWN: 0x4E,
    e.KEY_RIGHT: 0x4F,
    e.KEY_LEFT: 0x50,
    e.KEY_DOWN: 0x51,
    e.KEY_UP: 0x52,

    # Keypad
    e.KEY_NUMLOCK: 0x53,
    e.KEY_KPSLASH: 0x54,
    e.KEY_KPASTERISK: 0x55,
    e.KEY_KPMINUS: 0x56,
    e.KEY_KPPLUS: 0x57,
    e.KEY_KPENTER: 0x58,
    e.KEY_KP1: 0x59,
    e.KEY_KP2: 0x5A,
    e.KEY_KP3: 0x5B,
    e.KEY_KP4: 0x5C,
    e.KEY_KP5: 0x5D,
    e.KEY_KP6: 0x5E,
    e.KEY_KP7: 0x5F,
    e.KEY_KP8: 0x60,
    e.KEY_KP9: 0x61,
    e.KEY_KP0: 0x62,
    e.KEY_KPDOT: 0x63,

    # Miscellaneous (the report map's key array tops out at 0x65, so media keys can't be sent)
    e.KEY_102ND: 0x64,       # ISO "<>" key next to left Shift
    e.KEY_COMPOSE: 0x65,     # Menu / Application key
}
