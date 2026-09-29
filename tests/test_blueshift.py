"""
Automated Test Suite for BlueShift BLE KVM Switch.
Tests core modules, BLE reports, evdev mapping, config manager, and PyQt6 GUI offscreen.
"""

import sys
import os
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.hid_constants import (
    REPORT_MAP_BYTES, REPORT_ID_KEYBOARD, REPORT_ID_MOUSE,
    EVDEV_TO_HID_KEY, MODIFIER_MASKS, MOUSE_BUTTON_MASKS,
    UUID_HOGP, UUID_DIS, UUID_BAS
)
from src.core.config import ConfigManager, DEFAULT_CONFIG
from src.core.ble_server import BleServer
from src.core.input_grabber import (
    InputGrabber, list_input_devices, auto_detect_devices,
    CONTROL_LOCAL, CONTROL_REMOTE
)
from src.core.client_helper import ClientHelper


class TestHidConstants(unittest.TestCase):
    def test_report_map_descriptor(self):
        self.assertGreater(len(REPORT_MAP_BYTES), 100)
        # Check Report IDs present in descriptor
        self.assertIn(bytes([0x85, REPORT_ID_KEYBOARD]), REPORT_MAP_BYTES)
        self.assertIn(bytes([0x85, REPORT_ID_MOUSE]), REPORT_MAP_BYTES)

    def test_modifier_masks(self):
        self.assertEqual(len(MODIFIER_MASKS), 8)
        self.assertEqual(sum(MODIFIER_MASKS.values()), 0xFF)

    def test_evdev_to_hid(self):
        # Key 'A' should map to HID 0x04
        import evdev.ecodes as e
        self.assertEqual(EVDEV_TO_HID_KEY[e.KEY_A], 0x04)
        self.assertEqual(EVDEV_TO_HID_KEY[e.KEY_Z], 0x1D)
        self.assertEqual(EVDEV_TO_HID_KEY[e.KEY_ENTER], 0x28)
        self.assertEqual(EVDEV_TO_HID_KEY[e.KEY_SPACE], 0x2C)


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.tmp_config = PROJECT_ROOT / "tests" / "scratch_config.json"
        if self.tmp_config.exists():
            self.tmp_config.unlink()
        self.cfg = ConfigManager(self.tmp_config)

    def tearDown(self):
        if self.tmp_config.exists():
            self.tmp_config.unlink()

    def test_defaults_and_persistence(self):
        self.assertEqual(self.cfg.get("role"), "server")
        self.assertEqual(self.cfg.get("host_name"), "Parrot")
        self.assertEqual(self.cfg.get("client_name"), "ArchLab")

        # Set and test save
        self.cfg.set("host_name", "ParrotOS")
        self.assertEqual(self.cfg.get("host_name"), "ParrotOS")

        # Reload from disk
        cfg2 = ConfigManager(self.tmp_config)
        self.assertEqual(cfg2.get("host_name"), "ParrotOS")

    def test_listener_callback(self):
        changed = []
        self.cfg.add_listener(lambda k, v: changed.append((k, v)))
        self.cfg.set("hotkey", "ctrl_alt_s")
        self.assertEqual(changed, [("hotkey", "ctrl_alt_s")])


class TestBleServer(unittest.TestCase):
    def test_ble_server_instantiation(self):
        server = BleServer()
        self.assertFalse(server.is_running)
        adapter_info = server.get_adapter_info()
        self.assertIn("address", adapter_info)
        self.assertIn("alias", adapter_info)

    def test_report_encoding(self):
        server = BleServer()
        # Mock characteristics to test report generation
        class MockChar:
            def __init__(self):
                self.last_val = None
            def notify_value(self, val):
                self.last_val = val

        server.kb_char = MockChar()
        server.mouse_char = MockChar()

        # Keyboard report test
        server.send_keyboard_report(modifiers=0x01, keys=[0x04, 0x05])
        self.assertEqual(len(server.kb_char.last_val), 8)
        self.assertEqual(server.kb_char.last_val[0], 0x01)  # Modifiers
        self.assertEqual(server.kb_char.last_val[1], 0x00)  # Reserved
        self.assertEqual(server.kb_char.last_val[2], 0x04)  # Key 1
        self.assertEqual(server.kb_char.last_val[3], 0x05)  # Key 2
        self.assertEqual(server.kb_char.last_val[4:], b"\x00\x00\x00\x00")

        # Mouse report test
        server.send_mouse_report(buttons=0x01, dx=10, dy=-15, wheel=1, hwheel=-1)
        self.assertEqual(len(server.mouse_char.last_val), 7)
        self.assertEqual(server.mouse_char.last_val[0], 0x01)  # Button 1


class TestInputGrabber(unittest.TestCase):
    def test_device_discovery(self):
        devices = list_input_devices()
        self.assertIsInstance(devices, list)
        self.assertGreater(len(devices), 0)

        kbd, mouse = auto_detect_devices()
        print(f"\n[Test] Auto-detected: Keyboard={kbd}, Mouse={mouse}")
        self.assertIsNotNone(kbd)
        self.assertIsNotNone(mouse)

    def test_control_toggling(self):
        server = BleServer()
        grabber = InputGrabber(server)
        self.assertEqual(grabber.current_control, CONTROL_LOCAL)

        # Toggle to REMOTE
        grabber.toggle_control()
        self.assertEqual(grabber.current_control, CONTROL_REMOTE)

        # Toggle back to LOCAL
        grabber.toggle_control()
        self.assertEqual(grabber.current_control, CONTROL_LOCAL)


class TestClientHelper(unittest.TestCase):
    def test_client_helper_instantiation(self):
        client = ClientHelper()
        self.assertFalse(client.is_scanning)
        devices = client.get_devices()
        self.assertIsInstance(devices, list)

    def test_virtual_device_detection(self):
        client = ClientHelper()
        vdevs = client.detect_virtual_hid_devices("parrot")
        self.assertIn("keyboard", vdevs)
        self.assertIn("mouse", vdevs)


class TestPyQt6Gui(unittest.TestCase):
    def test_gui_offscreen_instantiation(self):
        from PyQt6.QtWidgets import QApplication
        from src.gui.main_window import MainWindow

        app = QApplication.instance()
        if app is None:
            app = QApplication(["blueshift_test", "-platform", "offscreen"])

        window = MainWindow()
        self.assertEqual(window.tab_widget.count(), 3)
        self.assertIn("Host", window.tab_widget.tabText(0))
        self.assertIn("Target", window.tab_widget.tabText(1))
        self.assertIn("Settings", window.tab_widget.tabText(2))

        # Test control state switch trigger in UI
        window.grabber.set_control(CONTROL_REMOTE)
        self.assertEqual(window.grabber.current_control, CONTROL_REMOTE)
        window.grabber.set_control(CONTROL_LOCAL)
        self.assertEqual(window.grabber.current_control, CONTROL_LOCAL)

        window.close()


if __name__ == "__main__":
    unittest.main()
