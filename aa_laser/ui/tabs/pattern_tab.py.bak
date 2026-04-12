"""Pattern Generator tab."""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from aa_laser.constants import _DIM, _PATTERNS, _SEL
from aa_laser.core.dxf_io import (
    load_dxf_polylines,
    polylines_to_outline,
    write_polylines_dxf,
)
from aa_laser.core.generators import (
    gen_custom_tile,
    gen_diamond_checkering,
    gen_fish_scale,
    gen_gradient_honeycomb,
    gen_honeycomb,
    gen_image_halftone,
    gen_stipple_dots,
)
from aa_laser.settings import save_settings
from aa_laser.ui.canvas import DxfCanvas
from aa_laser.ui.helpers import _section_label


class PatternTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict | None = None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings: dict = settings or {}

        # Runtime state
        self._orig_polys: list[list[tuple[float, float]]] = []
        self._edit_polys: list[
            list[tuple[float, float]]
        ] = []  # outline after user edits
        self._orig_w: float = 0.0  # bounding-box width of loaded DXF (mm)
        self._orig_h: float = 0.0  # bounding-box height
        self._ar_locked: bool = True  # aspect-ratio lock state
        self._updating_dims: bool = False  # re-entrance guard
        self._preview_job: str | None = None  # debounce handle
        self._preview_running: bool = False  # background thread guard

        # Two-column layout
        left_outer = ctk.CTkFrame(self, width=310)
        left_outer.pack(side="left", fill="y", padx=(10, 4), pady=10)
        left_outer.pack_propagate(False)
        left = ctk.CTkScrollableFrame(left_outer, fg_color="transparent", width=290)
        left.pack(fill="both", expand=True)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        self._build_left(left)
        self._build_right(right)

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        # ── DXF file ──────────────────────────────────────────────────────────
        _section_label(parent, "Outline DXF")

        file_row = ctk.CTkFrame(parent, fg_color="transparent")
        file_row.pack(fill="x", padx=8, pady=(4, 0))
        self._dxf_var = ctk.StringVar()
        ctk.CTkEntry(
            file_row, textvariable=self._dxf_var, placeholder_text="Select .dxf…"
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._recent_btn = ctk.CTkButton(
            file_row, text="Recent ▾", width=64, command=self._show_recent_menu
        )
        self._recent_btn.pack(side="right", padx=(0, 4))
        ctk.CTkButton(file_row, text="Browse", width=64, command=self._browse_dxf).pack(
            side="right"
        )

        ctk.CTkButton(
            parent,
            text="↺  Reload",
            height=28,
            fg_color="transparent",
            border_width=1,
            command=self._reload_dxf,
        ).pack(fill="x", padx=8, pady=(4, 0))

        _section_label(parent, "Scale")

        # Original size display
        orig_row = ctk.CTkFrame(parent, fg_color="transparent")
        orig_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(
            orig_row, text="Original:", text_color=_DIM, anchor="w", width=68
        ).pack(side="left")
        self._orig_dims_label = ctk.CTkLabel(
            orig_row, text="—", text_color=_DIM, anchor="w"
        )
        self._orig_dims_label.pack(side="left")

        # Scale-to fields
        dims_g = ctk.CTkFrame(parent, fg_color="transparent")
        dims_g.pack(fill="x", padx=8, pady=(0, 2))
        ctk.CTkLabel(dims_g, text="Width (mm)", anchor="w", width=90).grid(
            row=0, column=0, padx=6, pady=2, sticky="w"
        )
        self._scale_w = ctk.CTkEntry(dims_g, width=80, placeholder_text="auto")
        self._scale_w.grid(row=0, column=1, padx=4, pady=2)
        self._scale_w.bind("<KeyRelease>", self._on_scale_w_changed)
        self._scale_w.bind("<KeyRelease>", self._schedule_preview, add="+")

        ctk.CTkLabel(dims_g, text="Height (mm)", anchor="w", width=90).grid(
            row=1, column=0, padx=6, pady=2, sticky="w"
        )
        self._scale_h = ctk.CTkEntry(dims_g, width=80, placeholder_text="auto")
        self._scale_h.grid(row=1, column=1, padx=4, pady=2)
        self._scale_h.bind("<KeyRelease>", self._on_scale_h_changed)
        self._scale_h.bind("<KeyRelease>", self._schedule_preview, add="+")

        # Aspect-ratio lock
        ar_row = ctk.CTkFrame(parent, fg_color="transparent")
        ar_row.pack(fill="x", padx=10, pady=(0, 2))
        self._ar_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            ar_row,
            text="Lock aspect ratio",
            variable=self._ar_var,
            command=self._on_ar_toggle,
        ).pack(side="left")

        _section_label(parent, "Outline Editor")

        self._sel_label = ctk.CTkLabel(
            parent, text="0 selected", text_color=_DIM, anchor="w"
        )
        self._sel_label.pack(anchor="w", padx=10)

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(4, 0))
        ctk.CTkButton(
            btn_row,
            text="All",
            width=46,
            height=28,
            command=lambda: self._canvas.select_all(),
        ).pack(side="left", padx=(0, 3))
        ctk.CTkButton(
            btn_row,
            text="None",
            width=46,
            height=28,
            command=lambda: self._canvas.deselect_all(),
        ).pack(side="left", padx=(0, 3))
        ctk.CTkButton(
            btn_row, text="Fit", width=40, height=28, command=lambda: self._canvas.fit()
        ).pack(side="left")

        self._del_btn = ctk.CTkButton(
            parent,
            text="Delete Selected  [Del]",
            height=30,
            fg_color="#8b1a1a",
            hover_color="#b22222",
            command=self._delete_selected,
        )
        self._del_btn.pack(fill="x", padx=8, pady=(6, 0))
        self._undo_btn = ctk.CTkButton(
            parent,
            text="↩  Undo Delete",
            height=28,
            fg_color="transparent",
            border_width=1,
            command=self._undo_delete,
        )
        self._undo_btn.pack(fill="x", padx=8, pady=(3, 0))

        _section_label(parent, "Pattern")
        self._pattern_var = ctk.StringVar(value="— None —")
        ctk.CTkOptionMenu(
            parent,
            values=_PATTERNS,
            variable=self._pattern_var,
            command=self._switch_pattern,
        ).pack(fill="x", padx=8, pady=(0, 6))

        self._honeycomb_frame = self._make_honeycomb_params(parent)
        self._checkering_frame = self._make_checkering_params(parent)
        self._fishscale_frame = self._make_fishscale_params(parent)
        self._stipple_frame = self._make_stipple_params(parent)
        self._gradient_frame = self._make_gradient_params(parent)
        self._custom_tile_frame = self._make_custom_tile_params(parent)
        self._halftone_frame = self._make_halftone_params(parent)
        self._switch_pattern("— None —")

        _section_label(parent, "Generate")
        self._gen_btn = ctk.CTkButton(
            parent, text="Generate DXF", height=38, command=self._generate
        )
        self._gen_btn.pack(fill="x", padx=8, pady=(0, 6))

        self._progress = ctk.CTkProgressBar(parent)
        self._progress.pack(fill="x", padx=8, pady=(0, 4))
        self._progress.set(0)

        self._status = ctk.CTkLabel(
            parent, text="", text_color=_DIM, anchor="w", wraplength=290
        )
        self._status.pack(anchor="w", padx=10, pady=(0, 4))
        self._last_out_path: str | None = None
        self._reveal_btn = ctk.CTkButton(
            parent,
            text="Show in Finder",
            height=26,
            fg_color="transparent",
            border_width=1,
            command=self._reveal_in_finder,
            state="disabled",
        )
        self._reveal_btn.pack(fill="x", padx=8, pady=(0, 8))

    def _make_honeycomb_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Hex size (mm)", anchor="w", width=145).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._hex_r = ctk.CTkEntry(g, width=80)
        self._hex_r.insert(0, "1.75")
        self._hex_r.grid(row=0, column=1, padx=4, pady=3)
        self._hex_r.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Gap (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._hex_gap = ctk.CTkEntry(g, width=80)
        self._hex_gap.insert(0, "0.5")
        self._hex_gap.grid(row=1, column=1, padx=4, pady=3)
        self._hex_gap.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _make_checkering_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Line spacing (mm)", anchor="w", width=145).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._check_spacing = ctk.CTkEntry(g, width=80)
        self._check_spacing.insert(0, "1.0")
        self._check_spacing.grid(row=0, column=1, padx=4, pady=3)
        self._check_spacing.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Angle (°)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._check_angle = ctk.CTkEntry(g, width=80)
        self._check_angle.insert(0, "45")
        self._check_angle.grid(row=1, column=1, padx=4, pady=3)
        self._check_angle.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _make_fishscale_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Scale width (mm)", anchor="w", width=145).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._fish_w = ctk.CTkEntry(g, width=80)
        self._fish_w.insert(0, "3.0")
        self._fish_w.grid(row=0, column=1, padx=4, pady=3)
        self._fish_w.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Scale height (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._fish_h = ctk.CTkEntry(g, width=80)
        self._fish_h.insert(0, "2.0")
        self._fish_h.grid(row=1, column=1, padx=4, pady=3)
        self._fish_h.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _make_stipple_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Dot radius (mm)", anchor="w", width=145).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._stip_r = ctk.CTkEntry(g, width=80)
        self._stip_r.insert(0, "0.4")
        self._stip_r.grid(row=0, column=1, padx=4, pady=3)
        self._stip_r.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Spacing (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._stip_spacing = ctk.CTkEntry(g, width=80)
        self._stip_spacing.insert(0, "1.2")
        self._stip_spacing.grid(row=1, column=1, padx=4, pady=3)
        self._stip_spacing.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _make_gradient_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Min size (mm)", anchor="w", width=145).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._grad_r_min = ctk.CTkEntry(g, width=80)
        self._grad_r_min.insert(0, "0.8")
        self._grad_r_min.grid(row=0, column=1, padx=4, pady=3)
        self._grad_r_min.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Max size (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._grad_r_max = ctk.CTkEntry(g, width=80)
        self._grad_r_max.insert(0, "2.5")
        self._grad_r_max.grid(row=1, column=1, padx=4, pady=3)
        self._grad_r_max.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Gap (mm)", anchor="w", width=145).grid(
            row=2, column=0, padx=6, pady=3, sticky="w"
        )
        self._grad_gap = ctk.CTkEntry(g, width=80)
        self._grad_gap.insert(0, "0.5")
        self._grad_gap.grid(row=2, column=1, padx=4, pady=3)
        self._grad_gap.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Direction (°)", anchor="w", width=145).grid(
            row=3, column=0, padx=6, pady=3, sticky="w"
        )
        self._grad_angle = ctk.CTkEntry(g, width=80)
        self._grad_angle.insert(0, "0")
        self._grad_angle.grid(row=3, column=1, padx=4, pady=3)
        self._grad_angle.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(
            g,
            text="0° = left→right  ·90° = vertical",
            text_color=_DIM,
            font=("Helvetica", 9),
            anchor="w",
        ).grid(row=4, column=0, columnspan=2, padx=6, pady=(0, 2), sticky="w")
        return f

    def _make_custom_tile_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        pick_row = ctk.CTkFrame(f, fg_color="transparent")
        pick_row.pack(fill="x", padx=4, pady=(4, 4))
        self._tile_path_var = ctk.StringVar()
        ctk.CTkEntry(
            pick_row,
            textvariable=self._tile_path_var,
            placeholder_text="Select tile DXF…",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            pick_row,
            text="Browse",
            width=64,
            command=self._browse_tile_dxf,
        ).pack(side="right")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Gap (mm)", anchor="w", width=145).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._tile_gap = ctk.CTkEntry(g, width=80)
        self._tile_gap.insert(0, "0.5")
        self._tile_gap.grid(row=0, column=1, padx=4, pady=3)
        self._tile_gap.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Tile rotation (°)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._tile_angle = ctk.CTkEntry(g, width=80)
        self._tile_angle.insert(0, "0")
        self._tile_angle.grid(row=1, column=1, padx=4, pady=3)
        self._tile_angle.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(
            g,
            text="Each tile instance is rotated",
            text_color=_DIM,
            font=("Helvetica", 9),
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, padx=6, pady=(0, 2), sticky="w")
        return f

    def _make_halftone_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        pick_row = ctk.CTkFrame(f, fg_color="transparent")
        pick_row.pack(fill="x", padx=4, pady=(4, 4))
        self._htone_img_var = ctk.StringVar()
        ctk.CTkEntry(
            pick_row,
            textvariable=self._htone_img_var,
            placeholder_text="Select image (jpg/png)…",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            pick_row,
            text="Browse",
            width=64,
            command=self._browse_halftone_image,
        ).pack(side="right")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Cell min (mm)", anchor="w", width=145).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._htone_r_min = ctk.CTkEntry(g, width=80)
        self._htone_r_min.insert(0, "0.3")
        self._htone_r_min.grid(row=0, column=1, padx=4, pady=3)
        ctk.CTkLabel(g, text="Cell max (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._htone_r_max = ctk.CTkEntry(g, width=80)
        self._htone_r_max.insert(0, "1.8")
        self._htone_r_max.grid(row=1, column=1, padx=4, pady=3)
        self._htone_r_max.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Grid spacing (mm)", anchor="w", width=145).grid(
            row=2, column=0, padx=6, pady=3, sticky="w"
        )
        self._htone_spacing = ctk.CTkEntry(g, width=80)
        self._htone_spacing.insert(0, "2.2")
        self._htone_spacing.grid(row=2, column=1, padx=4, pady=3)
        self._htone_spacing.bind("<KeyRelease>", self._schedule_preview)
        self._htone_invert = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            f,
            text="Invert  (dark → small cells)",
            variable=self._htone_invert,
            command=self._schedule_preview,
        ).pack(anchor="w", padx=8, pady=(4, 4))
        return f

    def _switch_pattern(self, value: str) -> None:
        for f in (
            self._honeycomb_frame,
            self._checkering_frame,
            self._fishscale_frame,
            self._stipple_frame,
            self._gradient_frame,
            self._custom_tile_frame,
            self._halftone_frame,
        ):
            f.pack_forget()
        if value != "— None —":
            {
                "Honeycomb": self._honeycomb_frame,
                "Gradient Honeycomb": self._gradient_frame,
                "Diamond Checkering": self._checkering_frame,
                "Fish Scale": self._fishscale_frame,
                "Stipple Dots": self._stipple_frame,
                "Custom Tile": self._custom_tile_frame,
                "Image Halftone": self._halftone_frame,
            }.get(value, self._honeycomb_frame).pack(fill="x", padx=4)
            self._schedule_preview()

    # ── Dimension callbacks ─────────────────────────────────────────────────

    def _on_scale_w_changed(self, *_) -> None:
        if self._updating_dims or not self._ar_var.get() or self._orig_w <= 0:
            return
        try:
            w = float(self._scale_w.get())
            h = w * self._orig_h / self._orig_w
            self._updating_dims = True
            self._scale_h.delete(0, "end")
            self._scale_h.insert(0, f"{h:.3f}")
        except ValueError:
            pass
        finally:
            self._updating_dims = False

    def _on_scale_h_changed(self, *_) -> None:
        if self._updating_dims or not self._ar_var.get() or self._orig_h <= 0:
            return
        try:
            h = float(self._scale_h.get())
            w = h * self._orig_w / self._orig_h
            self._updating_dims = True
            self._scale_w.delete(0, "end")
            self._scale_w.insert(0, f"{w:.3f}")
        except ValueError:
            pass
        finally:
            self._updating_dims = False

    def _on_ar_toggle(self) -> None:
        self._ar_locked = self._ar_var.get()

    def _reset_scale(self) -> None:
        self._scale_w.delete(0, "end")
        self._scale_h.delete(0, "end")
        if self._orig_polys:
            self._canvas.load(self._orig_polys)

    def _get_scaled_polys(
        self, polys: list[list[tuple[float, float]]]
    ) -> list[list[tuple[float, float]]]:
        """Return polys scaled to the requested dimensions (or unchanged if blank)."""
        if self._orig_w <= 0 or self._orig_h <= 0:
            return polys
        try:
            sw = (
                float(self._scale_w.get())
                if self._scale_w.get().strip()
                else self._orig_w
            )
            sh = (
                float(self._scale_h.get())
                if self._scale_h.get().strip()
                else self._orig_h
            )
        except ValueError:
            return polys
        if sw <= 0 or sh <= 0:
            return polys
        sx = sw / self._orig_w
        sy = sh / self._orig_h
        if abs(sx - 1.0) < 1e-9 and abs(sy - 1.0) < 1e-9:
            return polys
        # Find bounding-box origin so we scale around it
        all_pts = [pt for p in polys for pt in p]
        if not all_pts:
            return polys
        xs, ys = zip(*all_pts)
        ox, oy = min(xs), min(ys)
        scaled = [
            [(ox + (x - ox) * sx, oy + (y - oy) * sy) for x, y in poly]
            for poly in polys
        ]
        return scaled

    # ── Right panel (canvas) ──────────────────────────────────────────────────

    def _build_right(self, parent: ctk.CTkFrame) -> None:

        # ── Controls row (reset button + preview status) ──────────────────────
        ctrl_row = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=4, pady=(0, 2))
        self._back_btn = ctk.CTkButton(
            ctrl_row,
            text="↺ Reset preview",
            width=110,
            height=22,
            fg_color="transparent",
            border_width=1,
            font=("Helvetica", 11),
            command=self._reset_preview,
        )
        self._back_btn.pack(side="left")
        self._mode_seg = ctk.CTkSegmentedButton(
            ctrl_row,
            values=["Select", "Draw", "Edit"],
            command=self._on_toolbar_mode,
        )
        self._mode_seg.set("Select")
        self._mode_seg.pack(side="left", padx=(6, 0))

        self._preview_status = ctk.CTkLabel(
            ctrl_row,
            text="Load a DXF and select a pattern",
            text_color=_DIM,
            font=("Helvetica", 11),
            anchor="e",
        )
        self._preview_status.pack(side="right")

        # ── Tabbed canvas (Edit / Preview) ────────────────────────────────────
        self._canvas_tabs = ctk.CTkTabview(parent, fg_color="transparent")
        self._canvas_tabs.pack(fill="both", expand=True, padx=0, pady=(0, 0))

        edit_tab = self._canvas_tabs.add("Edit")
        preview_tab = self._canvas_tabs.add("Preview")

        self._canvas = DxfCanvas(
            edit_tab,
            selectable=True,
            on_change=self._on_sel_change,
            on_mode_change=self._on_canvas_mode_change,
        )
        self._canvas.pack(fill="both", expand=True)

        self._preview_canvas = DxfCanvas(
            preview_tab,
            selectable=False,
        )
        self._preview_canvas.pack(fill="both", expand=True)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_sel_change(self, count: int) -> None:
        self._sel_label.configure(
            text=f"{count} selected" if count else "0 selected",
            text_color=_SEL if count else _DIM,
        )
        # Keep _edit_polys in sync with current non-selected outline polys
        self._edit_polys = self._canvas.get_active()

    def _browse_dxf(self) -> None:
        idir = self._settings.get("outline_dxf_dir", "")
        path = filedialog.askopenfilename(
            title="Select outline DXF",
            initialdir=idir or None,
            filetypes=[("DXF files", "*.dxf *.Dxf *.DXF"), ("All files", "*.*")],
        )
        if path:
            self._dxf_var.set(path)
            self._load_dxf(path)

    def _reload_dxf(self) -> None:
        path = self._dxf_var.get().strip()
        if path:
            self._load_dxf(path)

    def _load_dxf(self, path: str) -> None:
        try:
            polys = load_dxf_polylines(path)
            self._orig_polys = polys
            self._edit_polys = list(polys)
            self._canvas.load(polys)

            # Compute & store bounding-box dimensions
            all_pts = [pt for p in polys for pt in p]
            if all_pts:
                xs, ys = zip(*all_pts)
                self._orig_w = max(xs) - min(xs)
                self._orig_h = max(ys) - min(ys)
                self._orig_dims_label.configure(
                    text=f"{self._orig_w:.2f} × {self._orig_h:.2f} mm"
                )
                # Pre-fill scale fields with original size
                self._scale_w.delete(0, "end")
                self._scale_w.insert(0, f"{self._orig_w:.3f}")
                self._scale_h.delete(0, "end")
                self._scale_h.insert(0, f"{self._orig_h:.3f}")
            else:
                self._orig_w = self._orig_h = 0.0
                self._orig_dims_label.configure(text="—")

            self._set_status(f"Loaded {len(polys)} polylines from {Path(path).name}")
            # Track recent files
            recent = self._settings.get("recent_dxf", [])
            if path in recent:
                recent.remove(path)
            recent.insert(0, path)
            self._settings["recent_dxf"] = recent[:8]
            save_settings(self._settings)
            # Show live preview immediately
            self._schedule_preview()
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def _delete_selected(self) -> None:
        n = self._canvas.delete_selected()
        if n:
            self._edit_polys = list(self._canvas.get_active())
            self._set_status(f"Deleted {n} polyline(s). Use ↩ Undo to restore.")
            self._schedule_preview()

    def _undo_delete(self) -> None:
        if not self._canvas.undo_delete():
            self._set_status("Nothing to undo.")
        else:
            self._edit_polys = list(self._canvas.get_active())
            self._set_status("Undo: polylines restored.")
            self._schedule_preview()

    def _on_toolbar_mode(self, value: str) -> None:
        self._canvas.set_mode(value.lower())

    def _on_canvas_mode_change(self, mode: str) -> None:
        self._mode_seg.set(mode.capitalize())

    def _reveal_in_finder(self) -> None:
        if self._last_out_path:
            subprocess.run(["open", "-R", self._last_out_path])

    def _show_recent_menu(self) -> None:
        recent = [r for r in self._settings.get("recent_dxf", []) if Path(r).exists()]
        if not recent:
            messagebox.showinfo("Recent Files", "No recent DXF files.", parent=self)
            return
        menu = tk.Menu(self, tearoff=0)
        for path in recent:
            lbl = Path(path).name + f"  ‹{Path(path).parent.name}›"
            menu.add_command(label=lbl, command=lambda p=path: self._quick_load(p))
        menu.add_separator()
        menu.add_command(label="Clear history", command=self._clear_recent)
        try:
            x = self._recent_btn.winfo_rootx()
            y = self._recent_btn.winfo_rooty() + self._recent_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _quick_load(self, path: str) -> None:
        self._dxf_var.set(path)
        self._load_dxf(path)

    def _clear_recent(self) -> None:
        self._settings["recent_dxf"] = []
        save_settings(self._settings)

    def _browse_tile_dxf(self) -> None:
        path = filedialog.askopenfilename(
            title="Select tile DXF",
            filetypes=[("DXF files", "*.dxf *.Dxf *.DXF"), ("All files", "*.*")],
        )
        if path:
            self._tile_path_var.set(path)
            self._schedule_preview()

    def _browse_halftone_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Select image for halftone",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._htone_img_var.set(path)
            self._schedule_preview()

    def _set_status(self, text: str, color: str = _DIM) -> None:
        self._status.configure(text=text, text_color=color)

    def _generate(self) -> None:
        if not self._edit_polys:
            messagebox.showerror("Error", "No polylines available for outline.")
            return

        out_path = filedialog.asksaveasfilename(
            title="Save pattern DXF",
            defaultextension=".dxf",
            initialdir=self._settings.get("pattern_output_dir") or None,
            initialfile="pattern.dxf",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if not out_path:
            return

        self._gen_btn.configure(state="disabled")
        self._progress.configure(mode="indeterminate")
        self._progress.start()
        self._set_status("Generating…")

        threading.Thread(
            target=self._run_generate,
            args=(list(self._edit_polys), out_path),
            daemon=True,
        ).start()

    def _run_generate(
        self, active: list[list[tuple[float, float]]], out_path: str
    ) -> None:
        try:
            scaled = self._get_scaled_polys(active)
            outline = polylines_to_outline(scaled)
            pattern = self._pattern_var.get()
            polys = self._extract_pattern_polys(outline, pattern)
            # Determine close flag per pattern type
            close = pattern not in ("Diamond Checkering", "Fish Scale")
            write_polylines_dxf(polys, out_path, close=close)

            count = len(polys)
            name = Path(out_path).name

            def _done():
                self._progress.stop()
                self._progress.configure(mode="determinate")
                self._progress.set(1)
                self._gen_btn.configure(state="normal")
                self._set_status(f"Done — {count} shapes → {name}", "#60c060")
                self._last_out_path = out_path
                self._reveal_btn.configure(state="normal")
                # Show generated result in preview canvas
                self._preview_canvas.load(polys)
                self._preview_status.configure(
                    text=f"{count} shapes generated", text_color="#60c060"
                )

            self.after(0, _done)

        except Exception as exc:
            _exc_msg = str(exc)

            def _err():
                self._progress.stop()
                self._progress.configure(mode="determinate")
                self._progress.set(0)
                self._gen_btn.configure(state="normal")
                self._set_status(f"Error: {_exc_msg}", "#e06060")

            self.after(0, _err)

    # ── Live preview ───────────────────────────────────────────────────────────────

    def _schedule_preview(self, *_) -> None:
        """Debounce: rebuild preview 400ms after the last param change."""
        if self._pattern_var.get() == "— None —":
            return
        if not self._edit_polys:
            return
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(400, self._start_preview_thread)

    def _start_preview_thread(self) -> None:
        if self._preview_running or not self._edit_polys:
            return
        self._preview_running = True
        polys_snap = list(self._edit_polys)
        self._preview_status.configure(text="Previewing…", text_color=_DIM)
        threading.Thread(
            target=self._compute_preview, args=(polys_snap,), daemon=True
        ).start()

    def _compute_preview(self, outline_polys) -> None:
        try:
            scaled = self._get_scaled_polys(outline_polys)
            outline = polylines_to_outline(scaled)
            pattern = self._pattern_var.get()
            polys = self._extract_pattern_polys(outline, pattern)
            count = len(polys)

            def _show():
                self._preview_running = False
                self._preview_canvas.reload(polys)
                self._preview_status.configure(
                    text=f"{count} shapes — live preview", text_color="#60c060"
                )
                # Only switch to Preview when pattern was explicitly chosen
                if self._pattern_var.get() != "— None —":
                    self._canvas_tabs.set("Preview")

            self.after(0, _show)

        except Exception as exc:
            _msg = str(exc)

            def _fail():
                self._preview_running = False
                self._preview_status.configure(
                    text=f"Preview error: {_msg}", text_color="#e06060"
                )

            self.after(0, _fail)

    def _extract_pattern_polys(
        self, outline, pattern: str
    ) -> list[list[tuple[float, float]]]:
        """Compute pattern polys for the given outline; shared by preview & generate."""
        if pattern == "Honeycomb":
            r = float(self._hex_r.get())
            gap = float(self._hex_gap.get())
            return gen_honeycomb(outline, r, gap)
        elif pattern == "Gradient Honeycomb":
            r_min = float(self._grad_r_min.get())
            r_max = float(self._grad_r_max.get())
            gap = float(self._grad_gap.get())
            angle = float(self._grad_angle.get())
            return gen_gradient_honeycomb(outline, r_min, r_max, gap, angle)
        elif pattern == "Diamond Checkering":
            spacing = float(self._check_spacing.get())
            angle = float(self._check_angle.get())
            return gen_diamond_checkering(outline, spacing, angle)
        elif pattern == "Fish Scale":
            sw = float(self._fish_w.get())
            sh = float(self._fish_h.get())
            return gen_fish_scale(outline, sw, sh)
        elif pattern == "Stipple Dots":
            r = float(self._stip_r.get())
            spacing = float(self._stip_spacing.get())
            return gen_stipple_dots(outline, r, spacing)
        elif pattern == "Custom Tile":
            tile_path = self._tile_path_var.get().strip()
            if not tile_path:
                raise ValueError("No tile DXF selected.")
            tile_polys = load_dxf_polylines(tile_path)
            gap = float(self._tile_gap.get())
            angle = float(self._tile_angle.get())
            return gen_custom_tile(outline, tile_polys, gap, angle)
        else:  # Image Halftone
            img_path = self._htone_img_var.get().strip()
            if not img_path:
                raise ValueError("No image selected.")
            r_min = float(self._htone_r_min.get())
            r_max = float(self._htone_r_max.get())
            spacing = float(self._htone_spacing.get())
            invert = bool(self._htone_invert.get())
            return gen_image_halftone(outline, img_path, r_min, r_max, spacing, invert)

    def _reset_preview(self) -> None:
        """Re-show the outline in the preview canvas and re-run preview."""
        if self._edit_polys:
            self._preview_canvas.reload(self._edit_polys)
            self._preview_status.configure(
                text="Preview reset — adjust params to regenerate", text_color=_DIM
            )
            self._schedule_preview()
