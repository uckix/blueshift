"""
BlueShift Main GUI Window (PyQt6).
Modern Dark Cyber UI with Host/Server controls, Target/Client dashboard, and Settings.
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QSlider, QCheckBox,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QTextEdit, QProgressBar, QMessageBox, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QBrush, QPen, QFont

from ..core.config import config, CONFIG_DIR
from ..core.ble_server import ble_server
from ..core.input_grabber import (
    InputGrabber, list_input_devices, auto_detect_devices,
    CONTROL_LOCAL, CONTROL_REMOTE, send_ipc_command
)
from ..core.client_helper import client_helper
from .style import apply_theme
from .tray import BlueShiftTray

logger = logging.getLogger("blueshift.gui")

ICON_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "blueshift.png"


class HeartbeatPulseWidget(QWidget):
    """Visual glowing LED that pulses brightly whenever input events are forwarded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self._glow_intensity = 0.0
        self._color = QColor("#00d2ff")

        self._decay_timer = QTimer(self)
        self._decay_timer.setInterval(30)
        self._decay_timer.timeout.connect(self._decay)

    def trigger(self, is_remote: bool = True):
        self._color = QColor("#10b981") if is_remote else QColor("#00d2ff")
        self._glow_intensity = 1.0
        self.update()
        if not self._decay_timer.isActive():
            self._decay_timer.start()

    def _decay(self):
        self._glow_intensity = max(0.0, self._glow_intensity - 0.1)
        self.update()
        if self._glow_intensity <= 0.01:
            self._decay_timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center_x = self.width() / 2
        center_y = self.height() / 2

        # Inactive base circle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#1e293b")))
        painter.drawEllipse(int(center_x - 6), int(center_y - 6), 12, 12)

        # Glowing pulse
        if self._glow_intensity > 0.05:
            glow_color = QColor(self._color)
            glow_color.setAlphaF(min(1.0, self._glow_intensity * 0.4))
            painter.setBrush(QBrush(glow_color))
            painter.drawEllipse(int(center_x - 11), int(center_y - 11), 22, 22)

            core_color = QColor(self._color)
            core_color.setAlphaF(min(1.0, self._glow_intensity))
            painter.setBrush(QBrush(core_color))
            painter.drawEllipse(int(center_x - 5), int(center_y - 5), 10, 10)
        painter.end()


