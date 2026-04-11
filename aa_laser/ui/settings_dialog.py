"""Settings dialog window."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from aa_laser.settings import save_settings
from aa_laser.ui.helpers import _sep


class SettingsDialog(ctk.CTkToplevel):
    _FOLDER_FIELDS = [
        ("outline_dxf_dir", "Outline DXF folder"),
        ("pattern_output_dir", "Pattern output folder"),
        ("shape_output_dir", "Shape output folder"),
    ]
    _GIT_FIELDS = [
        ("repo_path", "Local repo path"),
    ]

    def __init__(self, parent: ctk.CTk, settings: dict):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("560x500")
        self.resizable(False, False)
        self.lift()
        self.focus_force()
        self.grab_set()

        self._settings = settings
        self._entries: dict[str, ctk.CTkEntry] = {}

        ctk.CTkLabel(
            self,
            text="Default Folders",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        for key, label in self._FOLDER_FIELDS:
            self._add_row(key, label, browse_type="dir")

        _sep(self)

        ctk.CTkLabel(
            self,
            text="Git Repository",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(0, 4))

        for i, (key, label) in enumerate(self._GIT_FIELDS):
            self._add_row(key, label, browse_type="dir" if i == 0 else None)

        _sep(self)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            btn_row,
            text="Cancel",
            width=80,
            fg_color="transparent",
            border_width=1,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_row, text="Save", width=100, command=self._save).pack(
            side="right"
        )

    def _add_row(self, key: str, label: str, browse_type: str | None) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(row, text=label, anchor="w", width=170).pack(side="left")
        e = ctk.CTkEntry(row)
        e.insert(0, self._settings.get(key, ""))
        e.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._entries[key] = e
        if browse_type == "dir":
            ctk.CTkButton(
                row,
                text="…",
                width=28,
                height=28,
                command=lambda k=key: self._browse_dir(k),
            ).pack(side="right")

    def _browse_dir(self, key: str) -> None:
        current = self._entries[key].get().strip()
        d = filedialog.askdirectory(
            title="Select folder",
            initialdir=current if current else str(Path.home()),
        )
        if d:
            self._entries[key].delete(0, "end")
            self._entries[key].insert(0, d)

    def _save(self) -> None:
        for key, entry in self._entries.items():
            v = entry.get().strip()
            if v:
                self._settings[key] = v
            elif key in self._settings:
                del self._settings[key]
        save_settings(self._settings)
        self.destroy()
