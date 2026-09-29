"""
BlueShift window. Deliberately tiny: it only shows the service's state and sends it
commands over IPC. All the real work happens in the background service.
"""

import sys
import socket
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QStackedWidget, QFormLayout, QToolButton, QSizePolicy,
)

from ..core import ipc
from ..core.config import config, HOTKEYS, ROLE_SERVER, ROLE_CLIENT

ICON_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "blueshift.png"

GREEN, AMBER, RED, GREY = "#22c55e", "#f59e0b", "#ef4444", "#8b93a1"

STYLE = """
QWidget { background: #16181d; color: #e8eaed; font-size: 14px; }
QLabel#title { font-size: 17px; font-weight: 700; }
QLabel#muted { color: #8b93a1; font-size: 13px; }
QLabel#status { font-size: 14px; }
QToolButton { border: none; font-size: 18px; color: #8b93a1; padding: 4px; }
QToolButton:hover { color: #e8eaed; }
QPushButton {
    background: #242830; border: 1px solid #2f343d; border-radius: 10px;
    padding: 9px 16px; font-weight: 600;
}
QPushButton:hover { border-color: #4b5261; }
QPushButton:disabled { color: #5c6370; }
QPushButton#primary { background: #3b82f6; border-color: #3b82f6; color: white; }
QPushButton#primary:hover { background: #2f6fd8; }
QPushButton#primary:disabled { background: #26324a; border-color: #26324a; color: #8b93a1; }
QPushButton#flat { background: transparent; border: none; color: #8b93a1; font-weight: 500; }
QPushButton#flat:hover { color: #e8eaed; }
QPushButton#pc {
    min-height: 118px; border-radius: 14px; font-size: 17px; text-align: center;
}
QPushButton#pc:checked { background: #1d3a6b; border: 2px solid #3b82f6; }
QComboBox { background: #242830; border: 1px solid #2f343d; border-radius: 8px; padding: 6px 10px; }
QComboBox QAbstractItemView { background: #242830; selection-background-color: #3b82f6; }
"""


