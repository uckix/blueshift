"""
BlueShift test suite. Runs without Bluetooth or input hardware (fakes stand in for both).
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import evdev
from evdev import ecodes as e

from src.core.hid_constants import REPORT_MAP_BYTES, REPORT_ID_KEYBOARD, REPORT_ID_MOUSE, EVDEV_TO_HID_KEY, MODIFIER_MASKS
from src.core.config import ConfigManager, config
from src.core.ble_server import BleServer
from src.core import input_grabber
from src.core.input_grabber import InputGrabber, CONTROL_LOCAL, CONTROL_REMOTE
from src.core import ipc


class FakeBle:
    def __init__(self, ready=True):
        self.ready = ready
        self.kb = []
        self.mouse = []

    def send_keyboard_report(self, mods, keys):
        self.kb.append((mods, list(keys)))

    def send_mouse_report(self, buttons, dx, dy, wheel=0, hwheel=0):
        self.mouse.append((buttons, dx, dy, wheel, hwheel))


class FakeDev:
    def __init__(self, held=()):
        self.name = "Fake Keyboard"
        self.held = list(held)
        self.grabbed = False

    def active_keys(self):
        return self.held

    def grab(self):
        self.grabbed = True

    def ungrab(self):
        self.grabbed = False


def key(code, value):
    return evdev.InputEvent(0, 0, e.EV_KEY, code, value)


def rel(code, value):
    return evdev.InputEvent(0, 0, e.EV_REL, code, value)


SYN = evdev.InputEvent(0, 0, e.EV_SYN, e.SYN_REPORT, 0)


class TestHidConstants(unittest.TestCase):
    def test_report_map(self):
        self.assertIn(bytes([0x85, REPORT_ID_KEYBOARD]), REPORT_MAP_BYTES)
        self.assertIn(bytes([0x85, REPORT_ID_MOUSE]), REPORT_MAP_BYTES)

    def test_modifiers_and_keys(self):
        self.assertEqual(sum(MODIFIER_MASKS.values()), 0xFF)
        self.assertEqual(EVDEV_TO_HID_KEY[e.KEY_A], 0x04)
        self.assertEqual(EVDEV_TO_HID_KEY[e.KEY_102ND], 0x64)
        # Every mapped key must fit the report map's logical maximum (0x65)
        self.assertLessEqual(max(EVDEV_TO_HID_KEY.values()), 0x65)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "config.json"

    def test_persistence(self):
        cfg = ConfigManager(self.tmp)
        cfg.set("client_name", "archlab")
        self.assertEqual(ConfigManager(self.tmp).get("client_name"), "archlab")

    def test_legacy_and_bad_values(self):
        self.tmp.write_text(json.dumps({"role": "target", "hotkey": "nope", "battery_level": 5}))
        cfg = ConfigManager(self.tmp)
        self.assertEqual(cfg.get("role"), "client")
        self.assertEqual(cfg.get("hotkey"), "ctrl_alt_s")
        self.assertEqual(cfg.get("battery_level"), 5)  # unknown keys preserved

    def test_corrupt_file(self):
        self.tmp.write_text("{not json")
        self.assertEqual(ConfigManager(self.tmp).get("role"), "server")


class TestReports(unittest.TestCase):
    def test_encoding(self):
        server = BleServer()
        sent = {}

        class Char:
            def __init__(self, k):
                self.k = k

            def notify_value(self, v):
                sent[self.k] = v

        server.kb_char, server.mouse_char = Char("kb"), Char("m")
        server.send_keyboard_report(0x01, [0x04, 0x05])
        self.assertEqual(sent["kb"], bytes([1, 0, 4, 5, 0, 0, 0, 0]))
        server.send_mouse_report(0x01, 10, -15, 1, -1)
        self.assertEqual(sent["m"], bytes([1, 10, 0, 0xF1, 0xFF, 1, 0xFF]))
        server.send_mouse_report(0, 99999, -99999, 500, -500)  # clamped, no OverflowError
        self.assertEqual(len(sent["m"]), 7)


class TestInputEngine(unittest.TestCase):
    def setUp(self):
        self.ble = FakeBle()
        self.g = InputGrabber(self.ble)
        self.dev = FakeDev()
        self.g.devices = {"/dev/input/fake": self.dev}
        self.notify = mock.patch.object(input_grabber, "send_desktop_notification").start()
        self.hotkey = mock.patch.dict(config._data, {"hotkey": "ctrl_alt_s", "mouse_sensitivity": 1.0}).start()

    def tearDown(self):
        mock.patch.stopall()

    def feed(self, *events):
        for ev in events:
            self.g._handle_event(ev)
        self.g._maybe_finish_grab()

    def test_hotkey_waits_for_release_before_grabbing(self):
        self.dev.held = [e.KEY_LEFTCTRL, e.KEY_LEFTALT, e.KEY_S]
        self.feed(key(e.KEY_LEFTCTRL, 1), key(e.KEY_LEFTALT, 1), key(e.KEY_S, 1))
        self.assertEqual(self.g.current_control, CONTROL_LOCAL)  # still held -> not grabbed yet
        self.assertFalse(self.dev.grabbed)
        self.dev.held = []
        self.feed(key(e.KEY_S, 0), key(e.KEY_LEFTALT, 0), key(e.KEY_LEFTCTRL, 0))
        self.assertEqual(self.g.current_control, CONTROL_REMOTE)
        self.assertTrue(self.dev.grabbed)
        self.assertEqual(self.ble.kb, [])  # the hotkey itself never reaches the target

    def test_refuses_remote_without_target(self):
        self.ble.ready = False
        self.assertEqual(self.g.set_control(CONTROL_REMOTE), "target not connected")
        self.assertEqual(self.g.current_control, CONTROL_LOCAL)

    def test_target_lost_returns_control(self):
        self.g.set_control(CONTROL_REMOTE)
        self.g._maybe_finish_grab()
        self.assertEqual(self.g.current_control, CONTROL_REMOTE)
        self.g.target_lost()
        self.assertEqual(self.g.current_control, CONTROL_LOCAL)
        self.assertFalse(self.dev.grabbed)
        self.assertEqual(self.ble.kb[-1], (0, []))  # all keys released on target

    def test_no_mouse_jump_after_local_movement(self):
        self.feed(rel(e.REL_X, 500), rel(e.REL_Y, 500), SYN)  # moving locally
        self.g.set_control(CONTROL_REMOTE)
        self.g._maybe_finish_grab()
        self.g._last_mouse_send = 0
        self.feed(rel(e.REL_X, 3), SYN)
        self.assertEqual(self.ble.mouse[-1][1:3], (3, 0))

    def test_keys_forwarded_and_repeat_ignored(self):
        self.g.set_control(CONTROL_REMOTE)
        self.g._maybe_finish_grab()
        self.feed(key(e.KEY_LEFTSHIFT, 1), key(e.KEY_A, 1), key(e.KEY_A, 2), key(e.KEY_A, 2))
        self.assertEqual(self.ble.kb, [(0x02, []), (0x02, [0x04])])
        self.feed(key(e.KEY_A, 0))
        self.assertEqual(self.ble.kb[-1], (0x02, []))

    def test_clicks_are_immediate_motion_is_coalesced(self):
        self.g.set_control(CONTROL_REMOTE)
        self.g._maybe_finish_grab()
        self.g._last_mouse_send = 10**9  # pretend we just sent
        self.feed(rel(e.REL_X, 1), SYN, rel(e.REL_X, 1), SYN)
        self.assertEqual(self.ble.mouse, [])  # coalesced, flushed later by the loop
        self.feed(key(e.BTN_LEFT, 1))
        self.assertEqual(self.ble.mouse[-1], (0x01, 2, 0, 0, 0))

    def test_hotkey_toggles_back(self):
        self.g.set_control(CONTROL_REMOTE)
        self.g._maybe_finish_grab()
        self.feed(key(e.KEY_LEFTCTRL, 1), key(e.KEY_LEFTALT, 1), key(e.KEY_S, 1))
        self.assertEqual(self.g.current_control, CONTROL_LOCAL)
        self.assertFalse(self.dev.grabbed)


class TestIpc(unittest.TestCase):
    def test_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmpdir}):
            server = ipc.IpcServer(lambda cmd: {"ok": True, "echo": cmd})
            self.assertTrue(server.start())
            try:
                self.assertEqual(ipc.request("STATUS"), {"ok": True, "echo": "status"})
                self.assertEqual(oct(os.stat(ipc.socket_path()).st_mode & 0o777), "0o600")
                self.assertFalse(ipc.IpcServer(lambda c: {}).start())  # second daemon refused
            finally:
                server.stop()
            self.assertIsNone(ipc.request("status"))


class TestGui(unittest.TestCase):
    def test_window_renders_every_state(self):
        from PyQt6.QtWidgets import QApplication
        from src.gui import app as gui
        self.qapp = QApplication.instance() or QApplication(["test"])
        states = [
            None,
            {"ok": True, "role": "server", "control": "LOCAL", "ready": True, "ble": True,
             "keyboards": 1, "mice": 1, "unreadable": 0, "host_name": "parrot",
             "client_name": "archlab", "hotkey": "Ctrl + Alt + S"},
            {"ok": True, "role": "client", "state": "pairing", "message": "Pairing…", "host_name": "parrot"},
            {"ok": True, "role": "client", "state": "connected", "message": "", "host_name": "parrot"},
        ]
        for st in states:
            with mock.patch.object(gui.ipc, "request", return_value=st):
                w = gui.Window()
                w.refresh()
                self.assertIn("●", w.status.text())
                w.close()


if __name__ == "__main__":
    unittest.main()
