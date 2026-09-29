"""
BlueShift Modern Cyber Dark Theme Stylesheet (QSS).
Sleek dark palette (#0b0f17, #131b26, #18202c) with glowing neon accents (#00d2ff, #10b981).
"""

DARK_THEME_QSS = """
/* ============================================================================
   Base Application Styling
   ============================================================================ */
QWidget {
    background-color: #0b0f17;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Ubuntu", "Helvetica Neue", sans-serif;
    font-size: 13px;
    selection-background-color: #00d2ff;
    selection-color: #0b0f17;
}

QMainWindow {
    background-color: #0b0f17;
}

/* ============================================================================
   Tab Widget & Tab Bar
   ============================================================================ */
QTabWidget::pane {
    border: 1px solid #1c2838;
    background-color: #0d131d;
    border-radius: 12px;
    top: -1px;
}

QTabBar::tab {
    background-color: #131b26;
    color: #94a3b8;
    padding: 10px 22px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border: 1px solid #1c2838;
    border-bottom: none;
    font-weight: 600;
    font-size: 13px;
}

QTabBar::tab:hover {
    background-color: #1a2434;
    color: #f1f5f9;
    border-color: #2a3c54;
}

QTabBar::tab:selected {
    background-color: #0d131d;
    color: #00d2ff;
    border-top: 2px solid #00d2ff;
    border-left: 1px solid #1c2838;
    border-right: 1px solid #1c2838;
}

/* ============================================================================
   Cards and Group Containers
   ============================================================================ */
QFrame.CardFrame {
    background-color: #131b26;
    border: 1px solid #1e2b3c;
    border-radius: 14px;
    padding: 16px;
}

QFrame.CardFrame:hover {
    border: 1px solid #283a52;
}

QFrame.ActiveCardParrot {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #102336, stop:1 #131b26);
    border: 2px solid #00d2ff;
    border-radius: 14px;
}

QFrame.ActiveCardArchlab {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0f2c25, stop:1 #131b26);
    border: 2px solid #10b981;
    border-radius: 14px;
}

QFrame.InactiveCard {
    background-color: #111722;
    border: 1px solid #1a2533;
    border-radius: 14px;
}

/* ============================================================================
   Buttons
   ============================================================================ */
QPushButton {
    background-color: #1a2434;
    color: #f1f5f9;
    border: 1px solid #25354c;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #233146;
    border-color: #00d2ff;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #151e2c;
    border-color: #00b4d8;
}

QPushButton:disabled {
    background-color: #0f1620;
    border-color: #17212e;
    color: #475569;
}

QPushButton.PrimaryButton {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #00d2ff);
    color: #050b14;
    border: none;
    font-weight: 700;
}

QPushButton.PrimaryButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0396e6, stop:1 #38bdf8);
}

QPushButton.SuccessButton {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #10b981);
    color: #ffffff;
    border: none;
    font-weight: 700;
}

QPushButton.SuccessButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #047857, stop:1 #34d399);
}

QPushButton.DangerButton {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #b91c1c, stop:1 #ef4444);
    color: #ffffff;
    border: none;
    font-weight: 700;
}

QPushButton.BigSwitchButton {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 14px 28px;
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.5px;
}

QPushButton.BigSwitchButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #7c3aed);
}

/* ============================================================================
   Inputs & Comboboxes
   ============================================================================ */
QComboBox {
    background-color: #151e2b;
    border: 1px solid #233146;
    border-radius: 8px;
    padding: 8px 12px;
    color: #f1f5f9;
    font-size: 13px;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #00d2ff;
}

QComboBox:focus {
    border-color: #00d2ff;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #94a3b8;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #151e2b;
    border: 1px solid #233146;
    border-radius: 8px;
    selection-background-color: #1e2b3c;
    selection-color: #00d2ff;
    color: #f1f5f9;
    padding: 4px;
}

QLineEdit {
    background-color: #151e2b;
    border: 1px solid #233146;
    border-radius: 8px;
    padding: 8px 12px;
    color: #f1f5f9;
}

QLineEdit:focus {
    border: 1px solid #00d2ff;
}

/* ============================================================================
   Sliders & Progress Bars
   ============================================================================ */
QSlider::groove:horizontal {
    height: 6px;
    background: #1e2b3c;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #00d2ff;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #00d2ff;
    width: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #00d2ff;
    border-color: #ffffff;
}

QProgressBar {
    background-color: #151e2b;
    border: 1px solid #233146;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: #94a3b8;
    font-size: 11px;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #00d2ff);
    border-radius: 5px;
}

/* ============================================================================
   Checkboxes
   ============================================================================ */
QCheckBox {
    color: #e2e8f0;
    spacing: 8px;
    font-size: 13px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #233146;
    background-color: #151e2b;
}

QCheckBox::indicator:hover {
    border-color: #00d2ff;
}

QCheckBox::indicator:checked {
    background-color: #00d2ff;
    border-color: #00d2ff;
}

/* ============================================================================
   Tables & Lists
   ============================================================================ */
QTableWidget, QTreeWidget, QListWidget {
    background-color: #111722;
    border: 1px solid #1e2b3c;
    border-radius: 10px;
    gridline-color: #182230;
    color: #e2e8f0;
    padding: 4px;
}

QHeaderView::section {
    background-color: #151e2b;
    color: #94a3b8;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #1e2b3c;
    font-weight: 600;
}

QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #1b2636;
    color: #00d2ff;
}

/* ============================================================================
   Text Edit & Logs
   ============================================================================ */
QTextEdit, QPlainTextEdit {
    background-color: #0c1017;
    border: 1px solid #1a2533;
    border-radius: 8px;
    color: #a5b4fc;
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 12px;
    padding: 8px;
}

/* ============================================================================
   Labels & Typography
   ============================================================================ */
QLabel.SectionTitle {
    color: #ffffff;
    font-size: 16px;
    font-weight: 700;
}

QLabel.SectionSubtitle {
    color: #64748b;
    font-size: 12px;
}

QLabel.BadgeConnected {
    background-color: #064e3b;
    color: #34d399;
    border: 1px solid #059669;
    border-radius: 6px;
    padding: 3px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel.BadgeDisconnected {
    background-color: #450a0a;
    color: #f87171;
    border: 1px solid #b91c1c;
    border-radius: 6px;
    padding: 3px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel.BadgeActiveControl {
    background-color: #0c4a6e;
    color: #38bdf8;
    border: 1px solid #0284c7;
    border-radius: 6px;
    padding: 3px 10px;
    font-weight: 700;
    font-size: 11px;
}

QScrollBar:vertical {
    border: none;
    background: #0b0f17;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #1e2b3c;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #2a3c54;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def apply_theme(app_or_widget):
    """Apply the BlueShift cyber dark stylesheet to a QApplication or QWidget."""
    app_or_widget.setStyleSheet(DARK_THEME_QSS)
