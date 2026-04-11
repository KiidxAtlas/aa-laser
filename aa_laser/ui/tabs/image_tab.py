"""Image to Outline tab.

Workflow:
  1. Load an image (jpg, png, bmp…)
  2. Tune preprocessing (blur, threshold, invert)
  3. Tune clean-up  (simplify tolerance, min area, real-world width)
  4. See the extracted outline live in the right canvas
  5. Edit: select and delete unwanted polylines on the canvas
  6. Export — full outline or selected-only
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from aa_laser.constants import _DIM, _SEL
from aa_laser.core.dxf_io import write_polylines_dxf
from aa_laser.core.image_trace import image_to_outlines
from aa_laser.ui.canvas import DxfCanvas
from aa_laser.ui.helpers import _section_label


class ImageTab(ctk.CTkFrame):
    """Image → outline tracing tab."""

    def __init__(self, master, settings: dict | None = None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings: dict = settings or {}
        self._img_path: str | None = None
        self._preview_job: str | None = None
        self._running: bool = False
        self._last_out: str | None = None
        self._ctk_thumb: ctk.CTkImage | None = None
        self._img_w_px: int = 0
        self._img_h_px: int = 0
        self._img_aspect: float = 1.0  # width / height pixel ratio
        self._aspect_locked: ctk.BooleanVar = ctk.BooleanVar(value=True)

        left = ctk.CTkFrame(self, width=310)
        left.pack(side="left", fill="y", padx=(10, 4), pady=10)
        left.pack_propagate(False)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        self._build_left(left)
        self._build_right(right)

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        left = ctk.CTkScrollableFrame(parent, fg_color="transparent", width=290)
        left.pack(fill="both", expand=True)

        # ── Image picker ──────────────────────────────────────────────────────
        _section_label(left, "Image")

        file_row = ctk.CTkFrame(left, fg_color="transparent")
        file_row.pack(fill="x", padx=8, pady=(0, 4))
        self._img_var = ctk.StringVar()
        ctk.CTkEntry(
            file_row, textvariable=self._img_var, placeholder_text="Select image…"
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            file_row, text="Browse", width=64, command=self._browse_image
        ).pack(side="right")

        # Thumbnail placeholder
        self._thumb_lbl = ctk.CTkLabel(left, text="", image=None, width=290, height=100)
        self._thumb_lbl.pack(padx=8, pady=(0, 4))

        _section_label(left, "Preprocessing")

        # Mode selector
        self._mode_var = ctk.StringVar(value="edges")
        ctk.CTkSegmentedButton(
            left,
            values=["edges", "threshold"],
            variable=self._mode_var,
            command=self._on_mode_change,
        ).pack(fill="x", padx=8, pady=(0, 6))

        # Container so both mode frames occupy the same slot
        mode_slot = ctk.CTkFrame(left, fg_color="transparent")
        mode_slot.pack(fill="x")

        # ── Edge-detect controls (shown by default) ──────────────────────────
        self._edge_frame = ctk.CTkFrame(mode_slot, fg_color="transparent")
        self._edge_frame.pack(fill="x", padx=8)

        ge = ctk.CTkFrame(self._edge_frame, fg_color="transparent")
        ge.pack(fill="x")
        ctk.CTkLabel(ge, text="Sigma", anchor="w", width=130).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._sigma = ctk.CTkEntry(ge, width=80)
        self._sigma.insert(0, "1.5")
        self._sigma.grid(row=0, column=1, padx=4, pady=3)
        self._sigma.bind("<KeyRelease>", self._schedule_trace)

        sens_row = ctk.CTkFrame(self._edge_frame, fg_color="transparent")
        sens_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(sens_row, text="Sensitivity", anchor="w", width=90).pack(
            side="left", padx=6
        )
        self._sens_pct_lbl = ctk.CTkLabel(
            sens_row, text="50 %", anchor="e", width=46, text_color=_DIM
        )
        self._sens_pct_lbl.pack(side="right", padx=6)
        self._sens_slider = ctk.CTkSlider(
            self._edge_frame,
            from_=0,
            to=100,
            number_of_steps=100,
            command=self._on_sensitivity_slider,
        )
        self._sens_slider.set(50)
        self._sens_slider.pack(fill="x", padx=8, pady=(2, 6))
        ctk.CTkLabel(
            self._edge_frame,
            text="Low ← more edges · fewer edges → High",
            text_color=_DIM,
            font=("Helvetica", 9),
            anchor="w",
        ).pack(anchor="w", padx=8, pady=(0, 4))

        # ── Threshold controls (hidden by default) ───────────────────────────
        self._thresh_frame = ctk.CTkFrame(mode_slot, fg_color="transparent")
        # not packed initially

        gt = ctk.CTkFrame(self._thresh_frame, fg_color="transparent")
        gt.pack(fill="x")
        ctk.CTkLabel(gt, text="Blur radius", anchor="w", width=130).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._blur = ctk.CTkEntry(gt, width=80)
        self._blur.insert(0, "1.5")
        self._blur.grid(row=0, column=1, padx=4, pady=3)
        self._blur.bind("<KeyRelease>", self._schedule_trace)

        ctk.CTkLabel(gt, text="Threshold (0-255)", anchor="w", width=130).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._thresh_entry = ctk.CTkEntry(gt, width=80)
        self._thresh_entry.insert(0, "128")
        self._thresh_entry.grid(row=1, column=1, padx=4, pady=3)
        self._thresh_entry.bind("<KeyRelease>", self._schedule_trace)

        self._thresh_slider = ctk.CTkSlider(
            self._thresh_frame,
            from_=0,
            to=255,
            number_of_steps=255,
            command=self._on_thresh_slider,
        )
        self._thresh_slider.set(128)
        self._thresh_slider.pack(fill="x", padx=8, pady=(2, 4))

        self._invert_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self._thresh_frame,
            text="Invert  (dark background → light foreground)",
            variable=self._invert_var,
            command=self._schedule_trace,
        ).pack(anchor="w", padx=10, pady=(0, 4))

        _section_label(left, "Clean-up")

        g2 = ctk.CTkFrame(left, fg_color="transparent")
        g2.pack(fill="x", padx=8)

        ctk.CTkLabel(g2, text="Simplify (px)", anchor="w", width=130).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._simplify = ctk.CTkEntry(g2, width=80)
        self._simplify.insert(0, "2.0")
        self._simplify.grid(row=0, column=1, padx=4, pady=3)
        self._simplify.bind("<KeyRelease>", self._schedule_trace)

        ctk.CTkLabel(g2, text="Min area (px²)", anchor="w", width=130).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._min_area = ctk.CTkEntry(g2, width=80)
        self._min_area.insert(0, "100")
        self._min_area.grid(row=1, column=1, padx=4, pady=3)
        self._min_area.bind("<KeyRelease>", self._schedule_trace)

        ctk.CTkLabel(g2, text="Max area (px²)", anchor="w", width=130).grid(
            row=2, column=0, padx=6, pady=3, sticky="w"
        )
        self._max_area = ctk.CTkEntry(g2, width=80, placeholder_text="none")
        self._max_area.grid(row=2, column=1, padx=4, pady=3)
        self._max_area.bind("<KeyRelease>", self._schedule_trace)

        ctk.CTkLabel(g2, text="Closing radius", anchor="w", width=130).grid(
            row=3, column=0, padx=6, pady=3, sticky="w"
        )
        self._close_r = ctk.CTkEntry(g2, width=80)
        self._close_r.insert(0, "1")
        self._close_r.grid(row=3, column=1, padx=4, pady=3)
        self._close_r.bind("<KeyRelease>", self._schedule_trace)

        _section_label(left, "Real-world scale")

        g3 = ctk.CTkFrame(left, fg_color="transparent")
        g3.pack(fill="x", padx=8)

        ctk.CTkLabel(g3, text="Width (mm)", anchor="w", width=130).grid(
            row=0, column=0, padx=6, pady=3, sticky="w"
        )
        self._width_mm = ctk.CTkEntry(g3, width=80)
        self._width_mm.insert(0, "50.0")
        self._width_mm.grid(row=0, column=1, padx=4, pady=3)
        self._width_mm.bind("<KeyRelease>", self._on_width_changed)

        ctk.CTkLabel(g3, text="Height (mm)", anchor="w", width=130).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._height_mm = ctk.CTkEntry(g3, width=80)
        self._height_mm.insert(0, "---")
        self._height_mm.grid(row=1, column=1, padx=4, pady=3)
        self._height_mm.bind("<KeyRelease>", self._on_height_changed)

        self._lock_btn = ctk.CTkCheckBox(
            g3,
            text="Lock aspect ratio",
            variable=self._aspect_locked,
            width=200,
        )
        self._lock_btn.grid(
            row=2, column=0, columnspan=2, padx=6, pady=(2, 2), sticky="w"
        )

        self._size_info_lbl = ctk.CTkLabel(
            g3,
            text="",
            text_color=_DIM,
            font=("Helvetica", 9),
            anchor="w",
        )
        self._size_info_lbl.grid(
            row=3, column=0, columnspan=2, padx=6, pady=(0, 2), sticky="w"
        )

        self._status = ctk.CTkLabel(
            left,
            text="Load an image to begin.",
            text_color=_DIM,
            anchor="w",
            wraplength=280,
        )
        self._status.pack(anchor="w", padx=10, pady=(0, 4))

        self._progress = ctk.CTkProgressBar(left)
        self._progress.pack(fill="x", padx=8, pady=(0, 6))
        self._progress.set(0)

        _section_label(left, "Export")

        self._export_all_btn = ctk.CTkButton(
            left,
            text="Export All as DXF…",
            height=36,
            state="disabled",
            command=self._export_all,
        )
        self._export_all_btn.pack(fill="x", padx=8, pady=(0, 4))

        self._export_sel_btn = ctk.CTkButton(
            left,
            text="Export Selected as DXF…",
            height=36,
            fg_color="transparent",
            border_width=1,
            state="disabled",
            command=self._export_selected,
        )
        self._export_sel_btn.pack(fill="x", padx=8, pady=(0, 4))

        self._reveal_btn = ctk.CTkButton(
            left,
            text="Show in Finder",
            height=26,
            fg_color="transparent",
            border_width=1,
            state="disabled",
            command=self._reveal_in_finder,
        )
        self._reveal_btn.pack(fill="x", padx=8, pady=(0, 8))

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self, parent: ctk.CTkFrame) -> None:
        # Canvas toolbar
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", padx=4, pady=(0, 4))

        ctk.CTkButton(
            toolbar,
            text="Select All",
            width=90,
            height=26,
            command=lambda: self._canvas.select_all(),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            toolbar,
            text="Deselect",
            width=80,
            height=26,
            command=lambda: self._canvas.deselect_all(),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            toolbar, text="Fit", width=50, height=26, command=lambda: self._canvas.fit()
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            toolbar,
            text="Delete Selected  [Del]",
            width=140,
            height=26,
            fg_color="#8b1a1a",
            hover_color="#b22222",
            command=self._delete_selected,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            toolbar,
            text="↩ Undo",
            width=70,
            height=26,
            fg_color="transparent",
            border_width=1,
            command=self._undo_delete,
        ).pack(side="left")
        self._mode_seg = ctk.CTkSegmentedButton(
            toolbar,
            values=["Select", "Draw", "Edit"],
            command=self._on_toolbar_mode,
        )
        self._mode_seg.set("Select")
        self._mode_seg.pack(side="left", padx=(4, 0))

        self._sel_label = ctk.CTkLabel(toolbar, text="", text_color=_DIM, anchor="e")
        self._sel_label.pack(side="right", padx=8)

        self._canvas = DxfCanvas(
            parent,
            selectable=True,
            on_change=self._on_sel_change,
            on_mode_change=self._on_canvas_mode_change,
        )
        self._canvas.pack(fill="both", expand=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = _DIM) -> None:
        self._status.configure(text=text, text_color=color)

    def _on_sel_change(self, count: int) -> None:
        if count:
            self._sel_label.configure(text=f"{count} selected", text_color=_SEL)
            self._export_sel_btn.configure(state="normal")
        else:
            self._sel_label.configure(text="", text_color=_DIM)
            self._export_sel_btn.configure(state="disabled")

    # ── Image loading ─────────────────────────────────────────────────────────

    def _browse_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._img_var.set(path)
            self._img_path = path
            self._load_thumbnail(path)
            self._schedule_trace()

    def _load_thumbnail(self, path: str) -> None:
        """Update the thumbnail and store pixel dimensions."""
        try:
            img = Image.open(path)
            self._img_w_px = img.width
            self._img_h_px = img.height
            self._img_aspect = img.width / max(img.height, 1)
            # Update height field from current width value
            self._update_height_from_width()
            img.thumbnail((290, 140), Image.LANCZOS)
            self._ctk_thumb = ctk.CTkImage(img, size=img.size)
            self._thumb_lbl.configure(image=self._ctk_thumb, text="")
        except Exception:
            self._thumb_lbl.configure(image=None, text="(preview unavailable)")

    def _update_height_from_width(self) -> None:
        """Recompute Height entry from current Width and stored aspect ratio."""
        if self._img_aspect <= 0:
            return
        try:
            w = float(self._width_mm.get() or "50.0")
            h = w / self._img_aspect
            self._height_mm.configure(state="normal")
            self._height_mm.delete(0, "end")
            self._height_mm.insert(0, f"{h:.2f}")
            if self._img_w_px and self._img_h_px:
                self._size_info_lbl.configure(
                    text=f"{self._img_w_px}×{self._img_h_px} px → {w:.1f}×{h:.1f} mm"
                )
        except ValueError:
            pass

    def _on_width_changed(self, *_) -> None:
        if self._aspect_locked.get():
            self._update_height_from_width()
        self._schedule_trace()

    def _on_height_changed(self, *_) -> None:
        if self._aspect_locked.get() and self._img_aspect > 0:
            try:
                h = float(self._height_mm.get() or "0")
                w = h * self._img_aspect
                self._width_mm.delete(0, "end")
                self._width_mm.insert(0, f"{w:.2f}")
            except ValueError:
                pass
        self._schedule_trace()

    # ── Tracing ───────────────────────────────────────────────────────────────

    def _on_mode_change(self, value: str) -> None:
        if value == "edges":
            self._thresh_frame.pack_forget()
            self._edge_frame.pack(fill="x")
        else:
            self._edge_frame.pack_forget()
            self._thresh_frame.pack(fill="x")
        self._schedule_trace()

    def _on_sensitivity_slider(self, value: float) -> None:
        self._sens_pct_lbl.configure(text=f"{int(round(value))} %")
        self._schedule_trace()

    def _schedule_trace(self, *_) -> None:
        if not self._img_path:
            return
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(450, self._start_trace_thread)

    def _start_trace_thread(self) -> None:
        if self._running or not self._img_path:
            return
        self._running = True
        self._progress.configure(mode="indeterminate")
        self._progress.start()
        self._set_status("Tracing…")
        threading.Thread(target=self._run_trace, daemon=True).start()

    def _run_trace(self) -> None:
        try:
            mode = self._mode_var.get()
            simplify = float(self._simplify.get() or "2.0")
            min_area = float(self._min_area.get() or "100")
            max_area_s = self._max_area.get().strip()
            max_area = float(max_area_s) if max_area_s else None
            close_r = max(0, int(float(self._close_r.get() or "1")))
            width_mm = float(self._width_mm.get() or "50.0")

            kwargs: dict = dict(
                mode=mode,
                simplify_tol=simplify,
                min_area_px=min_area,
                max_area_px=max_area,
                close_radius=close_r,
                width_mm=width_mm,
            )

            if mode == "edges":
                kwargs["sigma"] = float(self._sigma.get() or "1.5")
                # Sensitivity 0-100: 0=many edges, 100=few edges
                # hi_pct = percentile above which pixels are "strong"
                # lo_pct = lower cutoff for weak/hysteresis edges
                sens = float(self._sens_slider.get())
                hi = 0.9 - sens * 0.004  # 0→0.90, 100→0.50
                lo = max(0.0, hi - 0.25)
                kwargs["canny_lo"] = lo
                kwargs["canny_hi"] = hi
            else:
                kwargs["blur_radius"] = float(self._blur.get() or "1.5")
                thresh = int(float(self._thresh_entry.get() or "128"))
                kwargs["threshold"] = max(0, min(255, thresh))
                kwargs["invert"] = bool(self._invert_var.get())

            _display_img, polys, img_w_px, img_h_px = image_to_outlines(
                self._img_path, **kwargs
            )
            count = len(polys)
            width_mm_val = float(kwargs["width_mm"])
            height_mm_val = img_h_px / max(img_w_px, 1) * width_mm_val

            def _done():
                self._running = False
                self._progress.stop()
                self._progress.configure(mode="determinate")
                self._progress.set(1.0)
                self._canvas.set_image_bounds(width_mm_val, height_mm_val)
                # Send faded source image as background overlay
                if _display_img is not None:
                    try:
                        bg_rgb = (0x16, 0x21, 0x3e)  # matches _BG
                        bg_layer = Image.new("RGB", _display_img.size, bg_rgb)
                        faded = Image.blend(
                            _display_img.convert("RGB"), bg_layer, 0.7
                        )
                        self._canvas.set_background_image(
                            faded, width_mm_val, height_mm_val
                        )
                    except Exception:
                        pass
                if polys:
                    self._canvas.load(polys)
                    self._export_all_btn.configure(state="normal")
                    self._set_status(
                        f"{count} contour(s) extracted  ·  "
                        f"{img_w_px}×{img_h_px} px → "
                        f"{width_mm_val:.1f}×{height_mm_val:.1f} mm",
                        "#60c060",
                    )
                else:
                    self._set_status(
                        "No contours found. Try adjusting threshold or inverting.",
                        "#e06060",
                    )

            self.after(0, _done)

        except Exception as exc:
            _msg = str(exc)

            def _err():
                self._running = False
                self._progress.stop()
                self._progress.configure(mode="determinate")
                self._progress.set(0)
                self._set_status(f"Error: {_msg}", "#e06060")

            self.after(0, _err)

    # ── Canvas actions ────────────────────────────────────────────────────────

    def _delete_selected(self) -> None:
        n = self._canvas.delete_selected()
        if n:
            self._set_status(f"Deleted {n} polyline(s). Use ↩ Undo to restore.")
        if self._canvas.poly_count == 0:
            self._export_all_btn.configure(state="disabled")

    def _undo_delete(self) -> None:
        if self._canvas.undo_delete():
            self._set_status("Undo: polylines restored.")
            self._export_all_btn.configure(state="normal")
        else:
            self._set_status("Nothing to undo.")

    # ── Threshold slider sync ─────────────────────────────────────────────────

    def _on_thresh_slider(self, value: float) -> None:
        v = int(round(value))
        self._thresh_entry.delete(0, "end")
        self._thresh_entry.insert(0, str(v))
        self._schedule_trace()

    def _on_toolbar_mode(self, value: str) -> None:
        self._canvas.set_mode(value.lower())

    def _on_canvas_mode_change(self, mode: str) -> None:
        self._mode_seg.set(mode.capitalize())

    # ── Export ────────────────────────────────────────────────────────────────

    def _get_save_path(self, title: str) -> str | None:
        stem = Path(self._img_path).stem if self._img_path else "outline"
        return filedialog.asksaveasfilename(
            title=title,
            defaultextension=".dxf",
            initialfile=f"{stem}_outline.dxf",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )

    def _export_all(self) -> None:
        polys = self._canvas.get_active() + self._canvas.get_selected()
        # All means everything currently in the canvas regardless of selection
        if not polys:
            messagebox.showerror("Export", "No polylines to export.")
            return
        out = self._get_save_path("Export all outlines as DXF")
        if not out:
            return
        try:
            write_polylines_dxf(polys, out, close=True)
            self._last_out = out
            self._reveal_btn.configure(state="normal")
            self._set_status(
                f"Exported {len(polys)} polylines → {Path(out).name}", "#60c060"
            )
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _export_selected(self) -> None:
        polys = self._canvas.get_selected()
        if not polys:
            messagebox.showinfo("Export Selected", "Nothing is selected.")
            return
        out = self._get_save_path("Export selected outlines as DXF")
        if not out:
            return
        try:
            write_polylines_dxf(polys, out, close=True)
            self._last_out = out
            self._reveal_btn.configure(state="normal")
            self._set_status(
                f"Exported {len(polys)} selected polylines → {Path(out).name}",
                "#60c060",
            )
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _reveal_in_finder(self) -> None:
        if self._last_out:
            subprocess.run(["open", "-R", self._last_out])
