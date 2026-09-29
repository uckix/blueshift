"""
Tiny JSON-over-UNIX-socket IPC between the daemon and the GUI / CLI.
Request: one line of text (command). Response: one line of JSON.
"""

import os
import json
import socket
import logging
import threading
from pathlib import Path
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("blueshift.ipc")


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if os.path.isdir(runtime):
        return Path(runtime) / "blueshift.sock"
    return Path.home() / ".config" / "blueshift" / "blueshift.sock"


def request(command: str, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    """Send a command to the running daemon. Returns None if it isn't running."""
    path = socket_path()
    if not path.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path))
            sock.sendall(command.encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode() or "null")
    except (OSError, ValueError) as err:
        logger.debug("IPC request %s failed: %s", command, err)
        return None


class IpcServer:
    """Serves commands on the socket; `handler(cmd) -> dict` runs on a worker thread."""

    def __init__(self, handler: Callable[[str], Dict[str, Any]]):
        self.handler = handler
        self.path = socket_path()
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()

    def start(self) -> bool:
        if request("status") is not None:
            logger.error("Another BlueShift daemon is already running (%s).", self.path)
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        threading.Thread(target=self._serve, name="BlueShift-IPC", daemon=True).start()
        logger.info("IPC listening at %s", self.path)
        return True

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    conn.settimeout(2.0)
                    cmd = conn.recv(1024).decode().strip().lower()
                    try:
                        reply = self.handler(cmd)
                    except Exception as err:  # never let one bad command kill the server
                        logger.exception("IPC handler error for %r", cmd)
                        reply = {"ok": False, "error": str(err)}
                    conn.sendall(json.dumps(reply).encode() + b"\n")
                except OSError as err:
                    logger.debug("IPC connection error: %s", err)

    def stop(self):
        self._stop.set()
        if self._sock:
            self._sock.close()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
