"""
BlueShift evdev input engine (host side).

Watches every physical keyboard and mouse, detects the switch hotkey, and while the
target is active holds an exclusive EVIOCGRAB on all of them and turns their events
into BLE HID reports.
"""

import os
import re
import glob
import time
import errno
import logging
import threading
import selectors
import subprocess
from typing import Optional, Dict, List, Set, Callable, Any

import evdev
from evdev import ecodes as e

from .hid_constants import EVDEV_TO_HID_KEY, MODIFIER_MASKS, MOUSE_BUTTON_MASKS
from .config import config

logger = logging.getLogger("blueshift.grabber")

CONTROL_LOCAL = "LOCAL"    # keyboard & mouse drive this PC
CONTROL_REMOTE = "REMOTE"  # keyboard & mouse drive the target over BLE

RESCAN_INTERVAL = 2.0      # seconds between hotplug scans
MOUSE_MIN_INTERVAL = 0.008  # coalesce motion to <=125 reports/s so BLE never queues up
GRAB_RELEASE_TIMEOUT = 1.5  # max wait for held keys to be released before grabbing

_CTRL = {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL}
_ALT = {e.KEY_LEFTALT, e.KEY_RIGHTALT}


def classify(dev: evdev.InputDevice) -> Dict[str, bool]:
    caps = dev.capabilities()
    keys = set(caps.get(e.EV_KEY, []))
    rel = set(caps.get(e.EV_REL, []))
    return {
        "is_keyboard": e.KEY_A in keys and e.KEY_SPACE in keys,
        "is_mouse": e.BTN_LEFT in keys and e.REL_X in rel and e.REL_Y in rel,
    }


def _excluded(name: str) -> bool:
    patterns = config.get("exclude_devices", []) or []
    return any(re.search(p, name, re.IGNORECASE) for p in patterns)


def list_input_devices() -> List[Dict[str, Any]]:
    """All readable evdev devices with keyboard/mouse classification."""
    devices = []
    for path in sorted(evdev.list_devices()):
        try:
            dev = evdev.InputDevice(path)
            info = {"path": path, "name": dev.name, "phys": dev.phys, **classify(dev)}
            info["excluded"] = _excluded(dev.name)
            devices.append(info)
            dev.close()
        except OSError as err:
            logger.debug("Error inspecting device %s: %s", path, err)
    return devices


def unreadable_input_devices() -> int:
    """How many /dev/input/event* nodes we can't open (permission problem hint)."""
    return sum(1 for p in glob.glob("/dev/input/event*") if not os.access(p, os.R_OK))


