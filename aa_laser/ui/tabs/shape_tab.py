"""Shape Creator tab."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from aa_laser.constants import _DIM, _SEL, _SHAPES
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


def _param_row(grid: QGridLayout, row: int, label: str, default: str) -> QLineEdit:
    grid.addWidget(QLabel(label), row, 0)
    e = QLineEdit(default)
    e.setFixedWidth(80)
    grid.addWidget(e, row, 1)
    return e


class ShapeTab(QWidget):
    def __init__(self, parent: QWidget | None = None, settings: dict | None = None):
        super().__init__(parent)
        self._settings: dict = settings or {}
        self._preview_timer: QTimer | None = None
        self._last_out_path: str | None = None
        self._canvas_dirty: bool = False

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        left_w = QWidget()
        left_w.setFixedWidth(290)
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)

        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)

        root.addWidget(left_w)
        root.addWidget(right_w, stretch=1)

        self._build_left(left)
        self._build_right(right)
        self._update_preview()

    def _build_left(self, layout: QVBoxLayout) -> None:
        _section_label(layout, "Shape")
        self._shape_combo = QComboBox()
        self._shape_combo.addItems(_SHAPES)
        self._shape_combo.currentTextChanged.connect(self._switch_shape)
        layout.addWidget(self._shape_combo)

        # Stacked param panels
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._rect_page, self._rect_w, self._rect_h, self._rect_cr = self._make_rect()
        self._circle_page, self._circ_r, self._circ_n = self._make_circle()
        self._ellipse_page, self._ell_rx, self._ell_ry, self._ell_n = (
            self._make_ellipse()
        )
        self._polygon_page, self._poly_sides, self._poly_r = self._make_polygon()

        self._stack.addWidget(self._rect_page)
        self._stack.addWidget(self._circle_page)
        self._stack.addWidget(self._ellipse_page)
        self._stack.addWidget(self._polygon_page)
        self._stack.setCurrentIndex(0)

        # Rotation
        rot_row = QHBoxLayout()
        rot_row.addWidget(QLabel("Rotation (°)"))
        self._rotation = QLineEdit("0")
        self._rotation.setFixedWidth(80)
        self._rotation.textChanged.connect(self._schedule_preview)
        rot_row.addWidget(self._rotation)
        layout.addLayout(rot_row)

        # Regenerate
        self._regen_btn = QPushButton("↺ Regenerate")
        self._regen_btn.setMinimumHeight(30)
        self._regen_btn.setEnabled(False)
        self._regen_btn.setToolTip("Reset canvas to generated shape")
        self._regen_btn.clicked.connect(self._on_regenerate)
        layout.addWidget(self._regen_btn)

        # Export
        export_btn = QPushButton("Export DXF…")
        export_btn.setMinimumHeight(38)
        export_btn.setProperty("role", "primary")
        export_btn.clicked.connect(self._export)
        layout.addWidget(export_btn)

        self._shape_status = QLabel("")
        self._shape_status.setStyleSheet(f"color: {_DIM};")
        self._shape_status.setWordWrap(True)
        layout.addWidget(self._shape_status)

        self._reveal_btn = QPushButton("Show in Finder")
        self._reveal_btn.setMinimumHeight(26)
        self._reveal_btn.setEnabled(False)
        self._reveal_btn.clicked.connect(self._reveal_in_finder)
        layout.addWidget(self._reveal_btn)

        layout.addStretch()

    def _make_rect(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        rw = _param_row(g, 0, "Width (mm)", "50.0")
        rh = _param_row(g, 1, "Height (mm)", "30.0")
        cr = _param_row(g, 2, "Corner radius (mm)", "0")
        for e in (rw, rh, cr):
            e.textChanged.connect(self._schedule_preview)
        return w, rw, rh, cr

    def _make_circle(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        r = _param_row(g, 0, "Radius (mm)", "25.0")
        n = _param_row(g, 1, "Segments", "64")
        for e in (r, n):
            e.textChanged.connect(self._schedule_preview)
        return w, r, n

    def _make_ellipse(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        rx = _param_row(g, 0, "X radius (mm)", "40.0")
        ry = _param_row(g, 1, "Y radius (mm)", "20.0")
        n = _param_row(g, 2, "Segments", "64")
        for e in (rx, ry, n):
            e.textChanged.connect(self._schedule_preview)
        return w, rx, ry, n

    def _make_polygon(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        sides = _param_row(g, 0, "Sides", "6")
        r = _param_row(g, 1, "Radius (mm)", "25.0")
        for e in (sides, r):
            e.textChanged.connect(self._schedule_preview)
        return w, sides, r

    def _switch_shape(self, value: str) -> None:
        idx = {"Rectangle": 0, "Circle": 1, "Ellipse": 2}.get(value, 3)
        self._stack.setCurrentIndex(idx)
        self._schedule_preview()

    def _build_right(self, layout: QVBoxLayout) -> None:
        # Mode toolbar
        toolbar = QHBoxLayout()
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
            on_poly_change=self._on_canvas_edit,
        )
        layout.addWidget(self._canvas, stretch=1)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _schedule_preview(self, *_) -> None:
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._update_preview)
        self._preview_timer.start(250)

    def _update_preview(self) -> None:
        if self._canvas_dirty:
            return
        coords = self._build_coords()
        if coords:
            self._canvas.load([coords])

    def _build_coords(self) -> list[tuple[float, float]] | None:
        shape = self._shape_combo.currentText()
        try:
            coords: list[tuple[float, float]] | None = None
            if shape == "Rectangle":
                w = float(self._rect_w.text())
                h = float(self._rect_h.text())
                try:
                    cr = max(0.0, float(self._rect_cr.text()))
                except ValueError:
                    cr = 0.0
                if w > 0 and h > 0:
                    coords = (
                        shape_rect_rounded(w, h, cr) if cr > 0 else shape_rect(w, h)
                    )
            elif shape == "Circle":
                r = float(self._circ_r.text())
                n = max(3, int(self._circ_n.text()))
                if r > 0:
                    coords = shape_circle(r, n)
            elif shape == "Ellipse":
                rx = float(self._ell_rx.text())
                ry = float(self._ell_ry.text())
                n = max(3, int(self._ell_n.text()))
                if rx > 0 and ry > 0:
                    coords = shape_ellipse(rx, ry, n)
            else:
                sides = max(3, int(self._poly_sides.text()))
                r = float(self._poly_r.text())
                if r > 0:
                    coords = shape_polygon(sides, r)
            if coords is not None:
                try:
                    deg = float(self._rotation.text())
                except ValueError:
                    deg = 0.0
                if abs(deg) > 1e-6:
                    a = math.radians(deg)
                    ca, sa = math.cos(a), math.sin(a)
                    coords = [(x * ca - y * sa, x * sa + y * ca) for x, y in coords]
            return coords
        except ValueError:
            pass
        return None

    def _on_canvas_edit(self) -> None:
        self._canvas_dirty = True
        self._regen_btn.setEnabled(True)

    def _on_regenerate(self) -> None:
        self._canvas_dirty = False
        self._regen_btn.setEnabled(False)
        coords = self._build_coords()
        if coords:
            self._canvas.load([coords])

    def _on_sel_change(self, count: int) -> None:
        if count:
            self._sel_label.setText(f"{count} selected")
            self._sel_label.setStyleSheet(f"color: {_SEL};")
        else:
            self._sel_label.setText("")
            self._sel_label.setStyleSheet(f"color: {_DIM};")

    def _set_active_mode_btn(self, mode: str) -> None:
        v = mode.lower()
        for k, b in self._mode_btns.items():
            b.setProperty("active", k.lower() == v)
            b.style().unpolish(b)
            b.style().polish(b)

    def _on_toolbar_mode(self, mode: str) -> None:
        self._set_active_mode_btn(mode)
        self._canvas.set_mode(mode.lower())

    def _on_canvas_mode_change(self, mode: str) -> None:
        self._set_active_mode_btn(mode)

    def _export(self) -> None:
        if self._canvas_dirty:
            polys = self._canvas.get_active() + self._canvas.get_selected()
            if not polys:
                QMessageBox.critical(self, "Error", "Canvas is empty.")
                return
        else:
            coords = self._build_coords()
            if not coords:
                QMessageBox.critical(self, "Error", "Invalid shape parameters.")
                return
            polys = [coords]

        shape_name = self._shape_combo.currentText().lower().replace(" ", "_")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save shape as DXF",
            str(Path(self._settings.get("shape_output_dir", "")) / f"{shape_name}.dxf"),
            "DXF files (*.dxf);;All files (*)",
        )
        if not out_path:
            return

        try:
            write_polylines_dxf(polys, out_path, close=True)
            self._shape_status.setText(f"Saved → {Path(out_path).name}")
            self._shape_status.setStyleSheet("color: #3fb950;")
            self._last_out_path = out_path
            self._reveal_btn.setEnabled(True)
        except Exception as exc:
            self._shape_status.setText(f"Error: {exc}")
            self._shape_status.setStyleSheet("color: #f85149;")

    def _reveal_in_finder(self) -> None:
        if self._last_out_path:
            subprocess.run(["open", "-R", self._last_out_path])
