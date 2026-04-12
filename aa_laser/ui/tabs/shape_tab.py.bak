"""Shape Creator tab."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from aa_laser.constants import _DIM, _SHAPES
from aa_laser.core.dxf_io import write_polylines_dxf
from aa_laser.core.shapes import (
    shape_circle,
    shape_ellipse,
    shape_polygon,
    shape_rect,
    shape_rect_rounded,
)
from aa_laser.ui.canvas import DxfCanvas
from aa_laser.ui.helpers import _section_label


class ShapeTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict | None = None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings: dict = settings or {}

        left = ctk.CTkFrame(self, width=290)
        left.pack(side="left", fill="y", padx=(10, 4), pady=10)
        left.pack_propagate(False)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        self._preview_job: str | None = None

        self._build_left(left)
        self._build_right(right)

        self._update_preview()

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        _section_label(parent, "Shape")

        self._shape_var = ctk.StringVar(value="Rectangle")
        ctk.CTkOptionMenu(
            parent,
            values=_SHAPES,
            variable=self._shape_var,
            command=self._switch_shape,
        ).pack(fill="x", padx=8, pady=(0, 8))

        # ── Param frames (one per shape) ─────────────────────────────────────
        self._rect_frame = self._make_rect_params(parent)
        self._circle_frame = self._make_circle_params(parent)
        self._ellipse_frame = self._make_ellipse_params(parent)
        self._polygon_frame = self._make_polygon_params(parent)
        self._switch_shape("Rectangle")

        # Rotation (applies to all shapes)
        rot_row = ctk.CTkFrame(parent, fg_color="transparent")
        rot_row.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkLabel(rot_row, text="Rotation (°)", anchor="w", width=140).pack(
            side="left", padx=6
        )
        self._rotation = ctk.CTkEntry(rot_row, width=80)
        self._rotation.insert(0, "0")
        self._rotation.pack(side="left", padx=4)
        self._rotation.bind("<KeyRelease>", self._schedule_preview)

        # Export
        ctk.CTkButton(parent, text="Export DXF…", height=38, command=self._export).pack(
            fill="x", padx=8, pady=(0, 6)
        )

        self._shape_status = ctk.CTkLabel(
            parent, text="", text_color=_DIM, anchor="w", wraplength=260
        )
        self._shape_status.pack(anchor="w", padx=10, pady=(0, 4))
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
        self._reveal_btn.pack(fill="x", padx=8, pady=(0, 10))

    def _make_rect_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Width (mm)", anchor="w", width=140).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._rect_w = ctk.CTkEntry(g, width=80)
        self._rect_w.insert(0, "50.0")
        self._rect_w.grid(row=0, column=1, padx=4, pady=3)
        self._rect_w.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Height (mm)", anchor="w", width=140).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._rect_h = ctk.CTkEntry(g, width=80)
        self._rect_h.insert(0, "30.0")
        self._rect_h.grid(row=1, column=1, padx=4, pady=3)
        self._rect_h.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Corner radius (mm)", anchor="w", width=140).grid(
            row=2, column=0, padx=6, pady=3, sticky="w"
        )
        self._rect_cr = ctk.CTkEntry(g, width=80)
        self._rect_cr.insert(0, "0")
        self._rect_cr.grid(row=2, column=1, padx=4, pady=3)
        self._rect_cr.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _make_circle_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Radius (mm)", anchor="w", width=140).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._circ_r = ctk.CTkEntry(g, width=80)
        self._circ_r.insert(0, "25.0")
        self._circ_r.grid(row=0, column=1, padx=4, pady=3)
        self._circ_r.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Segments", anchor="w", width=140).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._circ_n = ctk.CTkEntry(g, width=80)
        self._circ_n.insert(0, "64")
        self._circ_n.grid(row=1, column=1, padx=4, pady=3)
        self._circ_n.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _make_ellipse_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="X radius (mm)", anchor="w", width=140).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._ell_rx = ctk.CTkEntry(g, width=80)
        self._ell_rx.insert(0, "40.0")
        self._ell_rx.grid(row=0, column=1, padx=4, pady=3)
        self._ell_rx.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Y radius (mm)", anchor="w", width=140).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._ell_ry = ctk.CTkEntry(g, width=80)
        self._ell_ry.insert(0, "20.0")
        self._ell_ry.grid(row=1, column=1, padx=4, pady=3)
        self._ell_ry.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Segments", anchor="w", width=140).grid(
            row=2, column=0, padx=6, pady=3, sticky="w"
        )
        self._ell_n = ctk.CTkEntry(g, width=80)
        self._ell_n.insert(0, "64")
        self._ell_n.grid(row=2, column=1, padx=4, pady=3)
        self._ell_n.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _make_polygon_params(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", padx=4)
        ctk.CTkLabel(g, text="Sides", anchor="w", width=140).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._poly_sides = ctk.CTkEntry(g, width=80)
        self._poly_sides.insert(0, "6")
        self._poly_sides.grid(row=0, column=1, padx=4, pady=3)
        self._poly_sides.bind("<KeyRelease>", self._schedule_preview)
        ctk.CTkLabel(g, text="Radius (mm)", anchor="w", width=140).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._poly_r = ctk.CTkEntry(g, width=80)
        self._poly_r.insert(0, "25.0")
        self._poly_r.grid(row=1, column=1, padx=4, pady=3)
        self._poly_r.bind("<KeyRelease>", self._schedule_preview)
        return f

    def _switch_shape(self, value: str) -> None:
        self._rect_frame.pack_forget()
        self._circle_frame.pack_forget()
        self._ellipse_frame.pack_forget()
        self._polygon_frame.pack_forget()
        if value == "Rectangle":
            self._rect_frame.pack(fill="x", padx=4)
        elif value == "Circle":
            self._circle_frame.pack(fill="x", padx=4)
        elif value == "Ellipse":
            self._ellipse_frame.pack(fill="x", padx=4)
        else:
            self._polygon_frame.pack(fill="x", padx=4)
        self._schedule_preview()

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self, parent: ctk.CTkFrame) -> None:
        self._canvas = DxfCanvas(parent, selectable=False)
        self._canvas.pack(fill="both", expand=True)

    # ── Preview / export ──────────────────────────────────────────────────────

    def _schedule_preview(self, *_) -> None:
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self._update_preview)

    def _update_preview(self) -> None:
        self._preview_job = None
        coords = self._build_coords()
        if coords:
            self._canvas.load([coords])

    def _build_coords(self) -> list[tuple[float, float]] | None:
        shape = self._shape_var.get()
        try:
            coords: list[tuple[float, float]] | None = None
            if shape == "Rectangle":
                w = float(self._rect_w.get())
                h = float(self._rect_h.get())
                try:
                    cr = max(0.0, float(self._rect_cr.get()))
                except (ValueError, AttributeError):
                    cr = 0.0
                if w > 0 and h > 0:
                    coords = (
                        shape_rect_rounded(w, h, cr) if cr > 0 else shape_rect(w, h)
                    )
            elif shape == "Circle":
                r = float(self._circ_r.get())
                n = max(3, int(self._circ_n.get()))
                if r > 0:
                    coords = shape_circle(r, n)
            elif shape == "Ellipse":
                rx = float(self._ell_rx.get())
                ry = float(self._ell_ry.get())
                n = max(3, int(self._ell_n.get()))
                if rx > 0 and ry > 0:
                    coords = shape_ellipse(rx, ry, n)
            else:
                sides = max(3, int(self._poly_sides.get()))
                r = float(self._poly_r.get())
                if r > 0:
                    coords = shape_polygon(sides, r)
            if coords is not None:
                try:
                    deg = float(self._rotation.get())
                except (ValueError, AttributeError):
                    deg = 0.0
                if abs(deg) > 1e-6:
                    a = math.radians(deg)
                    ca, sa = math.cos(a), math.sin(a)
                    coords = [(x * ca - y * sa, x * sa + y * ca) for x, y in coords]
            return coords
        except ValueError:
            pass
        return None

    def _export(self) -> None:
        coords = self._build_coords()
        if not coords:
            messagebox.showerror("Error", "Invalid shape parameters.")
            return

        shape_name = self._shape_var.get().lower().replace(" ", "_")
        out_path = filedialog.asksaveasfilename(
            title="Save shape as DXF",
            defaultextension=".dxf",
            initialdir=self._settings.get("shape_output_dir") or None,
            initialfile=f"{shape_name}.dxf",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if not out_path:
            return

        try:
            write_polylines_dxf([coords], out_path, close=True)
            self._shape_status.configure(
                text=f"Saved → {Path(out_path).name}", text_color="#60c060"
            )
            self._last_out_path = out_path
            self._reveal_btn.configure(state="normal")
        except Exception as exc:
            self._shape_status.configure(text=f"Error: {exc}", text_color="#e06060")

    def _reveal_in_finder(self) -> None:
        if self._last_out_path:
            subprocess.run(["open", "-R", self._last_out_path])
