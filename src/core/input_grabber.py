"""
BlueShift evdev Input Grabbing and Hotkey Dispatch Engine.
Monitors keyboard and mouse events, captures exclusive hardware grab when remote,
translates scancodes into BLE HID reports, and handles instant hotkey toggling.
"""

import os
import sys
import time
import socket
import logging
import threading
import selectors
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Set, Callable, Tuple, Any

import evdev
from evdev import ecodes as e

from .hid_constants import (
    EVDEV_TO_HID_KEY, MODIFIER_MASKS, MOUSE_BUTTON_MASKS
)
from .config import config, CONFIG_DIR

logger = logging.getLogger("blueshift.grabber")

# Control State Constants
CONTROL_LOCAL = "LOCAL"    # Host PC active (e.g. Parrot)
CONTROL_REMOTE = "REMOTE"  # Client PC active (e.g. ArchLab)

SOCKET_FILE = CONFIG_DIR / "blueshift.sock"


def list_input_devices() -> List[Dict[str, Any]]:
    """Scan and return all accessible evdev input devices with role classification."""
    devices = []
    for path in sorted(evdev.list_devices()):
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            has_keys = e.EV_KEY in caps
            has_rel = e.EV_REL in caps

            is_keyboard = False
            is_mouse = False

            if has_keys:
                key_set = set(caps[e.EV_KEY])
                # A true keyboard must have alphabetical keys and space
                if e.KEY_A in key_set and e.KEY_SPACE in key_set:
                    is_keyboard = True

                # A mouse must have relative X/Y movement and mouse buttons
                if has_rel and (e.BTN_LEFT in key_set or e.BTN_MOUSE in key_set):
                    rel_set = set(caps[e.EV_REL])
                    if e.REL_X in rel_set and e.REL_Y in rel_set:
                        is_mouse = True

            devices.append({
                "path": path,
                "name": dev.name,
                "phys": dev.phys,
                "is_keyboard": is_keyboard,
                "is_mouse": is_mouse,
            })
        except Exception as err:
            logger.debug("Error inspecting device %s: %s", path, err)
    return devices


def auto_detect_devices() -> Tuple[Optional[str], Optional[str]]:
    """Automatically discover the best candidate keyboard and mouse event paths."""
    all_devs = list_input_devices()
    kbd_path = None
    mouse_path = None

    for d in all_devs:
        if not kbd_path and d["is_keyboard"]:
            kbd_path = d["path"]
        if not mouse_path and d["is_mouse"]:
            mouse_path = d["path"]

    return kbd_path, mouse_path


