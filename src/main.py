"""
BlueShift entry point.

  blueshift                 open the window
  blueshift daemon          run the background service (systemd runs this)
  blueshift toggle|local|remote|status|connect|repair
  blueshift setup --role server|client [--peer MAC] [--peer-name NAME]
"""

import sys
import json
import socket
import argparse
import logging
from pathlib import Path

# Allow running as `python3 src/main.py`
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from src import __version__
from src.core.config import config, ROLE_SERVER, ROLE_CLIENT

COMMANDS = ("toggle", "local", "remote", "status", "connect", "repair")
# Flags from v1.0 (still used by old desktop files / scripts)
LEGACY_FLAGS = {"--toggle": ["toggle"], "--local": ["local"], "--remote": ["remote"],
                "--status": ["status"], "--gui": [], "--server": ["daemon", "--role", "server"],
                "--client": ["daemon", "--role", "client"]}


def run_gui() -> int:
    from src.gui.app import run
    return run()


def run_command(cmd: str) -> int:
    from src.core.ipc import request
    reply = request(cmd, timeout=3.0)
    if reply is None:
        print("BlueShift service is not running. Start it with: systemctl --user start blueshift")
        return 1
    print(json.dumps(reply, indent=2))
    return 0 if reply.get("ok") else 1


def run_setup(args) -> int:
    values = {"role": args.role,
              "client_name" if args.role == ROLE_CLIENT else "host_name": socket.gethostname()}
    if args.peer:
        values["host_mac" if args.role == ROLE_CLIENT else "client_mac"] = args.peer.upper()
        if args.role == ROLE_CLIENT and args.peer.upper() != (config.get("host_mac") or "").upper():
            values["le_paired"] = False
    if args.peer_name:
        values["host_name" if args.role == ROLE_CLIENT else "client_name"] = args.peer_name
    config.update(values)
    print(json.dumps(config.as_dict(), indent=2))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, arg in enumerate(argv):
        if arg in LEGACY_FLAGS:
            argv[i:i + 1] = LEGACY_FLAGS[arg]
            break

    parser = argparse.ArgumentParser(prog="blueshift", description="BlueShift — Bluetooth keyboard & mouse sharing")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"BlueShift {__version__}")
    sub = parser.add_subparsers(dest="command")
    d = sub.add_parser("daemon", help="run the background service")
    d.add_argument("--role", choices=[ROLE_SERVER, ROLE_CLIENT], help="override the configured role")
    s = sub.add_parser("setup", help="write the configuration non-interactively")
    s.add_argument("--role", choices=[ROLE_SERVER, ROLE_CLIENT], required=True)
    s.add_argument("--peer", help="Bluetooth MAC of the other PC")
    s.add_argument("--peer-name", help="display name of the other PC")
    for c in COMMANDS:
        sub.add_parser(c, help=f"send '{c}' to the running service")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

    if args.command == "daemon":
        from src.core.daemon import run_daemon
        return run_daemon(args.role or config.get("role"))
    if args.command == "setup":
        return run_setup(args)
    if args.command in COMMANDS:
        return run_command(args.command)
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