class MainWindow(QMainWindow):
    """BlueShift Desktop Application Main Window."""

    # Thread-safe Qt signals
    control_switched = pyqtSignal(str)
    stats_updated = pyqtSignal(int, int)
    connection_changed = pyqtSignal(bool, object)
    pulse_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlueShift — Bluetooth Low Energy KVM")
        self.setMinimumSize(920, 680)
        self.resize(960, 720)

        # Set Window Icon
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        # Core Engines
        self.grabber = InputGrabber(ble_server)

        # Wire Core Signals to Qt Signals
        self.grabber.on_control_changed = lambda state: self.control_switched.emit(state)
        self.grabber.on_pulse = lambda: self.pulse_triggered.emit()
        ble_server.on_stats_updated = lambda kb, m: self.stats_updated.emit(kb, m)
        ble_server.on_connection_changed = lambda conn, dev: self.connection_changed.emit(conn, dev)

        # Connect Qt Signals to GUI Slots
        self.control_switched.connect(self._on_control_switched)
        self.stats_updated.connect(self._on_stats_updated)
        self.connection_changed.connect(self._on_connection_changed)
        self.pulse_triggered.connect(self._on_pulse)

        # Setup GUI Elements
        self._init_ui()
        apply_theme(self)

        # System Tray Integration
        self.tray = BlueShiftTray(self)
        self.tray.switch_requested.connect(self._toggle_control_action)
        self.tray.show_window_requested.connect(self._restore_window)
        self.tray.quit_requested.connect(self._quit_application)

        # Periodic refresh timers
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1500)
        self._status_timer.timeout.connect(self._periodic_status_check)
        self._status_timer.start()

        # Configure initial view and startup based on configured role
        if config.get("role") == "client":
            self.tab_widget.setCurrentIndex(1)
            self.badge_server.setVisible(False)
            QTimer.singleShot(300, self._refresh_client_devices_table)
            QTimer.singleShot(600, self._check_virtual_devices)
        else:
            self.tab_widget.setCurrentIndex(0)
            if config.get("server_autostart", True):
                QTimer.singleShot(500, self._start_server)

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(14)

        # 1. Header Bar
        main_layout.addLayout(self._create_header_bar())

        # 2. Main Tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self._create_server_tab(), "🖥  Host / Server Mode")
        self.tab_widget.addTab(self._create_client_tab(), "📡  Target / Client Mode")
        self.tab_widget.addTab(self._create_settings_tab(), "⚙  Settings & Diagnostics")
        main_layout.addWidget(self.tab_widget)

        # 3. Footer Status Line
        main_layout.addLayout(self._create_footer_bar())

    # ========================================================================
    # Header Bar
    # ========================================================================

    def _create_header_bar(self) -> QHBoxLayout:
        header_layout = QHBoxLayout()

        # Logo & App Title
        logo_label = QLabel()
        if ICON_PATH.exists():
            pixmap = QPixmap(str(ICON_PATH)).scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
        header_layout.addWidget(logo_label)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(1)

        title_label = QLabel("BLUESHIFT")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #00d2ff; font-weight: 800;")
        title_layout.addWidget(title_label)

        subtitle_label = QLabel("Bluetooth Low Energy KVM Switch • Dual Machine Controller")
        subtitle_label.setStyleSheet("color: #64748b; font-size: 11px;")
        title_layout.addWidget(subtitle_label)

        header_layout.addLayout(title_layout)
        header_layout.addStretch()

        # Live Badges
        self.badge_server = QLabel("● SERVER RUNNING")
        self.badge_server.setStyleSheet("background-color: #064e3b; color: #34d399; border: 1px solid #059669; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
        header_layout.addWidget(self.badge_server)

        self.badge_client = QLabel("● ARCHLAB CONNECTED")
        self.badge_client.setStyleSheet("background-color: #0c4a6e; color: #38bdf8; border: 1px solid #0284c7; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
        header_layout.addWidget(self.badge_client)

        return header_layout

    # ========================================================================
    # Tab 1: Host / Server Mode
    # ========================================================================

    def _create_server_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Row 1: Server Control & BlueZ Info Card
        srv_card = QFrame()
        srv_card.setProperty("class", "CardFrame")
        srv_layout = QHBoxLayout(srv_card)

        srv_info_layout = QVBoxLayout()
        self.lbl_adapter = QLabel("Adapter: Querying...")
        self.lbl_adapter.setStyleSheet("color: #f1f5f9; font-weight: 600; font-size: 13px;")
        srv_info_layout.addWidget(self.lbl_adapter)

        self.lbl_client_info = QLabel("Remote Client: Checking connection...")
        self.lbl_client_info.setStyleSheet("color: #94a3b8; font-size: 12px;")
        srv_info_layout.addWidget(self.lbl_client_info)
        srv_layout.addLayout(srv_info_layout)
        srv_layout.addStretch()

        self.btn_toggle_server = QPushButton("Stop Server")
        self.btn_toggle_server.setProperty("class", "DangerButton")
        self.btn_toggle_server.setFixedWidth(140)
        self.btn_toggle_server.clicked.connect(self._toggle_server_clicked)
        srv_layout.addWidget(self.btn_toggle_server)

        layout.addWidget(srv_card)

        # Row 2: Big Interactive "Active Control" Switch Card
        control_card = QFrame()
        control_card.setProperty("class", "CardFrame")
        control_layout = QVBoxLayout(control_card)

        ctrl_title = QLabel("ACTIVE INPUT CONTROL")
        ctrl_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        control_layout.addWidget(ctrl_title)

        switch_row = QHBoxLayout()

        # Left: Local Machine (Parrot)
        self.card_local = QFrame()
        self.card_local.setProperty("class", "ActiveCardParrot")
        self.card_local.setMinimumHeight(130)
        local_vbox = QVBoxLayout(self.card_local)
        local_vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_local_name = QLabel(config.get("host_name", "PARROT").upper())
        self.lbl_local_name.setStyleSheet("font-size: 20px; font-weight: 800; color: #ffffff;")
        local_vbox.addWidget(self.lbl_local_name, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_local_sub = QLabel("Host System (Local)")
        self.lbl_local_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
        local_vbox.addWidget(self.lbl_local_sub, alignment=Qt.AlignmentFlag.AlignCenter)

        self.badge_local_state = QLabel("● ACTIVE CONTROL")
        self.badge_local_state.setStyleSheet("color: #00d2ff; font-weight: 700; font-size: 11px;")
        local_vbox.addWidget(self.badge_local_state, alignment=Qt.AlignmentFlag.AlignCenter)
        switch_row.addWidget(self.card_local, 1)

        # Center: Big Switch Button & Arrow
        center_vbox = QVBoxLayout()
        center_vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_big_switch = QPushButton("⇄  SWITCH CONTROL")
        self.btn_big_switch.setProperty("class", "BigSwitchButton")
        self.btn_big_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_big_switch.clicked.connect(self._toggle_control_action)
        center_vbox.addWidget(self.btn_big_switch, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_hotkey_hint = QLabel("Hotkey: [ Scroll Lock ]")
        self.lbl_hotkey_hint.setStyleSheet("color: #94a3b8; font-size: 11px; margin-top: 4px;")
        center_vbox.addWidget(self.lbl_hotkey_hint, alignment=Qt.AlignmentFlag.AlignCenter)
        switch_row.addLayout(center_vbox)

        # Right: Remote Machine (ArchLab)
        self.card_remote = QFrame()
        self.card_remote.setProperty("class", "InactiveCard")
        self.card_remote.setMinimumHeight(130)
        remote_vbox = QVBoxLayout(self.card_remote)
        remote_vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_remote_name = QLabel(config.get("client_name", "ARCHLAB").upper())
        self.lbl_remote_name.setStyleSheet("font-size: 20px; font-weight: 800; color: #ffffff;")
        remote_vbox.addWidget(self.lbl_remote_name, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_remote_sub = QLabel("Target System (BLE)")
        self.lbl_remote_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
        remote_vbox.addWidget(self.lbl_remote_sub, alignment=Qt.AlignmentFlag.AlignCenter)

        self.badge_remote_state = QLabel("STANDBY")
        self.badge_remote_state.setStyleSheet("color: #64748b; font-weight: 700; font-size: 11px;")
        remote_vbox.addWidget(self.badge_remote_state, alignment=Qt.AlignmentFlag.AlignCenter)
        switch_row.addWidget(self.card_remote, 1)

        control_layout.addLayout(switch_row)
        layout.addWidget(control_card)

        # Row 3: Hardware Input Device Selection Card
        dev_card = QFrame()
        dev_card.setProperty("class", "CardFrame")
        dev_layout = QGridLayout(dev_card)
        dev_layout.setVerticalSpacing(10)
        dev_layout.setHorizontalSpacing(14)

        dev_title = QLabel("HARDWARE INPUT DEVICES (EVDEV)")
        dev_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        dev_layout.addWidget(dev_title, 0, 0, 1, 3)

        # Keyboard selector
        dev_layout.addWidget(QLabel("Keyboard:"), 1, 0)
        self.combo_keyboard = QComboBox()
        dev_layout.addWidget(self.combo_keyboard, 1, 1)

        # Mouse selector
        dev_layout.addWidget(QLabel("Mouse:"), 2, 0)
        self.combo_mouse = QComboBox()
        dev_layout.addWidget(self.combo_mouse, 2, 1)

        # Auto-detect button
        btn_autodetect = QPushButton("⚡ Auto-Detect")
        btn_autodetect.setFixedWidth(120)
        btn_autodetect.clicked.connect(self._auto_detect_devices_clicked)
        dev_layout.addWidget(btn_autodetect, 1, 2, 2, 1)

        # Hotkey selector
        dev_layout.addWidget(QLabel("Toggle Hotkey:"), 3, 0)
        self.combo_hotkey = QComboBox()
        self.combo_hotkey.addItem("Scroll Lock (Recommended)", "scroll_lock")
        self.combo_hotkey.addItem("Ctrl + Alt + S", "ctrl_alt_s")
        self.combo_hotkey.addItem("Right Alt", "right_alt")
        self.combo_hotkey.addItem("Pause / Break", "pause")
        self.combo_hotkey.currentIndexChanged.connect(self._on_hotkey_changed)
        dev_layout.addWidget(self.combo_hotkey, 3, 1)

        layout.addWidget(dev_card)

        # Row 4: Live Telemetry & Heartbeat Pulse Card
        pulse_card = QFrame()
        pulse_card.setProperty("class", "CardFrame")
        pulse_layout = QHBoxLayout(pulse_card)

        self.heartbeat_widget = HeartbeatPulseWidget()
        pulse_layout.addWidget(self.heartbeat_widget)

        self.lbl_pulse_text = QLabel("Live Forwarding Pulse")
        self.lbl_pulse_text.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")
        pulse_layout.addWidget(self.lbl_pulse_text)

        pulse_layout.addStretch()

        self.lbl_packets_kb = QLabel("Keyboard Packets: 0")
        self.lbl_packets_kb.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        pulse_layout.addWidget(self.lbl_packets_kb)

        pulse_layout.addSpacing(20)

        self.lbl_packets_mouse = QLabel("Mouse Packets: 0")
        self.lbl_packets_mouse.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        pulse_layout.addWidget(self.lbl_packets_mouse)

        layout.addWidget(pulse_card)

        # Populate device lists
        self._populate_input_devices()

        return widget

    # ========================================================================
    # Tab 2: Target / Client Mode
    # ========================================================================

    def _create_client_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Card 1: Discovery & Pairing
        scan_card = QFrame()
        scan_card.setProperty("class", "CardFrame")
        scan_layout = QVBoxLayout(scan_card)

        scan_header = QHBoxLayout()
        scan_title = QLabel("BLUETOOTH HOST SCANNER & PAIRING")
        scan_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        scan_header.addWidget(scan_title)
        scan_header.addStretch()

        self.btn_scan = QPushButton("🔍 Scan for Host (BLE)")
        self.btn_scan.setProperty("class", "PrimaryButton")
        self.btn_scan.clicked.connect(self._scan_bluetooth_clicked)
        scan_header.addWidget(self.btn_scan)
        scan_layout.addLayout(scan_header)

        # Devices Table
        self.table_devices = QTableWidget(0, 5)
        self.table_devices.setHorizontalHeaderLabels(["Name / Alias", "MAC Address", "Type", "Status", "Action"])
        self.table_devices.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_devices.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_devices.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_devices.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_devices.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table_devices.setColumnWidth(4, 110)
        self.table_devices.setMinimumHeight(150)
        scan_layout.addWidget(self.table_devices)

        layout.addWidget(scan_card)

        # Card 2: Virtual HID Device Detection
        vdev_card = QFrame()
        vdev_card.setProperty("class", "CardFrame")
        vdev_layout = QVBoxLayout(vdev_card)

        vdev_header = QHBoxLayout()
        vdev_title = QLabel("VIRTUAL INPUT STATUS (RECEIVING END)")
        vdev_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        vdev_header.addWidget(vdev_title)
        vdev_header.addStretch()

        btn_refresh_vdev = QPushButton("↻ Refresh Devices")
        btn_refresh_vdev.clicked.connect(self._check_virtual_devices)
        vdev_header.addWidget(btn_refresh_vdev)
        vdev_layout.addLayout(vdev_header)

        vdev_row = QHBoxLayout()

        self.lbl_vdev_kb = QLabel("Keyboard: Checking...")
        self.lbl_vdev_kb.setStyleSheet("color: #e2e8f0; font-size: 13px; padding: 6px;")
        vdev_row.addWidget(self.lbl_vdev_kb)

        self.lbl_vdev_mouse = QLabel("Mouse: Checking...")
        self.lbl_vdev_mouse.setStyleSheet("color: #e2e8f0; font-size: 13px; padding: 6px;")
        vdev_row.addWidget(self.lbl_vdev_mouse)

        vdev_layout.addLayout(vdev_row)
        layout.addWidget(vdev_card)

        # Card 3: Link Health Dashboard & Auto-Reconnect
        health_card = QFrame()
        health_card.setProperty("class", "CardFrame")
        health_layout = QGridLayout(health_card)
        health_layout.setVerticalSpacing(10)

        health_title = QLabel("CONNECTION HEALTH & AUTO-RECONNECT")
        health_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        health_layout.addWidget(health_title, 0, 0, 1, 3)

        self.lbl_latency = QLabel("Latency: < 8 ms (Ultra-Low Latency BLE)")
        self.lbl_latency.setStyleSheet("color: #38bdf8; font-weight: 600;")
        health_layout.addWidget(self.lbl_latency, 1, 0)

        self.lbl_signal = QLabel("Signal Quality: Excellent (-60 dBm)")
        self.lbl_signal.setStyleSheet("color: #34d399; font-weight: 600;")
        health_layout.addWidget(self.lbl_signal, 1, 1)

        self.lbl_battery = QLabel("Reported Battery: 100%")
        self.lbl_battery.setStyleSheet("color: #f1f5f9; font-weight: 600;")
        health_layout.addWidget(self.lbl_battery, 1, 2)

        # Auto-reconnect toggle
        self.chk_auto_reconnect = QCheckBox("Enable Background Auto-Reconnect Daemon")
        self.chk_auto_reconnect.setChecked(config.get("auto_reconnect", True))
        self.chk_auto_reconnect.toggled.connect(self._on_auto_reconnect_toggled)
        health_layout.addWidget(self.chk_auto_reconnect, 2, 0, 1, 2)

        self.btn_systemd_install = QPushButton("Install systemd Service")
        self.btn_systemd_install.clicked.connect(self._install_client_service)
        health_layout.addWidget(self.btn_systemd_install, 2, 2)

        layout.addWidget(health_card)

        # Initial device populate for table
        self._refresh_client_devices_table()
        self._check_virtual_devices()

        return widget

    # ========================================================================
    # Tab 3: Settings & Diagnostics
    # ========================================================================

    def _create_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Settings Card
        cfg_card = QFrame()
        cfg_card.setProperty("class", "CardFrame")
        cfg_layout = QGridLayout(cfg_card)
        cfg_layout.setVerticalSpacing(10)

        cfg_title = QLabel("SYSTEM CONFIGURATION")
        cfg_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        cfg_layout.addWidget(cfg_title, 0, 0, 1, 2)

        # Host label
        cfg_layout.addWidget(QLabel("Host PC Name:"), 1, 0)
        self.txt_host_name = QLineEdit(config.get("host_name", "Parrot"))
        cfg_layout.addWidget(self.txt_host_name, 1, 1)

        # Client label
        cfg_layout.addWidget(QLabel("Client PC Name:"), 2, 0)
        self.txt_client_name = QLineEdit(config.get("client_name", "ArchLab"))
        cfg_layout.addWidget(self.txt_client_name, 2, 1)

        # Target MAC
        cfg_layout.addWidget(QLabel("Client Bluetooth MAC:"), 3, 0)
        self.txt_client_mac = QLineEdit(config.get("client_mac", "90:E8:68:95:76:DC"))
        cfg_layout.addWidget(self.txt_client_mac, 3, 1)

        # Checkboxes
        self.chk_notifs = QCheckBox("Show desktop notifications on switch")
        self.chk_notifs.setChecked(config.get("notifications_enabled", True))
        cfg_layout.addWidget(self.chk_notifs, 4, 0, 1, 2)

        self.chk_boot = QCheckBox("Launch BlueShift on system startup")
        self.chk_boot.setChecked(config.get("start_on_boot", False))
        cfg_layout.addWidget(self.chk_boot, 5, 0, 1, 2)

        btn_save_cfg = QPushButton("💾 Save Settings")
        btn_save_cfg.setProperty("class", "PrimaryButton")
        btn_save_cfg.clicked.connect(self._save_settings)
        cfg_layout.addWidget(btn_save_cfg, 6, 1, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(cfg_card)

        # Event Log Card
        log_card = QFrame()
        log_card.setProperty("class", "CardFrame")
        log_layout = QVBoxLayout(log_card)

        log_header = QHBoxLayout()
        log_title = QLabel("REAL-TIME DIAGNOSTIC LOG")
        log_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        log_header.addWidget(log_title)
        log_header.addStretch()

        btn_clear_log = QPushButton("Clear")
        btn_clear_log.setFixedWidth(70)
        btn_clear_log.clicked.connect(lambda: self.txt_log.clear())
        log_header.addWidget(btn_clear_log)
        log_layout.addLayout(log_header)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(140)
        log_layout.addWidget(self.txt_log)

        layout.addWidget(log_card)
        self._append_log("BlueShift GUI initialized.")

        return widget

    # ========================================================================
    # Footer Bar
    # ========================================================================

    def _create_footer_bar(self) -> QHBoxLayout:
        footer = QHBoxLayout()

        self.lbl_footer_status = QLabel("System Status: Ready. BlueZ GATT Server active on /org/bluez/hci0.")
        self.lbl_footer_status.setStyleSheet("color: #64748b; font-size: 11px;")
        footer.addWidget(self.lbl_footer_status)

        footer.addStretch()

        lbl_version = QLabel("BlueShift v1.0.0 (GATT HID Switch)")
        lbl_version.setStyleSheet("color: #475569; font-size: 11px;")
        footer.addWidget(lbl_version)

        return footer

    # ========================================================================
    # Logic & Event Handlers
    # ========================================================================

    def _toggle_control_action(self):
        """Toggle active control between Local and Remote either via IPC daemon or local grabber."""
        status_resp = send_ipc_command("TOGGLE")
        if status_resp and "OK" in status_resp:
            new_state = CONTROL_REMOTE if "REMOTE" in status_resp else CONTROL_LOCAL
            self.grabber.current_control = new_state
            self._on_control_switched(new_state)
            self._on_pulse()
        else:
            self.grabber.toggle_control()

    def _start_server(self):
        """Start the BlueZ BLE server and input grabber."""
        # Check if background daemon is already active
        status_resp = send_ipc_command("STATUS")
        if status_resp:
            self._append_log("BlueShift background daemon is active. Connected via IPC.")
            self.badge_server.setText("● DAEMON ACTIVE")
            self.badge_server.setStyleSheet("background-color: #064e3b; color: #34d399; border: 1px solid #059669; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
            self.btn_toggle_server.setText("Daemon Active")
            self.btn_toggle_server.setEnabled(False)
            self._update_adapter_display()
            if "REMOTE" in status_resp:
                self._on_control_switched(CONTROL_REMOTE)
            else:
                self._on_control_switched(CONTROL_LOCAL)
            return

        self._append_log("Starting BLE GATT Peripheral Server...")
        success = ble_server.start()
        if success:
            self._append_log("GATT HID Server and LE Advertising registered.")
            self.btn_toggle_server.setText("Stop Server")
            self.btn_toggle_server.setProperty("class", "DangerButton")
            self.btn_toggle_server.setStyleSheet("")  # re-evaluate style
            self.badge_server.setText("● SERVER RUNNING")
            self.badge_server.setStyleSheet("background-color: #064e3b; color: #34d399; border: 1px solid #059669; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")

            # Start input grabber
            kbd_dev = self.combo_keyboard.currentData()
            mouse_dev = self.combo_mouse.currentData()
            self.grabber.start(kbd_dev, mouse_dev)
            self._append_log(f"Input grabber listening on {self.grabber.kbd_path} and {self.grabber.mouse_path}")
        else:
            self._append_log("Warning: BlueZ BLE server failed to start. Running in local mode.")
            self.badge_server.setText("● SERVER STOPPED")
            self.badge_server.setStyleSheet("background-color: #450a0a; color: #f87171; border: 1px solid #b91c1c; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
            self.btn_toggle_server.setText("Start Server")
            self.btn_toggle_server.setProperty("class", "SuccessButton")

        self._update_adapter_display()

    def _stop_server(self):
        """Stop BLE server and input grabber."""
        if not ble_server.is_running:
            return
        self._append_log("Stopping BLE GATT Server...")
        self.grabber.stop()
        ble_server.stop()
        self.btn_toggle_server.setText("Start Server")
        self.btn_toggle_server.setProperty("class", "SuccessButton")
        self.btn_toggle_server.setStyleSheet("")
        self.badge_server.setText("● SERVER STOPPED")
        self.badge_server.setStyleSheet("background-color: #450a0a; color: #f87171; border: 1px solid #b91c1c; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
        self._append_log("BLE GATT Server stopped.")

    def _toggle_server_clicked(self):
        if ble_server.is_running:
            self._stop_server()
        else:
            self._start_server()

    def _update_adapter_display(self):
        info = ble_server.get_adapter_info()
        self.lbl_adapter.setText(f"Adapter: {info['alias']} ({info['address']}) — {'Powered ON' if info['powered'] else 'Powered OFF'}")

        if ble_server.connected_device:
            dev = ble_server.connected_device
            self.lbl_client_info.setText(f"Connected: {dev['alias']} ({dev['address']}) • Paired: {'Yes' if dev['paired'] else 'No'} • RSSI: {dev['rssi']} dBm")
            self.badge_client.setText(f"● {dev['alias'].upper()} CONNECTED")
            self.badge_client.setStyleSheet("background-color: #064e3b; color: #34d399; border: 1px solid #059669; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
        else:
            self.lbl_client_info.setText("Remote Client: Not Connected (Advertising on BLE)")
            self.badge_client.setText("● WAITING CLIENT")
            self.badge_client.setStyleSheet("background-color: #172554; color: #60a5fa; border: 1px solid #2563eb; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")

    def _populate_input_devices(self):
        """Populate keyboard and mouse comboboxes with available evdev devices."""
        self.combo_keyboard.clear()
        self.combo_mouse.clear()

        devices = list_input_devices()
        cur_kbd = config.get("keyboard_device")
        cur_mouse = config.get("mouse_device")

        kbd_selected = False
        mouse_selected = False

        for d in devices:
            label = f"{d['name']} ({d['path']})"
            if d["is_keyboard"]:
                self.combo_keyboard.addItem(label, d["path"])
                if cur_kbd == d["path"]:
                    self.combo_keyboard.setCurrentIndex(self.combo_keyboard.count() - 1)
                    kbd_selected = True

            if d["is_mouse"]:
                self.combo_mouse.addItem(label, d["path"])
                if cur_mouse == d["path"]:
                    self.combo_mouse.setCurrentIndex(self.combo_mouse.count() - 1)
                    mouse_selected = True

        # If not matched, auto-select first
        if not kbd_selected and self.combo_keyboard.count() > 0:
            self.combo_keyboard.setCurrentIndex(0)
        if not mouse_selected and self.combo_mouse.count() > 0:
            self.combo_mouse.setCurrentIndex(0)

    def _auto_detect_devices_clicked(self):
        auto_kbd, auto_mouse = auto_detect_devices()
        self._populate_input_devices()

        if auto_kbd:
            idx = self.combo_keyboard.findData(auto_kbd)
            if idx >= 0:
                self.combo_keyboard.setCurrentIndex(idx)
        if auto_mouse:
            idx = self.combo_mouse.findData(auto_mouse)
            if idx >= 0:
                self.combo_mouse.setCurrentIndex(idx)

        self._append_log(f"Auto-detected devices: Keyboard={auto_kbd}, Mouse={auto_mouse}")

    def _on_hotkey_changed(self):
        key = self.combo_hotkey.currentData()
        config.set("hotkey", key)
        self.lbl_hotkey_hint.setText(f"Hotkey: [ {self.combo_hotkey.currentText()} ]")
        self._append_log(f"Switch hotkey updated to: {key}")

    def _on_control_switched(self, new_state: str):
        """Update UI styling when active control flips between LOCAL and REMOTE."""
        is_remote = (new_state == CONTROL_REMOTE)
        self.tray.update_control_state(new_state)

        if is_remote:
            self.card_local.setProperty("class", "InactiveCard")
            self.card_remote.setProperty("class", "ActiveCardArchlab")
            self.badge_local_state.setText("STANDBY")
            self.badge_local_state.setStyleSheet("color: #64748b; font-weight: 700; font-size: 11px;")
            self.badge_remote_state.setText("● ACTIVE CONTROL")
            self.badge_remote_state.setStyleSheet("color: #10b981; font-weight: 700; font-size: 11px;")
            self._append_log(f"Input control shifted to REMOTE ({config.get('client_name', 'ArchLab')}).")
        else:
            self.card_local.setProperty("class", "ActiveCardParrot")
            self.card_remote.setProperty("class", "InactiveCard")
            self.badge_local_state.setText("● ACTIVE CONTROL")
            self.badge_local_state.setStyleSheet("color: #00d2ff; font-weight: 700; font-size: 11px;")
            self.badge_remote_state.setText("STANDBY")
            self.badge_remote_state.setStyleSheet("color: #64748b; font-weight: 700; font-size: 11px;")
            self._append_log(f"Input control shifted to LOCAL ({config.get('host_name', 'Parrot')}).")

        # Force re-polish stylesheet
        self.card_local.style().unpolish(self.card_local)
        self.card_local.style().polish(self.card_local)
        self.card_remote.style().unpolish(self.card_remote)
        self.card_remote.style().polish(self.card_remote)

    def _on_stats_updated(self, kb_count: int, mouse_count: int):
        self.lbl_packets_kb.setText(f"Keyboard Packets: {kb_count}")
        self.lbl_packets_mouse.setText(f"Mouse Packets: {mouse_count}")

    def _on_pulse(self):
        is_remote = (self.grabber.current_control == CONTROL_REMOTE)
        self.heartbeat_widget.trigger(is_remote)

    def _on_connection_changed(self, connected: bool, device_info: Optional[Dict[str, Any]]):
        self._update_adapter_display()
        if connected and device_info:
            self._append_log(f"Client connected: {device_info.get('alias')} ({device_info.get('address')})")
        else:
            self._append_log("Client disconnected.")

    # ========================================================================
    # Client Mode Handlers
    # ========================================================================

    def _scan_bluetooth_clicked(self):
        self._append_log("Starting Bluetooth scan for host...")
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning...")

        client_helper.start_discovery(timeout=8.0)

        def _finish_scan():
            self._refresh_client_devices_table()
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText("🔍 Scan for Host (BLE)")
            self._append_log("Scan completed.")

        QTimer.singleShot(8500, _finish_scan)

    def _refresh_client_devices_table(self):
        devices = client_helper.get_devices()
        self.table_devices.setRowCount(len(devices))

        for row, dev in enumerate(devices):
            self.table_devices.setItem(row, 0, QTableWidgetItem(dev["alias"]))
            self.table_devices.setItem(row, 1, QTableWidgetItem(dev["address"]))
            self.table_devices.setItem(row, 2, QTableWidgetItem("HID Device" if dev["is_hid"] else "Generic BLE"))

            status_str = "Connected" if dev["connected"] else ("Paired" if dev["paired"] else "Available")
            self.table_devices.setItem(row, 3, QTableWidgetItem(status_str))

            btn = QPushButton("Connect" if not dev["connected"] else "Disconnect")
            btn.setProperty("class", "PrimaryButton" if not dev["connected"] else "DangerButton")
            btn.clicked.connect(lambda checked, addr=dev["address"], conn=dev["connected"]: self._toggle_client_connect(addr, conn))
            self.table_devices.setCellWidget(row, 4, btn)

    def _toggle_client_connect(self, address: str, is_connected: bool):
        if is_connected:
            self._append_log(f"Disconnecting from {address}...")
            client_helper.disconnect_device(address)
        else:
            self._append_log(f"Connecting to {address}...")
            client_helper.connect_device(address)
        QTimer.singleShot(1500, self._refresh_client_devices_table)
        QTimer.singleShot(2000, self._check_virtual_devices)

    def _check_virtual_devices(self):
        vdevs = client_helper.detect_virtual_hid_devices(config.get("host_name", "parrot"))

        if vdevs["keyboard"]["detected"]:
            self.lbl_vdev_kb.setText(f"✔ Keyboard: {vdevs['keyboard']['name']} ({vdevs['keyboard']['path']})")
            self.lbl_vdev_kb.setStyleSheet("color: #34d399; font-weight: 600; font-size: 13px;")
        else:
            self.lbl_vdev_kb.setText("✖ Keyboard: Not Detected (Waiting for Host)")
            self.lbl_vdev_kb.setStyleSheet("color: #f87171; font-weight: 600; font-size: 13px;")

        if vdevs["mouse"]["detected"]:
            self.lbl_vdev_mouse.setText(f"✔ Mouse: {vdevs['mouse']['name']} ({vdevs['mouse']['path']})")
            self.lbl_vdev_mouse.setStyleSheet("color: #34d399; font-weight: 600; font-size: 13px;")
        else:
            self.lbl_vdev_mouse.setText("✖ Mouse: Not Detected (Waiting for Host)")
            self.lbl_vdev_mouse.setStyleSheet("color: #f87171; font-weight: 600; font-size: 13px;")

    def _on_auto_reconnect_toggled(self, checked: bool):
        config.set("auto_reconnect", checked)
        if checked:
            client_helper.start_auto_reconnect()
            self._append_log("Auto-reconnect daemon started.")
        else:
            client_helper.stop_auto_reconnect()
            self._append_log("Auto-reconnect daemon stopped.")

    def _install_client_service(self):
        user_systemd_dir = Path.home() / ".config" / "systemd" / "user"
        user_systemd_dir.mkdir(parents=True, exist_ok=True)
        service_file = user_systemd_dir / "blueshift-client.service"

        content = f"""[Unit]
Description=BlueShift BLE KVM Client Auto-Reconnect Daemon
After=bluetooth.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m blueshift --client
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
        try:
            with open(service_file, "w") as f:
                f.write(content)
            self._append_log(f"Installed systemd client service at {service_file}")
            QMessageBox.information(
                self,
                "Service Installed",
                f"Client service installed to {service_file}.\nRun 'systemctl --user enable --now blueshift-client' to activate.",
            )
        except Exception as e:
            self._append_log(f"Failed to install systemd service: {e}")
            QMessageBox.warning(self, "Installation Error", str(e))

    # ========================================================================
    # Settings & Diagnostics Handlers
    # ========================================================================

    def _save_settings(self):
        config.set("host_name", self.txt_host_name.text().strip() or "Parrot")
        config.set("client_name", self.txt_client_name.text().strip() or "ArchLab")
        config.set("client_mac", self.txt_client_mac.text().strip())
        config.set("notifications_enabled", self.chk_notifs.isChecked())
        config.set("start_on_boot", self.chk_boot.isChecked())

        self.lbl_local_name.setText(config.get("host_name").upper())
        self.lbl_remote_name.setText(config.get("client_name").upper())

        self._append_log("Settings saved successfully.")
        QMessageBox.information(self, "Saved", "Settings saved successfully!")

    def _append_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{timestamp}] {message}")

    def _periodic_status_check(self):
        if config.get("role") == "client":
            self._check_virtual_devices()
            return

        if ble_server.is_running:
            self._update_adapter_display()
        else:
            status_resp = send_ipc_command("STATUS")
            if status_resp:
                self.badge_server.setText("● DAEMON ACTIVE")
                self.badge_server.setStyleSheet("background-color: #064e3b; color: #34d399; border: 1px solid #059669; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
                self._update_adapter_display()
                if "REMOTE" in status_resp and self.grabber.current_control != CONTROL_REMOTE:
                    self.grabber.current_control = CONTROL_REMOTE
                    self._on_control_switched(CONTROL_REMOTE)
                elif "LOCAL" in status_resp and self.grabber.current_control != CONTROL_LOCAL:
                    self.grabber.current_control = CONTROL_LOCAL
                    self._on_control_switched(CONTROL_LOCAL)

    def _restore_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

    def _quit_application(self):
        if ble_server.is_running:
            self._stop_server()
        if hasattr(self, "tray"):
            self.tray.tray_icon.hide()
        self.close()

    def closeEvent(self, event):
        """Minimize to tray if configured, otherwise clean exit."""
        if config.get("start_minimized", False):
            event.ignore()
            self.hide()
            self.tray.show_message("BlueShift Minimized", "BlueShift is running in background. Click tray icon to open.")
        else:
            if ble_server.is_running:
                self._stop_server()
            event.accept()