def send_desktop_notification(title: str, message: str, icon: str = "input-keyboard"):
    """Show an OS desktop notification if enabled in config."""
    if not config.get("notifications_enabled", True):
        return

    def _notify():
        try:
            subprocess.run(
                ["notify-send", "-a", "BlueShift", "-i", icon, title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
            )
        except Exception:
            pass

    threading.Thread(target=_notify, daemon=True).start()


class InputGrabber:
    """Manages input devices, exclusive evdev grabbing, and hotkey switching."""

    def __init__(self, ble_server_instance):
        self.ble_server = ble_server_instance
        self.current_control = CONTROL_LOCAL
        self.is_grabbed = False
        self.is_running = False

        self.kbd_path: Optional[str] = None
        self.mouse_path: Optional[str] = None
        self.kbd_dev: Optional[evdev.InputDevice] = None
        self.mouse_dev: Optional[evdev.InputDevice] = None

        # Tracking state
        self.active_modifiers_mask = 0
        self.pressed_keys: Set[int] = set()
        self.active_mouse_buttons = 0

        # Accumulated mouse relative deltas for frame-synced reporting
        self.accum_dx = 0
        self.accum_dy = 0
        self.accum_wheel = 0
        self.accum_hwheel = 0
        self.mouse_dirty = False

        # Modifiers for hotkey detection
        self._ctrl_down = False
        self._alt_down = False
        self._shift_down = False

        # Callbacks
        self.on_control_changed: Optional[Callable[[str], None]] = None
        self.on_pulse: Optional[Callable[[], None]] = None

        # Worker threads & sync
        self._selector: Optional[selectors.DefaultSelector] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # IPC Server thread
        self._ipc_thread: Optional[threading.Thread] = None

    def start(self, kbd_path: Optional[str] = None, mouse_path: Optional[str] = None) -> bool:
        """Start monitoring and event translation."""
        if self.is_running:
            return True

        # Use explicitly provided paths, or configuration, or auto-detect
        if not kbd_path:
            kbd_path = config.get("keyboard_device")
        if not mouse_path:
            mouse_path = config.get("mouse_device")

        auto_kbd, auto_mouse = auto_detect_devices()
        self.kbd_path = kbd_path or auto_kbd
        self.mouse_path = mouse_path or auto_mouse

        logger.info("Initializing InputGrabber with Keyboard=%s, Mouse=%s", self.kbd_path, self.mouse_path)

        self._stop_event.clear()
        self.is_running = True

        # Start input polling thread
        self._thread = threading.Thread(target=self._run_loop, name="BlueShift-InputLoop", daemon=True)
        self._thread.start()

        # Start IPC command listener thread (for blueshift --toggle)
        self._ipc_thread = threading.Thread(target=self._run_ipc_server, name="BlueShift-IPC", daemon=True)
        self._ipc_thread.start()

        return True

    def stop(self):
        """Release grabbed devices and terminate background worker threads."""
        logger.info("Stopping InputGrabber...")
        self.is_running = False
        self._stop_event.set()

        # Ensure devices are ungrabbed before closing
        self.release_grab()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        # Cleanup socket
        if SOCKET_FILE.exists():
            try:
                SOCKET_FILE.unlink()
            except Exception:
                pass

        logger.info("InputGrabber stopped.")

    def set_control(self, new_state: str) -> bool:
        """Switch active control between LOCAL and REMOTE."""
        with self._lock:
            if new_state == self.current_control:
                return True

            logger.info("Switching control: %s -> %s", self.current_control, new_state)
            self.current_control = new_state

            host_label = config.get("host_name", "Parrot")
            client_label = config.get("client_name", "ArchLab")

            if new_state == CONTROL_REMOTE:
                self._apply_grab()
                send_desktop_notification(
                    "BlueShift Active: Remote",
                    f"Keyboard & Mouse redirected to {client_label}",
                    "network-wireless",
                )
            else:
                self.release_grab()
                send_desktop_notification(
                    "BlueShift Active: Local",
                    f"Keyboard & Mouse returned to {host_label}",
                    "computer",
                )

            if self.on_control_changed:
                try:
                    self.on_control_changed(self.current_control)
                except Exception as e:
                    logger.debug("on_control_changed callback error: %s", e)

            return True

    def toggle_control(self) -> str:
        """Toggle control between LOCAL and REMOTE."""
        next_state = CONTROL_REMOTE if self.current_control == CONTROL_LOCAL else CONTROL_LOCAL
        self.set_control(next_state)
        return self.current_control

    def _apply_grab(self):
        """Acquire exclusive grab on hardware input devices."""
        if self.is_grabbed:
            return

        grabbed_any = False
        if self.kbd_dev:
            try:
                self.kbd_dev.grab()
                grabbed_any = True
                logger.debug("Grabbed keyboard device %s", self.kbd_path)
            except Exception as e:
                logger.warning("Failed to grab keyboard device %s: %s", self.kbd_path, e)

        if self.mouse_dev:
            try:
                self.mouse_dev.grab()
                grabbed_any = True
                logger.debug("Grabbed mouse device %s", self.mouse_path)
            except Exception as e:
                logger.warning("Failed to grab mouse device %s: %s", self.mouse_path, e)

        self.is_grabbed = grabbed_any

    def release_grab(self):
        """Release exclusive grab and reset all remote key/mouse states."""
        # Release remote keys and buttons so none remain stuck down on remote
        self.active_modifiers_mask = 0
        self.pressed_keys.clear()
        self.active_mouse_buttons = 0
        self.accum_dx = 0
        self.accum_dy = 0
        self.accum_wheel = 0
        self.accum_hwheel = 0

        if self.ble_server:
            try:
                self.ble_server.send_keyboard_report(0, [])
                self.ble_server.send_mouse_report(0, 0, 0, 0, 0)
            except Exception:
                pass

        if self.kbd_dev and self.is_grabbed:
            try:
                self.kbd_dev.ungrab()
                logger.debug("Ungrabbed keyboard device %s", self.kbd_path)
            except Exception as e:
                logger.debug("kbd ungrab note: %s", e)

        if self.mouse_dev and self.is_grabbed:
            try:
                self.mouse_dev.ungrab()
                logger.debug("Ungrabbed mouse device %s", self.mouse_path)
            except Exception as e:
                logger.debug("mouse ungrab note: %s", e)

        self.is_grabbed = False

    def _open_devices(self, selector: selectors.DefaultSelector):
        """Open keyboard and mouse input devices and register with selector."""
        # Keyboard
        if self.kbd_path and os.path.exists(self.kbd_path):
            try:
                self.kbd_dev = evdev.InputDevice(self.kbd_path)
                selector.register(self.kbd_dev, selectors.EVENT_READ, data="keyboard")
                logger.info("Opened keyboard: %s (%s)", self.kbd_dev.name, self.kbd_path)
            except Exception as e:
                logger.error("Could not open keyboard %s: %s", self.kbd_path, e)

        # Mouse
        if self.mouse_path and os.path.exists(self.mouse_path):
            try:
                self.mouse_dev = evdev.InputDevice(self.mouse_path)
                selector.register(self.mouse_dev, selectors.EVENT_READ, data="mouse")
                logger.info("Opened mouse: %s (%s)", self.mouse_dev.name, self.mouse_path)
            except Exception as e:
                logger.error("Could not open mouse %s: %s", self.mouse_path, e)

    def _close_devices(self, selector: selectors.DefaultSelector):
        """Unregister and close input devices."""
        for dev in [self.kbd_dev, self.mouse_dev]:
            if dev:
                try:
                    selector.unregister(dev)
                except Exception:
                    pass
                try:
                    dev.close()
                except Exception:
                    pass
        self.kbd_dev = None
        self.mouse_dev = None

    def _is_toggle_hotkey(self, event_code: int, event_val: int) -> bool:
        """Check if an event matches the configured hotkey trigger."""
        if event_val != 1:  # Only trigger on key down
            return False

        hotkey_config = config.get("hotkey", "scroll_lock")

        if hotkey_config == "scroll_lock":
            return event_code == e.KEY_SCROLLLOCK

        if hotkey_config == "ctrl_alt_s":
            # Requires Ctrl + Alt + S
            if event_code == e.KEY_S and (self._ctrl_down and self._alt_down):
                return True

        if hotkey_config == "right_alt":
            return event_code == e.KEY_RIGHTALT

        if hotkey_config == "pause":
            return event_code == e.KEY_PAUSE

        return False

    def _handle_keyboard_event(self, event: evdev.InputEvent):
        """Process keyboard event: hotkey matching, modifier tracking, HID forwarding."""
        if event.type != e.EV_KEY:
            return

        code = event.code
        val = event.value  # 0=release, 1=press, 2=repeat

        # Track modifier state for hotkey detection
        if code in (e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL):
            self._ctrl_down = (val != 0)
        elif code in (e.KEY_LEFTALT, e.KEY_RIGHTALT):
            self._alt_down = (val != 0)
        elif code in (e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT):
            self._shift_down = (val != 0)

        # Check for toggle hotkey
        if self._is_toggle_hotkey(code, val):
            logger.info("Hotkey detected! Toggling control mode.")
            self.toggle_control()
            return

        # If we are in REMOTE mode, forward keystroke to BLE server
        if self.current_control == CONTROL_REMOTE and self.ble_server:
            # Check if this key is a modifier bit
            if code in MODIFIER_MASKS:
                mask = MODIFIER_MASKS[code]
                if val != 0:
                    self.active_modifiers_mask |= mask
                else:
                    self.active_modifiers_mask &= ~mask
            else:
                # Regular key
                hid_key = EVDEV_TO_HID_KEY.get(code)
                if hid_key:
                    if val != 0:
                        self.pressed_keys.add(hid_key)
                    else:
                        self.pressed_keys.discard(hid_key)

            # Send 8-byte HID report
            self.ble_server.send_keyboard_report(
                self.active_modifiers_mask,
                list(self.pressed_keys),
            )
            if self.on_pulse:
                self.on_pulse()

    def _handle_mouse_event(self, event: evdev.InputEvent):
        """Process mouse movement, buttons, and frame-synced reporting on SYN_REPORT."""
        sensitivity = float(config.get("mouse_sensitivity", 1.0))

        if event.type == e.EV_REL:
            if event.code == e.REL_X:
                self.accum_dx += int(event.value * sensitivity)
                self.mouse_dirty = True
            elif event.code == e.REL_Y:
                self.accum_dy += int(event.value * sensitivity)
                self.mouse_dirty = True
            elif event.code == e.REL_WHEEL:
                self.accum_wheel += event.value
                self.mouse_dirty = True
            elif event.code == e.REL_HWHEEL:
                self.accum_hwheel += event.value
                self.mouse_dirty = True

        elif event.type == e.EV_KEY:
            btn_mask = MOUSE_BUTTON_MASKS.get(event.code, 0)
            if btn_mask:
                if event.value != 0:
                    self.active_mouse_buttons |= btn_mask
                else:
                    self.active_mouse_buttons &= ~btn_mask
                self.mouse_dirty = True

        elif event.type == e.EV_SYN and event.code == e.SYN_REPORT:
            if self.current_control == CONTROL_REMOTE and self.mouse_dirty and self.ble_server:
                self.ble_server.send_mouse_report(
                    self.active_mouse_buttons,
                    self.accum_dx,
                    self.accum_dy,
                    self.accum_wheel,
                    self.accum_hwheel,
                )
                self.accum_dx = 0
                self.accum_dy = 0
                self.accum_wheel = 0
                self.accum_hwheel = 0
                self.mouse_dirty = False
                if self.on_pulse:
                    self.on_pulse()

    def _run_loop(self):
        """Main selector polling loop reading evdev events."""
        selector = selectors.DefaultSelector()
        self._selector = selector
        self._open_devices(selector)

        logger.info("Input loop running...")
        while not self._stop_event.is_set():
            try:
                events = selector.select(timeout=0.1)
                for key, _ in events:
                    dev = key.fileobj
                    device_type = key.data
                    try:
                        for event in dev.read():
                            if device_type == "keyboard":
                                self._handle_keyboard_event(event)
                            elif device_type == "mouse":
                                self._handle_mouse_event(event)
                    except (BlockingIOError, OSError):
                        pass
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.debug("Input loop select exception: %s", e)
                time.sleep(0.05)

        self._close_devices(selector)
        selector.close()
        logger.info("Input loop terminated cleanly.")

    # ========================================================================
    # IPC Command Server (UNIX Domain Socket)
    # ========================================================================

    def _run_ipc_server(self):
        """Listen on UNIX domain socket for CLI requests (e.g. blueshift --toggle)."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if SOCKET_FILE.exists():
            try:
                SOCKET_FILE.unlink()
            except Exception:
                pass

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(str(SOCKET_FILE))
        server_sock.listen(5)
        server_sock.settimeout(0.5)

        logger.info("IPC socket listening at %s", SOCKET_FILE)
        while not self._stop_event.is_set():
            try:
                conn, _ = server_sock.accept()
                with conn:
                    data = conn.recv(1024).decode("utf-8").strip()
                    logger.info("Received IPC command: %s", data)
                    if data == "TOGGLE":
                        new_state = self.toggle_control()
                        conn.sendall(f"OK {new_state}\n".encode("utf-8"))
                    elif data == "LOCAL":
                        self.set_control(CONTROL_LOCAL)
                        conn.sendall(b"OK LOCAL\n")
                    elif data == "REMOTE":
                        self.set_control(CONTROL_REMOTE)
                        conn.sendall(b"OK REMOTE\n")
                    elif data == "STATUS":
                        conn.sendall(f"CONTROL: {self.current_control}\n".encode("utf-8"))
                    else:
                        conn.sendall(b"ERR UNKNOWN_COMMAND\n")
            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.debug("IPC server exception: %s", e)

        server_sock.close()
        if SOCKET_FILE.exists():
            try:
                SOCKET_FILE.unlink()
            except Exception:
                pass


def send_ipc_command(command: str) -> Optional[str]:
    """Send an IPC command to the currently running BlueShift instance."""
    if not SOCKET_FILE.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(str(SOCKET_FILE))
            sock.sendall(f"{command}\n".encode("utf-8"))
            response = sock.recv(1024).decode("utf-8").strip()
            return response
    except Exception as e:
        logger.debug("Failed to communicate with BlueShift IPC socket: %s", e)
        return None
