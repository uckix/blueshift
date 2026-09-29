"""
The BlueShift background service. One per PC, run by systemd (blueshift.service).
  server role: BLE HID peripheral + input grabbing + hotkey
  client role: keeps the LE link to the host alive
The GUI and CLI talk to it over IPC (see ipc.py).
"""

import signal
import logging
import threading
from typing import Dict, Any

from .config import config, HOTKEYS, ROLE_SERVER
from .ipc import IpcServer

logger = logging.getLogger("blueshift.daemon")


def _server_handler(ble, grabber):
    from .input_grabber import CONTROL_LOCAL, CONTROL_REMOTE, classify, unreadable_input_devices

    def status() -> Dict[str, Any]:
        kbds = mice = 0
        for dev in list(grabber.devices.values()):
            try:
                kind = classify(dev)
            except OSError:
                continue
            kbds += kind["is_keyboard"]
            mice += kind["is_mouse"]
        return {
            "ok": True,
            "role": ROLE_SERVER,
            "control": grabber.current_control,
            "switching": grabber._grab_deadline is not None,
            "ready": ble.ready,
            "ble": ble.is_running,
            "ble_error": ble.last_error,
            "keyboards": kbds,
            "mice": mice,
            "unreadable": unreadable_input_devices(),
            "host_name": config.get("host_name"),
            "client_name": config.get("client_name"),
            "hotkey": HOTKEYS.get(config.get("hotkey"), ""),
        }

    def handle(cmd: str) -> Dict[str, Any]:
        error = ""
        if cmd == "toggle":
            error = grabber.toggle_control()
        elif cmd == "local":
            error = grabber.set_control(CONTROL_LOCAL)
        elif cmd == "remote":
            error = grabber.set_control(CONTROL_REMOTE)
        elif cmd == "reload":
            config.load()
        elif cmd != "status":
            return {"ok": False, "error": f"unknown command: {cmd}"}
        if error:
            return {"ok": False, "error": error}
        if cmd in ("toggle", "local", "remote"):
            # Let the input thread apply the switch so the reply shows the new state.
            threading.Event().wait(0.15)
        return status()

    return handle


def _client_handler(link):
    def handle(cmd: str) -> Dict[str, Any]:
        if cmd == "connect":
            link.connect_now()
        elif cmd == "repair":
            link.connect_now(repair=True)
        elif cmd == "reload":
            config.load()
            link.connect_now()
        elif cmd != "status":
            return {"ok": False, "error": f"unknown command: {cmd}"}
        return {"ok": True, "role": "client", "host_name": config.get("host_name"),
                "client_name": config.get("client_name"), **link.status()}

    return handle


def run_daemon(role: str) -> int:
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    if role == ROLE_SERVER:
        from .ble_server import ble_server
        from .input_grabber import InputGrabber

        grabber = InputGrabber(ble_server)
        ble_server.on_ready_changed = lambda ready: None if ready else grabber.target_lost()
        ipc = IpcServer(_server_handler(ble_server, grabber))
        if not ipc.start():
            return 1
        grabber.start()
        logger.info("Server running. Hotkey: %s", HOTKEYS.get(config.get("hotkey")))
        while not stop.is_set():
            if not ble_server.is_running:
                ble_server.start()  # retried until Bluetooth is available
            stop.wait(5.0)
        grabber.stop()
        ble_server.stop()
    else:
        from .client_helper import client_link

        ipc = IpcServer(_client_handler(client_link))
        if not ipc.start():
            return 1
        client_link.start()
        logger.info("Client running, host %s (%s)", config.get("host_name"), config.get("host_mac"))
        stop.wait()
        client_link.stop()

    ipc.stop()
    logger.info("BlueShift daemon exited cleanly.")
    return 0
