"""
BlueShift Main Application Entry Point.
Supports modern PyQt6 GUI mode, headless CLI server daemon, and client reconnect daemon.
"""

import sys
import os
import signal
import argparse
import logging
import time
from pathlib import Path

# Ensure package directory is on python path
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from src.core.config import config
from src.core.ble_server import ble_server
from src.core.input_grabber import (
    InputGrabber, send_ipc_command,
    CONTROL_LOCAL, CONTROL_REMOTE
)
from src.core.client_helper import client_helper

logger = logging.getLogger("blueshift")


def setup_logging(verbose: bool = False):
    """Configure structured console logging."""
    level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=log_format, datefmt="%H:%M:%S")


def run_gui():
    """Launch the PyQt6 graphical desktop application."""
    from PyQt6.QtWidgets import QApplication
    from src.gui.main_window import MainWindow

    # Enable high DPI scaling
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("BlueShift")
    app.setOrganizationName("BlueShift")

    # Clean exit on Ctrl+C in terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    window = MainWindow()
    if not config.get("start_minimized", False):
        window.show()

    sys.exit(app.exec())


def run_server_cli():
    """Run headless Host / Server daemon in terminal or systemd."""
    logger.info("Starting BlueShift in Headless Server Daemon mode...")

    # Start BlueZ GATT Server
    if not ble_server.start():
        logger.error("Failed to start BlueZ GATT server. Exiting.")
        sys.exit(1)

    # Start Input Grabber
    grabber = InputGrabber(ble_server)
    grabber.start()

    logger.info("Host: %s, Target Client: %s", config.get("host_name"), config.get("client_name"))
    logger.info("Active Control: LOCAL (%s)", config.get("host_name"))
    logger.info("Press configured hotkey ([%s]) to switch control.", config.get("hotkey"))
    logger.info("Press Ctrl+C to terminate server daemon.")

    stop_event = False

    def handle_sig(sig, frame):
        nonlocal stop_event
        logger.info("Shutdown signal received...")
        stop_event = True

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    try:
        while not stop_event:
            time.sleep(0.5)
    finally:
        grabber.stop()
        ble_server.stop()
        logger.info("BlueShift Server daemon exited cleanly.")


def run_client_cli():
    """Run headless Target / Client auto-reconnect daemon."""
    logger.info("Starting BlueShift in Headless Client Daemon mode...")
    target_mac = config.get("host_mac", "D8:5B:27:23:42:AA")
    logger.info("Monitoring connection to Host: %s", target_mac)

    client_helper.start_auto_reconnect(target_mac)
    logger.info("Auto-reconnect daemon active. Press Ctrl+C to stop.")

    stop_event = False

    def handle_sig(sig, frame):
        nonlocal stop_event
        logger.info("Shutdown signal received...")
        stop_event = True

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    try:
        while not stop_event:
            time.sleep(1.0)
    finally:
        client_helper.stop_auto_reconnect()
        logger.info("BlueShift Client daemon exited cleanly.")


def handle_ipc_command(cmd: str):
    """Dispatch CLI command to running BlueShift instance via IPC socket."""
    response = send_ipc_command(cmd)
    if response:
        print(f"[BlueShift IPC] {response}")
        sys.exit(0)
    else:
        print(f"[BlueShift] Error: No running BlueShift instance found (or IPC socket unavailable).")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="blueshift",
        description="BlueShift — Bluetooth Low Energy KVM Switch for Linux",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gui", action="store_true", help="Launch PyQt6 GUI Dashboard (Default)")
    group.add_argument("--server", action="store_true", help="Run headless Host / Server daemon")
    group.add_argument("--client", action="store_true", help="Run headless Target / Client reconnect daemon")
    group.add_argument("--toggle", action="store_true", help="Toggle control between Local and Remote on running instance")
    group.add_argument("--local", action="store_true", help="Switch control to Local host on running instance")
    group.add_argument("--remote", action="store_true", help="Switch control to Remote client on running instance")
    group.add_argument("--status", action="store_true", help="Query status of running instance")

    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--version", action="version", version="BlueShift 1.0.0")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # IPC commands
    if args.toggle:
        handle_ipc_command("TOGGLE")
    elif args.local:
        handle_ipc_command("LOCAL")
    elif args.remote:
        handle_ipc_command("REMOTE")
    elif args.status:
        handle_ipc_command("STATUS")

    # Execution modes
    if args.server:
        run_server_cli()
    elif args.client:
        run_client_cli()
    else:
        # Default is GUI mode
        run_gui()


if __name__ == "__main__":
    main()
