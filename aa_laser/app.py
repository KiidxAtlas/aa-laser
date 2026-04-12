"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolBar,
)

from aa_laser.settings import load_settings
from aa_laser.ui.settings_dialog import SettingsDialog
from aa_laser.ui.tabs.fvi_tab import UtilitiesTab
from aa_laser.ui.tabs.image_tab import ImageTab
from aa_laser.ui.tabs.pattern_tab import PatternTab
from aa_laser.ui.tabs.repo_tab import RepoTab
from aa_laser.ui.tabs.shape_tab import ShapeTab


def _apply_dark_palette(app: QApplication) -> None:
    """Apply a neutral dark palette (GitHub/VS Code aesthetic) to the entire application."""
    app.setStyle("Fusion")
    p = QPalette()
    # 4-level background hierarchy: deepest → sidebar → panel → elevated
    p.setColor(QPalette.ColorRole.Window, QColor("#161b22"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#e6edf3"))
    p.setColor(QPalette.ColorRole.Base, QColor("#0d1117"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#1c2128"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1c2128"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#e6edf3"))
    p.setColor(QPalette.ColorRole.Text, QColor("#e6edf3"))
    p.setColor(QPalette.ColorRole.Button, QColor("#21262d"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#e6edf3"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#2f81f7"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#484f58"))
    p.setColor(QPalette.ColorRole.Mid, QColor("#30363d"))
    p.setColor(QPalette.ColorRole.Dark, QColor("#0d1117"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#484f58"))
    p.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#484f58")
    )
    app.setPalette(p)
    app.setStyleSheet(
        """
        /* ── Global font ─────────────────────────────────────── */
        * {
            font-family: -apple-system, "SF Pro Text", "Segoe UI", "Helvetica Neue", sans-serif;
            font-size: 13px;
        }

        /* ── Tab bar ─────────────────────────────────────────── */
        QTabWidget::pane {
            border: none;
            border-top: 1px solid #30363d;
        }
        QTabBar {
            background: #0d1117;
        }
        QTabBar::tab {
            background: transparent;
            color: #8b949e;
            padding: 8px 20px;
            margin-right: 0px;
            border: none;
            border-bottom: 2px solid transparent;
            font-size: 13px;
        }
        QTabBar::tab:selected {
            color: #e6edf3;
            border-bottom: 2px solid #2f81f7;
        }
        QTabBar::tab:hover:!selected {
            color: #c9d1d9;
            background: #161b22;
        }

        /* ── Tooltip ─────────────────────────────────────────── */
        QToolTip {
            background: #1c2128;
            color: #e6edf3;
            border: 1px solid #30363d;
            padding: 5px 8px;
            border-radius: 4px;
        }

        /* ── Buttons ─────────────────────────────────────────── */
        QPushButton {
            padding: 5px 14px;
            border-radius: 6px;
            background: #21262d;
            border: 1px solid #30363d;
            color: #e6edf3;
            font-size: 13px;
        }
        QPushButton:hover {
            background: #2d333b;
            border-color: #8b949e;
        }
        QPushButton:pressed {
            background: #1c2128;
        }
        QPushButton:disabled {
            background: #161b22;
            border-color: #21262d;
            color: #484f58;
        }
        QPushButton:checked {
            background: #1f3a6e;
            border-color: #2f81f7;
            color: #79c0ff;
        }

        /* ── Active mode button (toolbar toggles) ────────────── */
        QPushButton[active="true"] {
            background: #1f3a6e;
            border-color: #2f81f7;
            color: #79c0ff;
        }
        QPushButton[active="true"]:hover {
            background: #25437e;
            border-color: #58a6ff;
        }

        /* ── Primary action button ───────────────────────────── */
        QPushButton[role="primary"] {
            background: #2f81f7;
            border-color: #2f81f7;
            color: #ffffff;
            font-weight: 600;
        }
        QPushButton[role="primary"]:hover {
            background: #388bfd;
            border-color: #58a6ff;
        }
        QPushButton[role="primary"]:pressed {
            background: #1a70e0;
        }
        QPushButton[role="primary"]:disabled {
            background: #161b22;
            border-color: #21262d;
            color: #484f58;
            font-weight: normal;
        }

        /* ── Input fields ────────────────────────────────────── */
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            padding: 5px 8px;
            border-radius: 6px;
            border: 1px solid #30363d;
            background: #0d1117;
            color: #e6edf3;
            selection-background-color: #1f3a6e;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: #2f81f7;
        }
        QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
            border-color: #8b949e;
        }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox::down-arrow {
            width: 10px;
            height: 10px;
        }
        QComboBox QAbstractItemView {
            background: #1c2128;
            border: 1px solid #30363d;
            selection-background-color: #1f3a6e;
            outline: none;
        }
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
            width: 16px;
            border: none;
            background: transparent;
        }

        /* ── Scroll areas ────────────────────────────────────── */
        QScrollArea {
            border: none;
        }

        /* ── Sliders ─────────────────────────────────────────── */
        QSlider::groove:horizontal {
            height: 3px;
            background: #21262d;
            border-radius: 2px;
            margin: 0 3px;
        }
        QSlider::sub-page:horizontal {
            background: #2f81f7;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #e6edf3;
            border: 2px solid #2f81f7;
            width: 14px;
            height: 14px;
            margin: -6px -1px;
            border-radius: 8px;
        }
        QSlider::handle:horizontal:hover {
            background: #2f81f7;
            border-color: #58a6ff;
        }

        /* ── Progress bar ────────────────────────────────────── */
        QProgressBar {
            border: none;
            border-radius: 3px;
            background: #21262d;
            text-align: center;
            color: transparent;
            max-height: 4px;
        }
        QProgressBar::chunk {
            background: #2f81f7;
            border-radius: 3px;
        }

        /* ── Check boxes ─────────────────────────────────────── */
        QCheckBox {
            spacing: 6px;
        }
        QCheckBox::indicator {
            width: 15px;
            height: 15px;
            border: 1px solid #30363d;
            border-radius: 4px;
            background: #0d1117;
        }
        QCheckBox::indicator:checked {
            background: #2f81f7;
            border-color: #2f81f7;
        }
        QCheckBox::indicator:hover {
            border-color: #58a6ff;
        }

        /* ── Plain text / log ────────────────────────────────── */
        QPlainTextEdit {
            border: 1px solid #30363d;
            border-radius: 6px;
            background: #0d1117;
        }

        /* ── Scroll bars ─────────────────────────────────────── */
        QScrollBar:vertical {
            width: 5px;
            background: transparent;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #30363d;
            border-radius: 3px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover {
            background: #484f58;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
        QScrollBar:horizontal {
            height: 5px;
            background: transparent;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #30363d;
            border-radius: 3px;
            min-width: 24px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #484f58;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0;
        }

        /* ── Menu ────────────────────────────────────────────── */
        QMenu {
            background: #1c2128;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 4px;
        }
        QMenu::item {
            padding: 5px 16px;
            border-radius: 4px;
            color: #e6edf3;
        }
        QMenu::item:selected {
            background: #1f3a6e;
            color: #79c0ff;
        }
        QMenu::separator {
            height: 1px;
            background: #30363d;
            margin: 4px 8px;
        }

        /* ── Message boxes ───────────────────────────────────── */
        QMessageBox {
            background: #161b22;
        }

        /* ── Dialog ──────────────────────────────────────────── */
        QDialog {
            background: #161b22;
        }
        """
    )


class App(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AA Laser Studio")
        self.resize(1100, 740)
        self.setMinimumSize(860, 580)

        self._settings = load_settings()

        # ── Tabs ──────────────────────────────────────────────────────────────
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        self._utilities_tab = UtilitiesTab(settings=self._settings)
        self._pattern_tab = PatternTab(settings=self._settings)
        self._shape_tab = ShapeTab(settings=self._settings)
        self._image_tab = ImageTab(settings=self._settings)
        self._repo_tab = RepoTab(settings=self._settings)

        tabs.addTab(self._utilities_tab, "Utilities")
        tabs.addTab(self._pattern_tab, "Pattern Generator")
        tabs.addTab(self._shape_tab, "Shape Creator")
        tabs.addTab(self._image_tab, "Image → Outline")
        tabs.addTab(self._repo_tab, "Repository")

        # ── Settings toolbar (top-right, always visible on macOS) ─────────
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setStyleSheet(
            "QToolBar { border: none; background: transparent; padding: 0; spacing: 0; }"
        )
        spacer = QPushButton()
        spacer.setEnabled(False)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer.setStyleSheet("background: transparent; border: none;")
        toolbar.addWidget(spacer)
        gear_btn = QPushButton("⚙")
        gear_btn.setFixedSize(28, 24)
        gear_btn.setToolTip("Settings  Ctrl+,")
        gear_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; font-size: 16px; color: #8b949e; }"
            "QPushButton:hover { color: #e6edf3; }"
        )
        gear_btn.clicked.connect(self._open_settings)
        toolbar.addWidget(gear_btn)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        # ── Keyboard shortcuts ────────────────────────────────────────────────
        settings_action = QAction("Settings…", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        self.addAction(settings_action)

        # ── Auto-pull on open ─────────────────────────────────────────────────
        QTimer.singleShot(800, self._repo_tab.auto_pull)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self._settings)
        dlg.exec()
