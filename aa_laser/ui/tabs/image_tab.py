"""Image to Outline tab."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from aa_laser.constants import _DIM, _SEL
from aa_laser.core.dxf_io import write_polylines_dxf
from aa_laser.core.image_trace import image_to_outlines
from aa_laser.ui.canvas import DxfCanvas
from aa_laser.ui.helpers import _section_label


class ImageTab(QWidget):
    """Image → outline tracing tab."""

    _trace_done = Signal(object)  # (display_img, polys, img_w_px, img_h_px, width_mm)
    _trace_error = Signal(str)

    def __init__(self, parent: QWidget | None = None, settings: dict | None = None):
        super().__init__(parent)
        self._settings: dict = settings or {}
        self._img_path: str | None = None
        self._running: bool = False

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._start_trace_thread)

        self._trace_done.connect(self._handle_trace_done)
        self._trace_error.connect(self._handle_trace_error)
        self._last_out: str | None = None
        self._last_display_img = None
        self._last_width_mm: float = 0.0
        self._last_height_mm: float = 0.0
        self._img_w_px: int = 0
        self._img_h_px: int = 0
        self._img_aspect: float = 1.0
        self._aspect_locked: bool = True

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Left panel (scrollable) ──────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(310)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(left_w)
        root.addWidget(scroll)

        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        root.addWidget(right_w, stretch=1)

        self._build_left(left)
        self._build_right(right)

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self, layout: QVBoxLayout) -> None:
        _section_label(layout, "Image")
        file_row = QHBoxLayout()
        self._img_edit = QLineEdit()
        self._img_edit.setPlaceholderText("Select image…")
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(64)
        browse_btn.clicked.connect(self._browse_image)
        file_row.addWidget(self._img_edit, stretch=1)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedHeight(100)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb_lbl)

        _section_label(layout, "Preprocessing")

        # Threshold controls
        self._thresh_w = QWidget()
        tg = QGridLayout(self._thresh_w)
        tg.setContentsMargins(0, 0, 0, 0)
        tg.addWidget(QLabel("Blur radius"), 0, 0)
        self._blur = QLineEdit("1.5")
        self._blur.setFixedWidth(80)
        self._blur.textChanged.connect(self._schedule_trace)
        tg.addWidget(self._blur, 0, 1)
        tg.addWidget(QLabel("Threshold (0-255)"), 1, 0)
        self._thresh_entry = QLineEdit("128")
        self._thresh_entry.setFixedWidth(80)
        self._thresh_entry.textChanged.connect(self._schedule_trace)
        tg.addWidget(self._thresh_entry, 1, 1)
        layout.addWidget(self._thresh_w)

        self._thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self._thresh_slider.setRange(0, 255)
        self._thresh_slider.setValue(128)
        self._thresh_slider.valueChanged.connect(self._on_thresh_slider)
        layout.addWidget(self._thresh_slider)

        self._invert_cb = QCheckBox("Invert  (dark background → light foreground)")
        self._invert_cb.stateChanged.connect(self._schedule_trace)
        layout.addWidget(self._invert_cb)

        _section_label(layout, "Clean-up")
        g2 = QGridLayout()
        g2.addWidget(QLabel("Simplify (px)"), 0, 0)
        self._simplify = QLineEdit("2.0")
        self._simplify.setFixedWidth(80)
        self._simplify.textChanged.connect(self._schedule_trace)
        g2.addWidget(self._simplify, 0, 1)
        g2.addWidget(QLabel("Min area (px²)"), 1, 0)
        self._min_area = QLineEdit("100")
        self._min_area.setFixedWidth(80)
        self._min_area.textChanged.connect(self._schedule_trace)
        g2.addWidget(self._min_area, 1, 1)
        g2.addWidget(QLabel("Max area (px²)"), 2, 0)
        self._max_area = QLineEdit()
        self._max_area.setFixedWidth(80)
        self._max_area.setPlaceholderText("none")
        self._max_area.textChanged.connect(self._schedule_trace)
        g2.addWidget(self._max_area, 2, 1)
        g2.addWidget(QLabel("Closing radius"), 3, 0)
        self._close_r = QLineEdit("1")
        self._close_r.setFixedWidth(80)
        self._close_r.textChanged.connect(self._schedule_trace)
        g2.addWidget(self._close_r, 3, 1)
        layout.addLayout(g2)

        _section_label(layout, "Real-world scale")
        g3 = QGridLayout()
        g3.addWidget(QLabel("Width (mm)"), 0, 0)
        self._width_mm = QLineEdit("50.0")
        self._width_mm.setFixedWidth(80)
        self._width_mm.textChanged.connect(self._on_width_changed)
        g3.addWidget(self._width_mm, 0, 1)
        g3.addWidget(QLabel("Height (mm)"), 1, 0)
        self._height_mm = QLineEdit("---")
        self._height_mm.setFixedWidth(80)
        self._height_mm.textChanged.connect(self._on_height_changed)
        g3.addWidget(self._height_mm, 1, 1)
        layout.addLayout(g3)

        self._lock_cb = QCheckBox("Lock aspect ratio")
        self._lock_cb.setChecked(True)
        self._lock_cb.stateChanged.connect(
            lambda s: setattr(self, "_aspect_locked", bool(s))
        )
        layout.addWidget(self._lock_cb)

        self._size_info_lbl = QLabel("")
        self._size_info_lbl.setStyleSheet(f"color: {_DIM}; font-size: 9px;")
        layout.addWidget(self._size_info_lbl)

        self._status = QLabel("Load an image to begin.")
        self._status.setStyleSheet(f"color: {_DIM};")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._bg_visible_cb = QCheckBox("Show image in background")
        self._bg_visible_cb.setChecked(True)
        self._bg_visible_cb.stateChanged.connect(self._on_bg_visible_changed)
        layout.addWidget(self._bg_visible_cb)

        _section_label(layout, "Export")
        self._export_all_btn = QPushButton("Export All as DXF…")
        self._export_all_btn.setMinimumHeight(36)
        self._export_all_btn.setProperty("role", "primary")
        self._export_all_btn.setEnabled(False)
        self._export_all_btn.clicked.connect(self._export_all)
        layout.addWidget(self._export_all_btn)

        self._export_sel_btn = QPushButton("Export Selected as DXF…")
        self._export_sel_btn.setMinimumHeight(36)
        self._export_sel_btn.setEnabled(False)
        self._export_sel_btn.clicked.connect(self._export_selected)
        layout.addWidget(self._export_sel_btn)

        self._reveal_btn = QPushButton("Show in Finder")
        self._reveal_btn.setMinimumHeight(26)
        self._reveal_btn.setEnabled(False)
        self._reveal_btn.clicked.connect(self._reveal_in_finder)
        layout.addWidget(self._reveal_btn)

        layout.addStretch()

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self, layout: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()
        for label, slot in [
            ("Select All", lambda: self._canvas.select_all()),
            ("Deselect", lambda: self._canvas.deselect_all()),
            ("Fit", lambda: self._canvas.fit()),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.clicked.connect(slot)
            toolbar.addWidget(b)

        del_btn = QPushButton("Delete Selected  [Del]")
        del_btn.setFixedHeight(26)
        del_btn.setStyleSheet(
            "background: transparent;border: 1px solid #f85149;color: #f85149;"
        )
        del_btn.clicked.connect(self._delete_selected)
        toolbar.addWidget(del_btn)

        undo_btn = QPushButton("↩ Undo")
        undo_btn.setFixedHeight(26)
        undo_btn.clicked.connect(self._undo_delete)
        toolbar.addWidget(undo_btn)

        # Mode buttons
        self._mode_btns: dict[str, QPushButton] = {}
        for mode in ("Select", "Draw", "Edit"):
            b = QPushButton(mode)
            b.setFixedHeight(26)
            b.setProperty("active", mode == "Select")
            b.clicked.connect(lambda checked, m=mode: self._on_toolbar_mode(m))
            toolbar.addWidget(b)
            self._mode_btns[mode] = b

        self._sel_label = QLabel("")
        self._sel_label.setStyleSheet(f"color: {_DIM};")
        self._sel_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        toolbar.addWidget(self._sel_label, stretch=1)

        layout.addLayout(toolbar)

        self._canvas = DxfCanvas(
            selectable=True,
            on_change=self._on_sel_change,
            on_mode_change=self._on_canvas_mode_change,
        )
        layout.addWidget(self._canvas, stretch=1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = _DIM) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color};")

    def _on_sel_change(self, count: int) -> None:
        if count:
            self._sel_label.setText(f"{count} selected")
            self._sel_label.setStyleSheet(f"color: {_SEL};")
            self._export_sel_btn.setEnabled(True)
        else:
            self._sel_label.setText("")
            self._sel_label.setStyleSheet(f"color: {_DIM};")
            self._export_sel_btn.setEnabled(False)

    # ── Image loading ─────────────────────────────────────────────────────────

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)",
        )
        if path:
            self._img_edit.setText(path)
            self._img_path = path
            self._load_thumbnail(path)
            self._schedule_trace()

    def _load_thumbnail(self, path: str) -> None:
        try:
            img = Image.open(path)
            self._img_w_px = img.width
            self._img_h_px = img.height
            self._img_aspect = img.width / max(img.height, 1)
            self._update_height_from_width()
            img.thumbnail((290, 140), Image.LANCZOS)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            pm = QPixmap.fromImage(qimg.copy())
            self._thumb_lbl.setPixmap(pm)
        except Exception:
            self._thumb_lbl.setText("(preview unavailable)")

    def _update_height_from_width(self) -> None:
        if self._img_aspect <= 0:
            return
        try:
            w = float(self._width_mm.text() or "50.0")
            h = w / self._img_aspect
            self._height_mm.blockSignals(True)
            self._height_mm.setText(f"{h:.2f}")
            self._height_mm.blockSignals(False)
            if self._img_w_px and self._img_h_px:
                self._size_info_lbl.setText(
                    f"{self._img_w_px}×{self._img_h_px} px → {w:.1f}×{h:.1f} mm"
                )
        except ValueError:
            pass

    def _on_width_changed(self, *_) -> None:
        if self._aspect_locked:
            self._update_height_from_width()
        self._schedule_trace()

    def _on_height_changed(self, *_) -> None:
        if self._aspect_locked and self._img_aspect > 0:
            try:
                h = float(self._height_mm.text() or "0")
                w = h * self._img_aspect
                self._width_mm.blockSignals(True)
                self._width_mm.setText(f"{w:.2f}")
                self._width_mm.blockSignals(False)
            except ValueError:
                pass
        self._schedule_trace()

    # ── Tracing ───────────────────────────────────────────────────────────────

    def _on_sensitivity_slider(self, value: int) -> None:
        self._sens_pct_lbl.setText(f"{value} %")
        self._schedule_trace()

    def _schedule_trace(self, *_) -> None:
        if not self._img_path:
            return
        self._preview_timer.start(450)

    def _start_trace_thread(self) -> None:
        if self._running or not self._img_path:
            return
        # Collect ALL widget values on the GUI thread (thread-safe)
        try:
            simplify = float(self._simplify.text() or "2.0")
            min_area = float(self._min_area.text() or "100")
            max_area_s = self._max_area.text().strip()
            max_area = float(max_area_s) if max_area_s else None
            close_r = max(0, int(float(self._close_r.text() or "1")))
            width_mm = float(self._width_mm.text() or "50.0")
        except ValueError:
            return

        try:
            blur_radius = float(self._blur.text() or "1.5")
        except ValueError:
            blur_radius = 1.5
        try:
            thresh = int(float(self._thresh_entry.text() or "128"))
        except ValueError:
            thresh = 128

        kwargs: dict = dict(
            blur_radius=blur_radius,
            threshold=max(0, min(255, thresh)),
            invert=self._invert_cb.isChecked(),
            simplify_tol=simplify,
            min_area_px=min_area,
            max_area_px=max_area,
            close_radius=close_r,
            width_mm=width_mm,
        )

        self._running = True
        self._progress.setRange(0, 0)  # indeterminate
        self._set_status("Tracing…")
        threading.Thread(target=self._run_trace, args=(kwargs,), daemon=True).start()

    def _run_trace(self, kwargs: dict) -> None:
        try:
            result = image_to_outlines(self._img_path, **kwargs)
            self._trace_done.emit((*result, kwargs["width_mm"]))
        except Exception as exc:
            self._trace_error.emit(str(exc))

    def _handle_trace_done(self, payload: tuple) -> None:
        _display_img, polys, img_w_px, img_h_px, width_mm_val = payload
        width_mm_val = float(width_mm_val)
        height_mm_val = img_h_px / max(img_w_px, 1) * width_mm_val
        count = len(polys)

        self._running = False
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._canvas.set_image_bounds(width_mm_val, height_mm_val)
        self._last_display_img = _display_img
        self._last_width_mm = width_mm_val
        self._last_height_mm = height_mm_val
        if _display_img is not None and self._bg_visible_cb.isChecked():
            try:
                bg_rgb = (0x16, 0x21, 0x3E)
                bg_layer = Image.new("RGB", _display_img.size, bg_rgb)
                faded = Image.blend(_display_img.convert("RGB"), bg_layer, 0.7)
                self._canvas.set_background_image(faded, width_mm_val, height_mm_val)
            except Exception:
                pass
        if polys:
            self._canvas.load(polys)
            self._export_all_btn.setEnabled(True)
            self._set_status(
                f"{count} contour(s) extracted  ·  "
                f"{img_w_px}×{img_h_px} px → "
                f"{width_mm_val:.1f}×{height_mm_val:.1f} mm",
                "#3fb950",
            )
        else:
            self._set_status(
                "No contours found. Try adjusting threshold or inverting.",
                "#f85149",
            )

    def _handle_trace_error(self, msg: str) -> None:
        self._running = False
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._set_status(f"Error: {msg}", "#f85149")

    # ── Canvas actions ────────────────────────────────────────────────────────

    def _delete_selected(self) -> None:
        n = self._canvas.delete_selected()
        if n:
            self._set_status(f"Deleted {n} polyline(s). Use ↩ Undo to restore.")
        if self._canvas.poly_count == 0:
            self._export_all_btn.setEnabled(False)

    def _undo_delete(self) -> None:
        if self._canvas.undo_delete():
            self._set_status("Undo: polylines restored.")
            self._export_all_btn.setEnabled(True)
        else:
            self._set_status("Nothing to undo.")

    def _on_thresh_slider(self, value: int) -> None:
        self._thresh_entry.blockSignals(True)
        self._thresh_entry.setText(str(value))
        self._thresh_entry.blockSignals(False)
        self._schedule_trace()

    def _on_bg_visible_changed(self, state: int) -> None:
        if state and self._last_display_img is not None:
            try:
                bg_rgb = (0x16, 0x21, 0x3E)
                bg_layer = Image.new("RGB", self._last_display_img.size, bg_rgb)
                faded = Image.blend(
                    self._last_display_img.convert("RGB"), bg_layer, 0.7
                )
                self._canvas.set_background_image(
                    faded, self._last_width_mm, self._last_height_mm
                )
            except Exception:
                pass
        elif not state:
            self._canvas.clear_background_image()

    def _set_active_mode_btn(self, value: str) -> None:
        v = value.lower()
        for k, b in self._mode_btns.items():
            b.setProperty("active", k.lower() == v)
            b.style().unpolish(b)
            b.style().polish(b)

    def _on_toolbar_mode(self, value: str) -> None:
        self._set_active_mode_btn(value)
        self._canvas.set_mode(value.lower())

    def _on_canvas_mode_change(self, mode: str) -> None:
        self._set_active_mode_btn(mode)

    # ── Export ────────────────────────────────────────────────────────────────

    def _get_save_path(self, title: str) -> str | None:
        stem = Path(self._img_path).stem if self._img_path else "outline"
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            f"{stem}_outline.dxf",
            "DXF files (*.dxf);;All files (*)",
        )
        return path or None

    def _export_all(self) -> None:
        polys = self._canvas.get_active() + self._canvas.get_selected()
        if not polys:
            QMessageBox.critical(self, "Export", "No polylines to export.")
            return
        out = self._get_save_path("Export all outlines as DXF")
        if not out:
            return
        try:
            write_polylines_dxf(polys, out, close=True)
            self._last_out = out
            self._reveal_btn.setEnabled(True)
            self._set_status(
                f"Exported {len(polys)} polylines → {Path(out).name}", "#3fb950"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _export_selected(self) -> None:
        polys = self._canvas.get_selected()
        if not polys:
            QMessageBox.information(self, "Export Selected", "Nothing is selected.")
            return
        out = self._get_save_path("Export selected outlines as DXF")
        if not out:
            return
        try:
            write_polylines_dxf(polys, out, close=True)
            self._last_out = out
            self._reveal_btn.setEnabled(True)
            self._set_status(
                f"Exported {len(polys)} selected polylines → {Path(out).name}",
                "#3fb950",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _reveal_in_finder(self) -> None:
        if self._last_out:
            subprocess.run(["open", "-R", self._last_out])
