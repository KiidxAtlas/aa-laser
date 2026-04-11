"""Main application window."""

from __future__ import annotations

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Neutralise CTkScrollableFrame's global <MouseWheel> handler so it never
# fights with DxfCanvas._class_wheel_cb (which routes scroll to the right
# widget itself).  Must happen before any CTkScrollableFrame is created.
ctk.CTkScrollableFrame._mouse_wheel_all = lambda self, event: None

from aa_laser.settings import load_settings
from aa_laser.ui.canvas import DxfCanvas
from aa_laser.ui.settings_dialog import SettingsDialog
from aa_laser.ui.tabs.fvi_tab import FviTab
from aa_laser.ui.tabs.image_tab import ImageTab
from aa_laser.ui.tabs.pattern_tab import PatternTab
from aa_laser.ui.tabs.repo_tab import RepoTab
from aa_laser.ui.tabs.shape_tab import ShapeTab


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AA Laser Studio")
        self.geometry("1100x740")
        self.minsize(860, 580)

        self._settings = load_settings()

        # ── Tabs ──────────────────────────────────────────────────────────────
        tabs = ctk.CTkTabview(self, anchor="nw")
        tabs.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        tabs.add("FVI → DXF")
        tabs.add("Pattern Generator")
        tabs.add("Shape Creator")
        tabs.add("Image → Outline")
        tabs.add("Repository")

        FviTab(tabs.tab("FVI → DXF"), settings=self._settings).pack(
            fill="both", expand=True
        )
        PatternTab(tabs.tab("Pattern Generator"), settings=self._settings).pack(
            fill="both", expand=True
        )
        ShapeTab(tabs.tab("Shape Creator"), settings=self._settings).pack(
            fill="both", expand=True
        )
        ImageTab(tabs.tab("Image → Outline"), settings=self._settings).pack(
            fill="both", expand=True
        )
        self._repo_tab = RepoTab(tabs.tab("Repository"), settings=self._settings)
        self._repo_tab.pack(fill="both", expand=True)

        # ── Keyboard shortcuts ────────────────────────────────────────────────
        self.bind_all("<Command-comma>", lambda _: self._open_settings())

        # Install scroll interceptor AFTER all tabs (and their CTkScrollableFrames)
        # are fully constructed.  CTkScrollableFrame registers its own bind_all
        # handler during __init__; by deferring to after_idle we register last,
        # which means our handler overrides theirs (no add=True → last wins).
        self.after_idle(self._install_scroll_handler)

        # ── Auto-pull on open ─────────────────────────────────────────────────
        self.after(800, self._repo_tab.auto_pull)

    def _install_scroll_handler(self) -> None:
        self.bind_all("<MouseWheel>", DxfCanvas._class_wheel_cb)
        self.bind_all("<Button-4>", DxfCanvas._class_wheel_cb)  # Linux scroll up
        self.bind_all("<Button-5>", DxfCanvas._class_wheel_cb)  # Linux scroll down

    def _open_settings(self) -> None:
        SettingsDialog(self, self._settings)
