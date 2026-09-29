"""
Shared D-Bus system bus + GLib main loop.
One loop thread per process; every BlueZ object and signal handler lives on it.
"""

import threading
import logging

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

logger = logging.getLogger("blueshift.bus")

_lock = threading.Lock()
_bus = None
_loop = None
_thread = None


def get_bus() -> dbus.SystemBus:
    """Return the process-wide system bus, starting the GLib loop thread once."""
    global _bus, _loop, _thread
    with _lock:
        if _bus is None:
            dbus.mainloop.glib.threads_init()
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            _bus = dbus.SystemBus()
            _loop = GLib.MainLoop()
            _thread = threading.Thread(target=_loop.run, name="BlueShift-GLib", daemon=True)
            _thread.start()
        return _bus


def stop_loop():
    if _loop is not None and _loop.is_running():
        _loop.quit()
