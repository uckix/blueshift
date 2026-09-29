"""
BlueShift System Tray Integration.
Provides status indicators, quick control switching, notifications, and desktop menu.
"""

import sys
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import pyqtSignal, QObject

from ..core.config import config
from ..core.input_grabber import CONTROL_LOCAL, CONTROL_REMOTE

logger = logging.getLogger("blueshift.tray")

ICON_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "blueshift.png"


class BlueShiftTray(QObject):
    """System tray controller for BlueShift."""

    # Signals
    switch_requested = pyqtSignal()
    show_window_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
        self.tray_icon = QSystemTrayIcon(parent_window)

        if ICON_PATH.exists():
            self.icon = QIcon(str(ICON_PATH))
        else:
            self.icon = QIcon.fromTheme("input-keyboard")
        self.tray_icon.setIcon(self.icon)

        self._build_menu()
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _build_menu(self):
        """Construct system tray context menu."""
        self.menu = QMenu()
        self.menu.setStyleSheet("""
            QMenu {
                background-color: #131b26;
                color: #f1f5f9;
                border: 1px solid #1e2b3c;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 7px 22px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #1e2b3c;
                color: #00d2ff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #1e2b3c;
                margin: 5px 10px;
            }
        """)

        # Title
        self.action_title = QAction("✦ BlueShift BLE KVM", self.menu)
        self.action_title.setEnabled(False)
        self.menu.addAction(self.action_title)

        # Control State
        self.action_status = QAction("Active: Parrot (Local)", self.menu)
        self.action_status.setEnabled(False)
        self.menu.addAction(self.action_status)

        self.menu.addSeparator()

        # Switch Action
        self.action_switch = QAction("⇄ Switch Control (Scroll Lock)", self.menu)
        self.action_switch.triggered.connect(self.switch_requested.emit)
        self.menu.addAction(self.action_switch)

        # Show Window
        self.action_show = QAction("Open BlueShift Dashboard", self.menu)
        self.action_show.triggered.connect(self.show_window_requested.emit)
        self.menu.addAction(self.action_show)

        self.menu.addSeparator()

        # Quit
        self.action_quit = QAction("Quit BlueShift", self.menu)
        self.action_quit.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(self.action_quit)

        self.tray_icon.setContextMenu(self.menu)

    def update_control_state(self, current_control: str):
        """Update displayed control state in tray tooltip and menu."""
        host_name = config.get("host_name", "Parrot")
        client_name = config.get("client_name", "ArchLab")

        if current_control == CONTROL_REMOTE:
            text = f"Active: {client_name} (Remote) ⚡"
            tooltip = f"BlueShift - Active: {client_name} (Remote)"
        else:
            text = f"Active: {host_name} (Local) 🖥"
            tooltip = f"BlueShift - Active: {host_name} (Local)"

        self.action_status.setText(text)
        self.tray_icon.setToolTip(tooltip)

    def show_message(self, title: str, message: str):
        """Display desktop notification through system tray."""
        if config.get("notifications_enabled", True):
            self.tray_icon.showMessage(
                title,
                message,
                self.icon,
                3000,
            )

    def _on_tray_activated(self, reason):
        """Handle clicks on the tray icon."""
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window_requested.emit()