def send_desktop_notification(title: str, message: str, icon: str = "input-keyboard"):
    if not config.get("notifications_enabled", True):
        return

    def _notify():
        try:
            subprocess.run(["notify-send", "-a", "BlueShift", "-i", icon, "-t", "2000", title, message],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass

    threading.Thread(target=_notify, daemon=True).start()


class InputGrabber:
    """Owns all keyboards/mice, the hotkey, and LOCAL/REMOTE switching."""

    def __init__(self, ble_server_instance):
        self.ble_server = ble_server_instance
        self.current_control = CONTROL_LOCAL
        self.is_running = False

        self.devices: Dict[str, evdev.InputDevice] = {}   # path -> open device
        self._grabbed: Set[str] = set()
        self._ignored: Set[str] = set()                   # paths that aren't keyboards/mice

        # Physical key state across all keyboards (for hotkey chords)
        self._held: Set[int] = set()

        # Remote HID state
        self.active_modifiers_mask = 0
        self.pressed_keys: List[int] = []
        self.active_mouse_buttons = 0
        self._dx = 0.0
        self._dy = 0.0
        self._wheel = 0
        self._hwheel = 0
        self._mouse_dirty = False
        self._last_mouse_send = 0.0

        # Pending LOCAL -> REMOTE switch waiting for keys to be released
        self._grab_deadline: Optional[float] = None

        self.on_control_changed: Optional[Callable[[str], None]] = None

        self._selector: Optional[selectors.DefaultSelector] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        self._requests: List[str] = []

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> bool:
        if self.is_running:
            return True
        self._stop_event.clear()
        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, name="BlueShift-Input", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self.is_running = False
        self._stop_event.set()
        self._wake()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        with self._lock:
            self._go_local(notify=False)

    # ------------------------------------------------------------------ public control API (any thread)

    def set_control(self, new_state: str) -> str:
        """Request LOCAL or REMOTE. Returns an error message, or '' on success."""
        if new_state == CONTROL_REMOTE and not self.ble_server.ready:
            send_desktop_notification("BlueShift", f"{config.get('client_name')} is not connected",
                                      "dialog-warning")
            return "target not connected"
        if not self.is_running:
            # No input thread (e.g. tests): apply directly.
            with self._lock:
                self._apply_request(new_state)
            return ""
        with self._lock:
            self._requests.append(new_state)
        self._wake()
        return ""

    def toggle_control(self) -> str:
        pending = self._grab_deadline is not None
        target = CONTROL_LOCAL if (self.current_control == CONTROL_REMOTE or pending) else CONTROL_REMOTE
        return self.set_control(target)

    def target_lost(self):
        """Called when the BLE target disconnects: never leave the user with dead input."""
        if self.current_control == CONTROL_REMOTE or self._grab_deadline is not None:
            logger.warning("Target disconnected while active; returning control to this PC.")
            self.set_control(CONTROL_LOCAL)

    # ------------------------------------------------------------------ switching (input thread)

    def _apply_request(self, state: str):
        if state == CONTROL_REMOTE:
            if self.current_control != CONTROL_REMOTE and self._grab_deadline is None:
                # Wait until the hotkey (and anything else) is released, otherwise the
                # local desktop never sees those key-ups and modifiers get stuck.
                self._grab_deadline = time.monotonic() + GRAB_RELEASE_TIMEOUT
        else:
            self._grab_deadline = None
            if self.current_control == CONTROL_REMOTE:
                self._go_local(notify=True)

    def _keys_held(self) -> bool:
        for dev in self.devices.values():
            try:
                if dev.active_keys():
                    return True
            except OSError:
                pass
        return False

    def _maybe_finish_grab(self):
        if self._grab_deadline is None:
            return
        if self._keys_held() and time.monotonic() < self._grab_deadline:
            return
        self._grab_deadline = None
        if not self.ble_server.ready:
            return
        self._reset_remote_state()
        for path, dev in self.devices.items():
            self._grab(path, dev)
        self.current_control = CONTROL_REMOTE
        logger.info("Control -> REMOTE (%d devices grabbed)", len(self._grabbed))
        send_desktop_notification("BlueShift", f"Keyboard & mouse → {config.get('client_name')}",
                                  "network-wireless")
        self._emit_changed()

    def _go_local(self, notify: bool):
        was_remote = self.current_control == CONTROL_REMOTE
        self._reset_remote_state()
        try:
            self.ble_server.send_keyboard_report(0, [])
            self.ble_server.send_mouse_report(0, 0, 0, 0, 0)
        except Exception:
            pass
        for path in list(self._grabbed):
            dev = self.devices.get(path)
            if dev:
                try:
                    dev.ungrab()
                except OSError:
                    pass
        self._grabbed.clear()
        self.current_control = CONTROL_LOCAL
        if was_remote:
            logger.info("Control -> LOCAL")
            if notify:
                send_desktop_notification("BlueShift", f"Keyboard & mouse → {config.get('host_name')}",
                                          "computer")
            self._emit_changed()

    def _grab(self, path: str, dev: evdev.InputDevice):
        if path in self._grabbed:
            return
        try:
            dev.grab()
            self._grabbed.add(path)
        except OSError as err:
            logger.warning("Could not grab %s (%s): %s", dev.name, path, err)

    def _reset_remote_state(self):
        self.active_modifiers_mask = 0
        self.pressed_keys = []
        self.active_mouse_buttons = 0
        self._dx = self._dy = 0.0
        self._wheel = self._hwheel = 0
        self._mouse_dirty = False

    def _emit_changed(self):
        if self.on_control_changed:
            try:
                self.on_control_changed(self.current_control)
            except Exception:
                logger.exception("on_control_changed callback failed")

    # ------------------------------------------------------------------ hotplug

    def _rescan(self):
        present = set(evdev.list_devices())
        for path in list(self.devices):
            if path not in present:
                self._drop(path)
        self._ignored &= present
        for path in present:
            if path in self.devices or path in self._ignored:
                continue
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            kind = classify(dev)
            if not (kind["is_keyboard"] or kind["is_mouse"]) or _excluded(dev.name):
                dev.close()
                self._ignored.add(path)
                continue
            self.devices[path] = dev
            self._selector.register(dev, selectors.EVENT_READ, data=path)
            logger.info("Using %s: %s (%s)", "keyboard" if kind["is_keyboard"] else "mouse", dev.name, path)
            if self.current_control == CONTROL_REMOTE:
                self._grab(path, dev)

    def _drop(self, path: str, quiet: bool = False):
        dev = self.devices.pop(path, None)
        self._grabbed.discard(path)
        if dev is None:
            return
        if not quiet:
            logger.info("Device gone: %s (%s)", dev.name, path)
        try:
            self._selector.unregister(dev)
        except (KeyError, ValueError):
            pass
        try:
            dev.close()
        except OSError:
            pass

    # ------------------------------------------------------------------ event handling

    def _is_hotkey(self, code: int) -> bool:
        hotkey = config.get("hotkey", "ctrl_alt_s")
        if hotkey == "ctrl_alt_s":
            return code == e.KEY_S and bool(self._held & _CTRL) and bool(self._held & _ALT)
        return code == {"scroll_lock": e.KEY_SCROLLLOCK, "pause": e.KEY_PAUSE,
                        "right_alt": e.KEY_RIGHTALT}.get(hotkey)

    def _handle_event(self, ev: evdev.InputEvent):
        remote = self.current_control == CONTROL_REMOTE
        if ev.type == e.EV_KEY:
            if ev.code in MOUSE_BUTTON_MASKS:
                if remote:
                    mask = MOUSE_BUTTON_MASKS[ev.code]
                    before = self.active_mouse_buttons
                    if ev.value:
                        self.active_mouse_buttons |= mask
                    else:
                        self.active_mouse_buttons &= ~mask
                    if self.active_mouse_buttons != before:
                        self._flush_mouse(force=True)
                return
            if ev.value == 2:  # autorepeat: the target generates its own
                return
            if ev.value == 1:
                self._held.add(ev.code)
                if self._is_hotkey(ev.code):
                    logger.info("Hotkey pressed")
                    if remote or self._grab_deadline is not None:
                        self._apply_request(CONTROL_LOCAL)
                    elif self.ble_server.ready:
                        self._apply_request(CONTROL_REMOTE)
                    else:
                        send_desktop_notification("BlueShift", f"{config.get('client_name')} is not connected",
                                                  "dialog-warning")
                    return
            else:
                self._held.discard(ev.code)
            if remote:
                self._forward_key(ev.code, ev.value)
        elif ev.type == e.EV_REL and remote:
            scale = float(config.get("mouse_sensitivity", 1.0) or 1.0)
            if ev.code == e.REL_X:
                self._dx += ev.value * scale
            elif ev.code == e.REL_Y:
                self._dy += ev.value * scale
            elif ev.code == e.REL_WHEEL:
                self._wheel += ev.value
            elif ev.code == e.REL_HWHEEL:
                self._hwheel += ev.value
            else:
                return
            self._mouse_dirty = True
        elif ev.type == e.EV_SYN and ev.code == e.SYN_REPORT and remote and self._mouse_dirty:
            self._flush_mouse()

    def _forward_key(self, code: int, value: int):
        if code in MODIFIER_MASKS:
            if value:
                self.active_modifiers_mask |= MODIFIER_MASKS[code]
            else:
                self.active_modifiers_mask &= ~MODIFIER_MASKS[code]
        else:
            hid = EVDEV_TO_HID_KEY.get(code)
            if not hid:
                return
            if value and hid not in self.pressed_keys:
                self.pressed_keys.append(hid)
            elif not value and hid in self.pressed_keys:
                self.pressed_keys.remove(hid)
        self.ble_server.send_keyboard_report(self.active_modifiers_mask, self.pressed_keys)

    def _flush_mouse(self, force: bool = False):
        now = time.monotonic()
        if not force and now - self._last_mouse_send < MOUSE_MIN_INTERVAL:
            return  # the loop flushes it when the interval elapses
        dx, dy = int(self._dx), int(self._dy)
        self._dx -= dx  # keep sub-pixel remainder for smooth low sensitivity
        self._dy -= dy
        self.ble_server.send_mouse_report(self.active_mouse_buttons, dx, dy, self._wheel, self._hwheel)
        self._wheel = self._hwheel = 0
        self._mouse_dirty = False
        self._last_mouse_send = now

    # ------------------------------------------------------------------ main loop

    def _wake(self):
        try:
            os.write(self._wake_w, b"x")
        except OSError:
            pass

    def _run_loop(self):
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._wake_r, selectors.EVENT_READ, data=None)
        next_scan = 0.0
        logger.info("Input loop running")
        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                with self._lock:
                    if now >= next_scan:
                        self._rescan()
                        next_scan = now + RESCAN_INTERVAL
                    requests, self._requests = self._requests, []
                    for req in requests:
                        self._apply_request(req)

                timeout = max(0.0, next_scan - now)
                if self._grab_deadline is not None:
                    timeout = min(timeout, 0.02)
                if self._mouse_dirty:
                    timeout = min(timeout, max(0.0, self._last_mouse_send + MOUSE_MIN_INTERVAL - now))

                for key, _ in self._selector.select(timeout):
                    if key.data is None:
                        try:
                            os.read(self._wake_r, 512)
                        except BlockingIOError:
                            pass
                        continue
                    path = key.data
                    dev = self.devices.get(path)
                    if dev is None:
                        continue
                    try:
                        events = list(dev.read())
                    except BlockingIOError:
                        continue
                    except OSError as err:
                        # ENODEV: receiver unplugged / re-enumerated. Drop it; rescan reopens it.
                        if err.errno != errno.EAGAIN:
                            with self._lock:
                                self._drop(path)
                            next_scan = min(next_scan, time.monotonic() + 0.5)
                        continue
                    with self._lock:
                        for ev in events:
                            self._handle_event(ev)

                with self._lock:
                    if self._mouse_dirty and self.current_control == CONTROL_REMOTE:
                        self._flush_mouse()
                    self._maybe_finish_grab()
        except Exception:
            logger.exception("Input loop crashed")
        finally:
            with self._lock:
                self._go_local(notify=False)
                for path in list(self.devices):
                    self._drop(path, quiet=True)
            self._selector.close()
            logger.info("Input loop stopped")