def _label(text: str = "", name: str = "", wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _button(text: str, name: str = "") -> QPushButton:
    btn = QPushButton(text)
    if name:
        btn.setObjectName(name)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlueShift")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setStyleSheet(STYLE)
        self.setFixedWidth(420)
        self.state: Optional[Dict[str, Any]] = None

        self.pages = QStackedWidget()
        self.pages.addWidget(self._main_page())
        self.pages.addWidget(self._settings_page())
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 20)
        root.addWidget(self.pages)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(700)
        self.refresh()

    # ------------------------------------------------------------------ main page

    def _main_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.addWidget(_label("BlueShift", "title", wrap=False))
        head.addStretch()
        gear = QToolButton()
        gear.setText("⚙")
        gear.setToolTip("Settings")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.clicked.connect(self.open_settings)
        head.addWidget(gear)
        lay.addLayout(head)

        self.status = _label("", "status")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.status)

        # Server: two PCs, click one to send the keyboard & mouse there
        self.pc_row = QWidget()
        row = QHBoxLayout(self.pc_row)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(12)
        self.btn_here = _button("", "pc")
        self.btn_there = _button("", "pc")
        for b in (self.btn_here, self.btn_there):
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.addWidget(b)
        self.btn_here.clicked.connect(lambda: self.send("local"))
        self.btn_there.clicked.connect(lambda: self.send("remote"))
        lay.addWidget(self.pc_row)

        # Client / service-down: one action button + optional secondary
        self.btn_action = _button("", "primary")
        self.btn_action.clicked.connect(self.primary_action)
        lay.addWidget(self.btn_action)
        self.btn_secondary = _button("Re-pair", "flat")
        self.btn_secondary.setToolTip("Forget the old pairing and pair again over Bluetooth LE")
        self.btn_secondary.clicked.connect(lambda: self.send("repair"))
        lay.addWidget(self.btn_secondary, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.hint = _label("", "muted")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.hint)
        lay.addStretch()
        return page

    def refresh(self):
        if self.pages.currentIndex() != 0:
            return
        self.state = st = ipc.request("status", timeout=0.5)
        if st is None:
            self._render_down()
        elif st.get("role") == ROLE_SERVER:
            self._render_server(st)
        else:
            self._render_client(st)
        self.adjustSize()

    def _set_status(self, color: str, text: str):
        self.status.setText(f'<span style="color:{color}">●</span>&nbsp; {text}')

    def _render_down(self):
        self._set_status(RED, "BlueShift isn't running on this PC")
        self.pc_row.hide()
        self.btn_action.setText("Start BlueShift")
        self.btn_action.setEnabled(True)
        self.btn_action.show()
        self.btn_secondary.hide()
        self.hint.setText("")

    def _render_server(self, st: Dict[str, Any]):
        here, there = st.get("host_name") or "This PC", st.get("client_name") or "Other PC"
        remote = st.get("control") == "REMOTE"
        if not st.get("ble"):
            self._set_status(RED, f"Bluetooth problem: {st.get('ble_error') or 'starting…'}")
        elif st.get("ready"):
            self._set_status(GREEN, f"{there} is connected")
        else:
            self._set_status(AMBER, f"Waiting for {there} to connect…")
        if st.get("keyboards", 0) == 0 and st.get("unreadable"):
            self._set_status(RED, "Can't read the keyboard. Log out and back in, then retry.")

        self.btn_here.setText(f"{here}\nthis PC")
        self.btn_there.setText(f"{there}\nother PC")
        self.btn_here.setChecked(not remote)
        self.btn_there.setChecked(remote)
        self.btn_there.setEnabled(bool(st.get("ready")) or remote)
        self.pc_row.show()
        self.btn_action.hide()
        self.btn_secondary.hide()
        self.hint.setText(f"Switch anytime with  {st.get('hotkey')}")

    def _render_client(self, st: Dict[str, Any]):
        host = st.get("host_name") or "the host"
        state = st.get("state")
        self.pc_row.hide()
        self.btn_secondary.setVisible(state not in ("no_host",))
        if state == "connected":
            self._set_status(GREEN, f"Using {host}'s keyboard & mouse")
            self.btn_action.hide()
            self.hint.setText(f"Press the switch key on {host} to move them here and back.")
            return
        busy = state in ("searching", "pairing", "connecting")
        self._set_status(AMBER if busy else GREY, st.get("message") or f"Not connected to {host}")
        self.btn_action.setText("Choose host PC" if state == "no_host" else ("Connecting…" if busy else "Connect"))
        self.btn_action.setEnabled(not busy)
        self.btn_action.show()
        self.hint.setText("")

    def primary_action(self):
        if self.state is None:
            subprocess.Popen(["systemctl", "--user", "enable", "--now", "blueshift.service"])
            self._set_status(AMBER, "Starting…")
        elif self.state.get("state") == "no_host":
            self.open_settings()
        else:
            self.send("connect")

    def send(self, cmd: str):
        reply = ipc.request(cmd, timeout=3.0)
        if reply and not reply.get("ok"):
            self._set_status(AMBER, reply.get("error", "Couldn't do that"))
            QTimer.singleShot(1500, self.refresh)
            return
        self.refresh()

    # ------------------------------------------------------------------ settings page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(_label("Settings", "title"))

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.cmb_role = QComboBox()
        self.cmb_role.addItem("Shares its keyboard & mouse", ROLE_SERVER)
        self.cmb_role.addItem("Uses another PC's keyboard & mouse", ROLE_CLIENT)
        self.cmb_role.currentIndexChanged.connect(self._role_changed)
        form.addRow("This PC", self.cmb_role)

        self.cmb_peer = QComboBox()
        self.cmb_peer.setEditable(True)
        self.cmb_peer.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cmb_peer.lineEdit().setPlaceholderText("AA:BB:CC:DD:EE:FF")
        form.addRow("Other PC", self.cmb_peer)

        self.cmb_hotkey = QComboBox()
        for key, label in HOTKEYS.items():
            self.cmb_hotkey.addItem(label, key)
        self.lbl_hotkey = QLabel("Switch key")
        form.addRow(self.lbl_hotkey, self.cmb_hotkey)
        lay.addLayout(form)

        self.settings_note = _label("", "muted")
        lay.addWidget(self.settings_note)
        lay.addStretch()

        btns = QHBoxLayout()
        back = _button("Cancel")
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        save = _button("Save", "primary")
        save.clicked.connect(self.save_settings)
        btns.addWidget(back)
        btns.addWidget(save)
        lay.addLayout(btns)
        return page

    def open_settings(self):
        config.load()
        role = config.get("role")
        self.cmb_role.setCurrentIndex(0 if role == ROLE_SERVER else 1)
        self._fill_peers(config.get("client_mac") if role == ROLE_SERVER else config.get("host_mac"))
        self.cmb_hotkey.setCurrentIndex(max(0, self.cmb_hotkey.findData(config.get("hotkey"))))
        self._role_changed()
        self.settings_note.setText("")
        self.pages.setCurrentIndex(1)
        self.adjustSize()

    def _fill_peers(self, current_mac: str):
        from ..core.client_helper import known_devices
        self.cmb_peer.clear()
        for dev in known_devices():
            if dev["paired"] or dev["icon"] == "computer":
                self.cmb_peer.addItem(f"{dev['name']}  ({dev['address']})", dev)
        idx = next((i for i in range(self.cmb_peer.count())
                    if self.cmb_peer.itemData(i)["address"] == (current_mac or "").upper()), -1)
        if idx >= 0:
            self.cmb_peer.setCurrentIndex(idx)
        else:
            self.cmb_peer.setEditText(current_mac or "")

    def _role_changed(self):
        server = self.cmb_role.currentData() == ROLE_SERVER
        self.cmb_hotkey.setVisible(server)
        self.lbl_hotkey.setVisible(server)

    def _selected_peer(self):
        text = self.cmb_peer.currentText().strip()
        data = self.cmb_peer.currentData()
        if data and text == self.cmb_peer.itemText(self.cmb_peer.currentIndex()):
            return data["address"], data["name"]
        mac = text.upper()
        return mac, None

    def save_settings(self):
        role = self.cmb_role.currentData()
        mac, name = self._selected_peer()
        if mac and len(mac.split(":")) != 6:
            self.settings_note.setText("That doesn't look like a Bluetooth address (AA:BB:CC:DD:EE:FF).")
            return
        mac_key, name_key = ("client_mac", "client_name") if role == ROLE_SERVER else ("host_mac", "host_name")
        restart = role != config.get("role") or mac != (config.get(mac_key) or "").upper()
        values = {"role": role, mac_key: mac, "hotkey": self.cmb_hotkey.currentData()}
        if name:
            values[name_key] = name
        if role != config.get("role"):
            values["client_name" if role == ROLE_CLIENT else "host_name"] = socket.gethostname()
        if role == ROLE_CLIENT and mac != (config.get("host_mac") or "").upper():
            values["le_paired"] = False
        config.update(values)
        if restart:
            subprocess.Popen(["systemctl", "--user", "restart", "blueshift.service"])
        else:
            ipc.request("reload")
        self.pages.setCurrentIndex(0)
        QTimer.singleShot(300, self.refresh)


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("BlueShift")
    app.setDesktopFileName("blueshift")
    win = Window()
    win.show()
    return app.exec()
