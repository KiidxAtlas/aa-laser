"""Settings dialog window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aa_laser.settings import save_settings
from aa_laser.ui.helpers import _sep


class SettingsDialog(QDialog):
    _FOLDER_FIELDS = [
        ("outline_dxf_dir", "Outline DXF folder"),
        ("pattern_output_dir", "Pattern output folder"),
        ("shape_output_dir", "Shape output folder"),
        ("fvi_source_dir", "FVI source folder"),
        ("fvi_output_dir", "FVI output folder"),
    ]
    _GIT_FIELDS = [
        ("repo_path", "Local repo path"),
    ]

    def __init__(self, parent: QWidget | None = None, settings: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(560, 580)
        self.setModal(True)

        self._settings: dict = settings or {}
        self._entries: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)

        heading = QLabel("Default Folders")
        heading.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(heading)

        for key, label in self._FOLDER_FIELDS:
            self._add_row(layout, key, label, browse=True)

        _sep(layout)

        heading2 = QLabel("Git Repository")
        heading2.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(heading2)

        for key, label in self._GIT_FIELDS:
            self._add_row(layout, key, label, browse=True)

        _sep(layout)
        layout.addStretch()

        # Save / Cancel
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(100)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _add_row(
        self, layout: QVBoxLayout, key: str, label: str, browse: bool = False
    ) -> None:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(170)
        row.addWidget(lbl)
        e = QLineEdit()
        e.setText(self._settings.get(key, ""))
        row.addWidget(e, stretch=1)
        self._entries[key] = e
        if browse:
            btn = QPushButton("…")
            btn.setFixedSize(28, 28)
            btn.clicked.connect(lambda checked, k=key: self._browse_dir(k))
            row.addWidget(btn)
        layout.addLayout(row)

    def _browse_dir(self, key: str) -> None:
        current = self._entries[key].text().strip()
        d = QFileDialog.getExistingDirectory(
            self,
            "Select folder",
            current if current else str(Path.home()),
        )
        if d:
            self._entries[key].setText(d)

    def _save(self) -> None:
        for key, entry in self._entries.items():
            v = entry.text().strip()
            if v:
                self._settings[key] = v
            elif key in self._settings:
                del self._settings[key]
        save_settings(self._settings)
        self.accept()
