"""Pattern Generator tab."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aa_laser.constants import _DIM, _PATTERNS, _SEL
from aa_laser.core.dxf_io import (
    load_dxf_polylines,
    polylines_to_outline,
    write_polylines_dxf,
)
from aa_laser.core.generators import (
    gen_brick,
    gen_concentric_rings,
    gen_custom_tile,
    gen_diagonal_lines,
    gen_diamond_checkering,
    gen_fish_scale,
    gen_gradient_honeycomb,
    gen_honeycomb,
    gen_image_halftone,
    gen_square_grid,
    gen_stipple_dots,
    gen_sunburst,
    gen_triangle_grid,
    gen_voronoi,
    gen_wave_fill,
)
from aa_laser.settings import save_settings
from aa_laser.ui.canvas import DxfCanvas
from aa_laser.ui.helpers import _section_label


def _param_entry(
    grid: QGridLayout, row: int, label: str, default: str, width: int = 80
) -> QLineEdit:
    grid.addWidget(QLabel(label), row, 0)
    e = QLineEdit(default)
    e.setFixedWidth(width)
    grid.addWidget(e, row, 1)
    return e


class PatternTab(QWidget):
    _gen_done = Signal(object)  # (count, name, polys)
    _gen_error = Signal(str)
    _preview_done = Signal(object)  # (display_polys, count)
    _preview_error = Signal(str)

    def __init__(self, parent: QWidget | None = None, settings: dict | None = None):
        super().__init__(parent)
        self._settings: dict = settings or {}

        # Runtime state
        self._orig_polys: list[list[tuple[float, float]]] = []
        self._edit_polys: list[list[tuple[float, float]]] = []
        self._orig_w: float = 0.0
        self._orig_h: float = 0.0
        self._ar_locked: bool = True
        self._updating_dims: bool = False
        self._preview_running: bool = False
        self._last_out_path: str | None = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._start_preview_thread)

        self._gen_done.connect(self._handle_gen_done)
        self._gen_error.connect(self._handle_gen_error)
        self._preview_done.connect(self._handle_preview_done)
        self._preview_error.connect(self._handle_preview_error)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # Left panel (scrollable)
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
        # ── DXF file ──────────────────────────────────────────────────────────
        _section_label(layout, "Outline DXF")
        file_row = QHBoxLayout()
        self._dxf_edit = QLineEdit()
        self._dxf_edit.setPlaceholderText("Select .dxf…")
        file_row.addWidget(self._dxf_edit, stretch=1)
        self._recent_btn = QPushButton("Recent ▾")
        self._recent_btn.setFixedWidth(76)
        self._recent_btn.clicked.connect(self._show_recent_menu)
        file_row.addWidget(self._recent_btn)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse_dxf)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        reload_btn = QPushButton("↺  Reload")
        reload_btn.setMinimumHeight(28)
        reload_btn.clicked.connect(self._reload_dxf)
        layout.addWidget(reload_btn)

        # ── Scale ─────────────────────────────────────────────────────────────
        _section_label(layout, "Scale")

        orig_row = QHBoxLayout()
        orig_row.addWidget(QLabel("Original:"))
        self._orig_dims_label = QLabel("—")
        self._orig_dims_label.setStyleSheet(f"color: {_DIM};")
        orig_row.addWidget(self._orig_dims_label)
        orig_row.addStretch()
        layout.addLayout(orig_row)

        dims_g = QGridLayout()
        dims_g.addWidget(QLabel("Width (mm)"), 0, 0)
        self._scale_w = QLineEdit()
        self._scale_w.setFixedWidth(80)
        self._scale_w.setPlaceholderText("auto")
        self._scale_w.textChanged.connect(self._on_scale_w_changed)
        self._scale_w.textChanged.connect(self._schedule_preview)
        dims_g.addWidget(self._scale_w, 0, 1)
        dims_g.addWidget(QLabel("Height (mm)"), 1, 0)
        self._scale_h = QLineEdit()
        self._scale_h.setFixedWidth(80)
        self._scale_h.setPlaceholderText("auto")
        self._scale_h.textChanged.connect(self._on_scale_h_changed)
        self._scale_h.textChanged.connect(self._schedule_preview)
        dims_g.addWidget(self._scale_h, 1, 1)
        layout.addLayout(dims_g)

        self._ar_cb = QCheckBox("Lock aspect ratio")
        self._ar_cb.setChecked(True)
        self._ar_cb.stateChanged.connect(self._on_ar_toggle)
        layout.addWidget(self._ar_cb)

        # ── Outline editor ────────────────────────────────────────────────────
        _section_label(layout, "Outline Editor")

        self._sel_label = QLabel("0 selected")
        self._sel_label.setStyleSheet(f"color: {_DIM};")
        layout.addWidget(self._sel_label)

        btn_row = QHBoxLayout()
        for label, slot in [
            ("All", lambda: self._canvas.select_all()),
            ("None", lambda: self._canvas.deselect_all()),
            ("Fit", lambda: self._canvas.fit()),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        del_btn = QPushButton("Delete Selected  [Del]")
        del_btn.setMinimumHeight(30)
        del_btn.setStyleSheet(
            "background: transparent;border: 1px solid #f85149;color: #f85149;"
        )
        del_btn.clicked.connect(self._delete_selected)
        layout.addWidget(del_btn)

        undo_btn = QPushButton("↩  Undo Delete")
        undo_btn.setMinimumHeight(28)
        undo_btn.clicked.connect(self._undo_delete)
        layout.addWidget(undo_btn)

        # ── Pattern ───────────────────────────────────────────────────────────
        _section_label(layout, "Pattern")
        self._pattern_combo = QComboBox()
        self._pattern_combo.addItems(_PATTERNS)
        self._pattern_combo.currentTextChanged.connect(self._switch_pattern)
        layout.addWidget(self._pattern_combo)

        # Pattern param panels (stacked manually — show/hide)
        self._honeycomb_w = self._make_honeycomb_params()
        self._gradient_w = self._make_gradient_params()
        self._checkering_w = self._make_checkering_params()
        self._fishscale_w = self._make_fishscale_params()
        self._stipple_w = self._make_stipple_params()
        self._brick_w = self._make_brick_params()
        self._diagonal_w = self._make_diagonal_lines_params()
        self._square_grid_w = self._make_square_grid_params()
        self._concentric_w = self._make_concentric_rings_params()
        self._wave_w = self._make_wave_fill_params()
        self._sunburst_w = self._make_sunburst_params()
        self._voronoi_w = self._make_voronoi_params()
        self._triangle_w = self._make_triangle_grid_params()
        self._custom_tile_w = self._make_custom_tile_params()
        self._halftone_w = self._make_halftone_params()

        self._pattern_widgets = [
            self._honeycomb_w,
            self._gradient_w,
            self._checkering_w,
            self._fishscale_w,
            self._stipple_w,
            self._brick_w,
            self._diagonal_w,
            self._square_grid_w,
            self._concentric_w,
            self._wave_w,
            self._sunburst_w,
            self._voronoi_w,
            self._triangle_w,
            self._custom_tile_w,
            self._halftone_w,
        ]
        for w in self._pattern_widgets:
            layout.addWidget(w)
            w.hide()

        # ── Generate ──────────────────────────────────────────────────────────
        _section_label(layout, "Generate")

        self._include_border_cb = QCheckBox("Include border on separate layer")
        self._include_border_cb.setToolTip(
            "Writes the outline on a 'BORDER' DXF layer so your laser\n"
            "program can treat it separately from the pattern fill."
        )
        layout.addWidget(self._include_border_cb)

        self._gen_btn = QPushButton("Generate DXF")
        self._gen_btn.setMinimumHeight(38)
        self._gen_btn.setProperty("role", "primary")
        self._gen_btn.clicked.connect(self._generate)
        layout.addWidget(self._gen_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {_DIM};")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._reveal_btn = QPushButton("Show in Finder")
        self._reveal_btn.setMinimumHeight(26)
        self._reveal_btn.setEnabled(False)
        self._reveal_btn.clicked.connect(self._reveal_in_finder)
        layout.addWidget(self._reveal_btn)

        layout.addStretch()

    # ── Pattern param builders ────────────────────────────────────────────────

    def _make_honeycomb_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._hex_r = _param_entry(g, 0, "Hex size (mm)", "1.75")
        self._hex_gap = _param_entry(g, 1, "Gap (mm)", "0.5")
        self._hex_r.textChanged.connect(self._schedule_preview)
        self._hex_gap.textChanged.connect(self._schedule_preview)
        return w

    def _make_gradient_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._grad_r_min = _param_entry(g, 0, "Min size (mm)", "0.8")
        self._grad_r_max = _param_entry(g, 1, "Max size (mm)", "2.5")
        self._grad_gap = _param_entry(g, 2, "Gap (mm)", "0.5")
        self._grad_angle = _param_entry(g, 3, "Direction (°)", "0")
        for e in (self._grad_r_min, self._grad_r_max, self._grad_gap, self._grad_angle):
            e.textChanged.connect(self._schedule_preview)
        hint = QLabel("0° = left→right  ·90° = vertical")
        hint.setStyleSheet(f"color: {_DIM}; font-size: 9px;")
        g.addWidget(hint, 4, 0, 1, 2)
        return w

    def _make_checkering_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._check_cell = _param_entry(g, 0, "Cell size (mm)", "2.0")
        self._check_gap = _param_entry(g, 1, "Gap (mm)", "0.15")
        self._check_cell.textChanged.connect(self._schedule_preview)
        self._check_gap.textChanged.connect(self._schedule_preview)
        return w

    def _make_voronoi_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._vor_cells = _param_entry(g, 0, "Cell count", "60")
        self._vor_gap = _param_entry(g, 1, "Gap (mm)", "0.15")
        self._vor_seed = _param_entry(g, 2, "Seed", "42")
        self._vor_cells.textChanged.connect(self._schedule_preview)
        self._vor_gap.textChanged.connect(self._schedule_preview)
        self._vor_seed.textChanged.connect(self._schedule_preview)
        return w

    def _make_triangle_grid_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._tri_size = _param_entry(g, 0, "Side length (mm)", "3.0")
        self._tri_gap = _param_entry(g, 1, "Gap (mm)", "0.15")
        self._tri_size.textChanged.connect(self._schedule_preview)
        self._tri_gap.textChanged.connect(self._schedule_preview)
        return w

    def _make_fishscale_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._fish_w = _param_entry(g, 0, "Scale width (mm)", "3.0")
        self._fish_h = _param_entry(g, 1, "Scale height (mm)", "2.0")
        self._fish_w.textChanged.connect(self._schedule_preview)
        self._fish_h.textChanged.connect(self._schedule_preview)
        return w

    def _make_stipple_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._stip_r = _param_entry(g, 0, "Dot radius (mm)", "0.4")
        self._stip_spacing = _param_entry(g, 1, "Spacing (mm)", "1.2")
        self._stip_r.textChanged.connect(self._schedule_preview)
        self._stip_spacing.textChanged.connect(self._schedule_preview)
        return w

    def _make_brick_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._brick_w_e = _param_entry(g, 0, "Brick width (mm)", "4.0")
        self._brick_h_e = _param_entry(g, 1, "Brick height (mm)", "2.0")
        self._brick_gap = _param_entry(g, 2, "Gap (mm)", "0.5")
        self._brick_w_e.textChanged.connect(self._schedule_preview)
        self._brick_h_e.textChanged.connect(self._schedule_preview)
        self._brick_gap.textChanged.connect(self._schedule_preview)
        return w

    def _make_diagonal_lines_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._diag_spacing = _param_entry(g, 0, "Line spacing (mm)", "1.0")
        self._diag_angle = _param_entry(g, 1, "Angle (°)", "45")
        self._diag_spacing.textChanged.connect(self._schedule_preview)
        self._diag_angle.textChanged.connect(self._schedule_preview)
        return w

    def _make_square_grid_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._sq_spacing = _param_entry(g, 0, "Grid spacing (mm)", "1.0")
        self._sq_spacing.textChanged.connect(self._schedule_preview)
        return w

    def _make_concentric_rings_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._conc_spacing = _param_entry(g, 0, "Ring spacing (mm)", "1.5")
        self._conc_spacing.textChanged.connect(self._schedule_preview)
        return w

    def _make_wave_fill_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._wave_spacing = _param_entry(g, 0, "Row spacing (mm)", "1.5")
        self._wave_amplitude = _param_entry(g, 1, "Amplitude (mm)", "0.5")
        self._wave_wavelength = _param_entry(g, 2, "Wavelength (mm)", "3.0")
        self._wave_spacing.textChanged.connect(self._schedule_preview)
        self._wave_amplitude.textChanged.connect(self._schedule_preview)
        self._wave_wavelength.textChanged.connect(self._schedule_preview)
        return w

    def _make_sunburst_params(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        self._sunburst_spacing = _param_entry(g, 0, "Spoke spacing (°)", "5.0")
        self._sunburst_spacing.textChanged.connect(self._schedule_preview)
        hint = QLabel("5° → 36 spokes  ·  10° → 18 spokes")
        hint.setStyleSheet(f"color: {_DIM}; font-size: 9px;")
        g.addWidget(hint, 1, 0, 1, 2)
        return w

    def _make_custom_tile_params(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        pick_row = QHBoxLayout()
        self._tile_path_edit = QLineEdit()
        self._tile_path_edit.setPlaceholderText("Select tile DXF…")
        pick_row.addWidget(self._tile_path_edit, stretch=1)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(64)
        browse_btn.clicked.connect(self._browse_tile_dxf)
        pick_row.addWidget(browse_btn)
        vl.addLayout(pick_row)
        g = QGridLayout()
        self._tile_gap = _param_entry(g, 0, "Gap (mm)", "0.5")
        self._tile_angle = _param_entry(g, 1, "Tile rotation (°)", "0")
        self._tile_gap.textChanged.connect(self._schedule_preview)
        self._tile_angle.textChanged.connect(self._schedule_preview)
        vl.addLayout(g)
        hint = QLabel("Each tile instance is rotated")
        hint.setStyleSheet(f"color: {_DIM}; font-size: 9px;")
        vl.addWidget(hint)
        return w

    def _make_halftone_params(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        pick_row = QHBoxLayout()
        self._htone_img_edit = QLineEdit()
        self._htone_img_edit.setPlaceholderText("Select image (jpg/png)…")
        pick_row.addWidget(self._htone_img_edit, stretch=1)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(64)
        browse_btn.clicked.connect(self._browse_halftone_image)
        pick_row.addWidget(browse_btn)
        vl.addLayout(pick_row)
        g = QGridLayout()
        self._htone_r_min = _param_entry(g, 0, "Cell min (mm)", "0.3")
        self._htone_r_max = _param_entry(g, 1, "Cell max (mm)", "1.8")
        self._htone_spacing = _param_entry(g, 2, "Grid spacing (mm)", "2.2")
        self._htone_r_max.textChanged.connect(self._schedule_preview)
        self._htone_spacing.textChanged.connect(self._schedule_preview)
        vl.addLayout(g)
        self._htone_invert = QCheckBox("Invert  (dark → small cells)")
        self._htone_invert.stateChanged.connect(self._schedule_preview)
        vl.addWidget(self._htone_invert)
        return w

    def _switch_pattern(self, value: str) -> None:
        mapping = {
            "Honeycomb": self._honeycomb_w,
            "Gradient Honeycomb": self._gradient_w,
            "Diamond Checkering": self._checkering_w,
            "Fish Scale": self._fishscale_w,
            "Stipple Dots": self._stipple_w,
            "Brick": self._brick_w,
            "Diagonal Lines": self._diagonal_w,
            "Square Grid": self._square_grid_w,
            "Concentric Rings": self._concentric_w,
            "Wave Fill": self._wave_w,
            "Sunburst": self._sunburst_w,
            "Voronoi": self._voronoi_w,
            "Triangle Grid": self._triangle_w,
            "Custom Tile": self._custom_tile_w,
            "Image Halftone": self._halftone_w,
        }
        for w in self._pattern_widgets:
            w.hide()
        target = mapping.get(value)
        if target:
            target.show()
            self._schedule_preview()

    # ── Dimension callbacks ───────────────────────────────────────────────────

    def _on_scale_w_changed(self, *_) -> None:
        if self._updating_dims or not self._ar_cb.isChecked() or self._orig_w <= 0:
            return
        try:
            w = float(self._scale_w.text())
            h = w * self._orig_h / self._orig_w
            self._updating_dims = True
            self._scale_h.setText(f"{h:.3f}")
        except ValueError:
            pass
        finally:
            self._updating_dims = False

    def _on_scale_h_changed(self, *_) -> None:
        if self._updating_dims or not self._ar_cb.isChecked() or self._orig_h <= 0:
            return
        try:
            h = float(self._scale_h.text())
            w = h * self._orig_w / self._orig_h
            self._updating_dims = True
            self._scale_w.setText(f"{w:.3f}")
        except ValueError:
            pass
        finally:
            self._updating_dims = False

    def _on_ar_toggle(self, state: int) -> None:
        self._ar_locked = bool(state)

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self, layout: QVBoxLayout) -> None:
        ctrl_row = QHBoxLayout()
        back_btn = QPushButton("↺ Reset preview")
        back_btn.setFixedHeight(28)
        back_btn.clicked.connect(self._reset_preview)
        ctrl_row.addWidget(back_btn)

        # Mode buttons
        self._mode_btns: dict[str, QPushButton] = {}
        for mode in ("Select", "Draw", "Edit"):
            b = QPushButton(mode)
            b.setFixedHeight(28)
            b.setProperty("active", mode == "Select")
            b.clicked.connect(lambda checked, m=mode: self._on_toolbar_mode(m))
            ctrl_row.addWidget(b)
            self._mode_btns[mode] = b

        self._preview_status = QLabel("Load a DXF and select a pattern")
        self._preview_status.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        self._preview_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        ctrl_row.addWidget(self._preview_status, stretch=1)
        layout.addLayout(ctrl_row)

        # Tabbed canvas (Edit / Preview)
        self._canvas_tabs = QTabWidget()
        layout.addWidget(self._canvas_tabs, stretch=1)

        edit_page = QWidget()
        edit_lay = QVBoxLayout(edit_page)
        edit_lay.setContentsMargins(0, 0, 0, 0)
        self._canvas = DxfCanvas(
            selectable=True,
            on_change=self._on_sel_change,
            on_mode_change=self._on_canvas_mode_change,
        )
        edit_lay.addWidget(self._canvas)
        self._canvas_tabs.addTab(edit_page, "Edit")

        preview_page = QWidget()
        preview_lay = QVBoxLayout(preview_page)
        preview_lay.setContentsMargins(0, 0, 0, 0)
        self._preview_canvas = DxfCanvas(selectable=False)
        preview_lay.addWidget(self._preview_canvas)
        self._canvas_tabs.addTab(preview_page, "Preview")

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_sel_change(self, count: int) -> None:
        self._sel_label.setText(f"{count} selected" if count else "0 selected")
        self._sel_label.setStyleSheet(f"color: {_SEL};" if count else f"color: {_DIM};")
        # When polys are selected, use them as the clip outline; otherwise use all.
        if count:
            self._edit_polys = self._canvas.get_selected()
        else:
            self._edit_polys = self._canvas.get_active()
        self._schedule_preview()

    def _browse_dxf(self) -> None:
        idir = self._settings.get("outline_dxf_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select outline DXF",
            idir,
            "DXF files (*.dxf *.Dxf *.DXF);;All files (*)",
        )
        if path:
            self._dxf_edit.setText(path)
            self._load_dxf(path)

    def _reload_dxf(self) -> None:
        path = self._dxf_edit.text().strip()
        if path:
            self._load_dxf(path)

    def _load_dxf(self, path: str) -> None:
        try:
            polys = load_dxf_polylines(path)
            self._orig_polys = polys
            self._edit_polys = list(polys)
            self._canvas.load(polys)

            all_pts = [pt for p in polys for pt in p]
            if all_pts:
                xs, ys = zip(*all_pts)
                self._orig_w = max(xs) - min(xs)
                self._orig_h = max(ys) - min(ys)
                self._orig_dims_label.setText(
                    f"{self._orig_w:.2f} × {self._orig_h:.2f} mm"
                )
                self._scale_w.blockSignals(True)
                self._scale_h.blockSignals(True)
                self._scale_w.setText(f"{self._orig_w:.3f}")
                self._scale_h.setText(f"{self._orig_h:.3f}")
                self._scale_w.blockSignals(False)
                self._scale_h.blockSignals(False)
            else:
                self._orig_w = self._orig_h = 0.0
                self._orig_dims_label.setText("—")

            self._set_status(f"Loaded {len(polys)} polylines from {Path(path).name}")
            recent = self._settings.get("recent_dxf", [])
            if path in recent:
                recent.remove(path)
            recent.insert(0, path)
            self._settings["recent_dxf"] = recent[:8]
            save_settings(self._settings)
            self._schedule_preview()
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))

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

    def _reveal_in_finder(self) -> None:
        if self._last_out_path:
            subprocess.run(["open", "-R", self._last_out_path])

    def _show_recent_menu(self) -> None:
        recent = [r for r in self._settings.get("recent_dxf", []) if Path(r).exists()]
        if not recent:
            QMessageBox.information(self, "Recent Files", "No recent DXF files.")
            return
        menu = QMenu(self)
        for path in recent:
            lbl = Path(path).name + f"  ‹{Path(path).parent.name}›"
            menu.addAction(lbl, lambda p=path: self._quick_load(p))
        menu.addSeparator()
        menu.addAction("Clear history", self._clear_recent)
        menu.popup(self._recent_btn.mapToGlobal(QPoint(0, self._recent_btn.height())))

    def _quick_load(self, path: str) -> None:
        self._dxf_edit.setText(path)
        self._load_dxf(path)

    def _clear_recent(self) -> None:
        self._settings["recent_dxf"] = []
        save_settings(self._settings)

    def _browse_tile_dxf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select tile DXF",
            "",
            "DXF files (*.dxf *.Dxf *.DXF);;All files (*)",
        )
        if path:
            self._tile_path_edit.setText(path)
            self._schedule_preview()

    def _browse_halftone_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image for halftone",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)",
        )
        if path:
            self._htone_img_edit.setText(path)
            self._schedule_preview()

    def _set_status(self, text: str, color: str = _DIM) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color};")

    def _generate(self) -> None:
        if not self._edit_polys:
            QMessageBox.critical(self, "Error", "No polylines available for outline.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save pattern DXF",
            str(Path(self._settings.get("pattern_output_dir", "")) / "pattern.dxf"),
            "DXF files (*.dxf);;All files (*)",
        )
        if not out_path:
            return

        # Read widget values on the GUI thread (thread-safe)
        pattern = self._pattern_combo.currentText()
        include_border = self._include_border_cb.isChecked()
        try:
            scale = self._collect_scale()
            params = self._collect_pattern_params(pattern)
        except ValueError:
            return
        polys_snap = list(self._edit_polys)
        border_polys = self._apply_scale(polys_snap, *scale) if include_border else None

        self._gen_btn.setEnabled(False)
        self._progress.setRange(0, 0)  # indeterminate
        self._set_status("Generating…")

        threading.Thread(
            target=self._run_generate,
            args=(polys_snap, out_path, pattern, params, scale, border_polys),
            daemon=True,
        ).start()

    def _run_generate(
        self,
        active: list[list[tuple[float, float]]],
        out_path: str,
        pattern: str,
        params: dict,
        scale: tuple[float, float],
        border_polys: list[list[tuple[float, float]]] | None,
    ) -> None:
        try:
            scaled = self._apply_scale(active, *scale)
            outline = polylines_to_outline(scaled)
            polys = self._gen_pattern(outline, pattern, params)
            close = pattern not in (
                "Fish Scale",
                "Diagonal Lines", "Square Grid",
                "Concentric Rings", "Wave Fill", "Sunburst",
            )
            write_polylines_dxf(polys, out_path, close=close, border_polys=border_polys)

            count = len(polys)
            name = Path(out_path).name
            self._gen_done.emit((count, name, out_path, polys))

        except Exception as exc:
            self._gen_error.emit(str(exc))

    def _handle_gen_done(self, payload: tuple) -> None:
        count, name, out_path, polys = payload
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._gen_btn.setEnabled(True)
        self._set_status(f"Done — {count} shapes → {name}", "#3fb950")
        self._last_out_path = out_path
        self._reveal_btn.setEnabled(True)
        self._preview_canvas.load(polys)
        self._preview_status.setText(f"{count} shapes generated")
        self._preview_status.setStyleSheet("color: #3fb950; font-size: 11px;")

    def _handle_gen_error(self, msg: str) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._gen_btn.setEnabled(True)
        self._set_status(f"Error: {msg}", "#f85149")

    # ── Live preview ─────────────────────────────────────────────────────────

    def _schedule_preview(self, *_) -> None:
        if self._pattern_combo.currentText() == "— None —":
            return
        if not self._edit_polys:
            return
        self._preview_timer.start(400)

    def _start_preview_thread(self) -> None:
        if self._preview_running or not self._edit_polys:
            return
        self._preview_running = True
        polys_snap = list(self._edit_polys)
        pattern = self._pattern_combo.currentText()
        include_border = self._include_border_cb.isChecked()
        try:
            scale = self._collect_scale()
            params = self._collect_pattern_params(pattern)
        except ValueError:
            self._preview_running = False
            return
        border_polys = self._apply_scale(polys_snap, *scale) if include_border else None
        self._preview_status.setText("Previewing…")
        self._preview_status.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        threading.Thread(
            target=self._compute_preview,
            args=(polys_snap, pattern, params, scale, border_polys),
            daemon=True,
        ).start()

    def _compute_preview(
        self,
        outline_polys,
        pattern: str,
        params: dict,
        scale: tuple[float, float],
        border_polys: list[list[tuple[float, float]]] | None,
    ) -> None:
        try:
            scaled = self._apply_scale(outline_polys, *scale)
            outline = polylines_to_outline(scaled)
            polys = self._gen_pattern(outline, pattern, params)
            if border_polys:
                display_polys = polys + border_polys
            else:
                display_polys = polys
            self._preview_done.emit((display_polys, len(polys)))
        except Exception as exc:
            self._preview_error.emit(str(exc))

    def _handle_preview_done(self, payload: tuple) -> None:
        display_polys, count = payload
        self._preview_running = False
        self._preview_canvas.reload(display_polys)
        self._preview_status.setText(f"{count} shapes — live preview")
        self._preview_status.setStyleSheet("color: #3fb950; font-size: 11px;")
        if self._pattern_combo.currentText() != "— None —":
            self._canvas_tabs.setCurrentIndex(1)

    def _handle_preview_error(self, msg: str) -> None:
        self._preview_running = False
        self._preview_status.setText(f"Preview error: {msg}")
        self._preview_status.setStyleSheet("color: #f85149; font-size: 11px;")

    # ── Param collection (GUI thread only) ───────────────────────────────────

    def _collect_scale(self) -> tuple[float, float]:
        sw = (
            float(self._scale_w.text())
            if self._scale_w.text().strip()
            else self._orig_w
        )
        sh = (
            float(self._scale_h.text())
            if self._scale_h.text().strip()
            else self._orig_h
        )
        return sw, sh

    def _collect_pattern_params(self, pattern: str) -> dict:
        if pattern == "Honeycomb":
            return {"r": float(self._hex_r.text()), "gap": float(self._hex_gap.text())}
        elif pattern == "Gradient Honeycomb":
            return {
                "r_min": float(self._grad_r_min.text()),
                "r_max": float(self._grad_r_max.text()),
                "gap": float(self._grad_gap.text()),
                "angle": float(self._grad_angle.text()),
            }
        elif pattern == "Diamond Checkering":
            return {
                "cell_size": float(self._check_cell.text()),
                "gap": float(self._check_gap.text()),
            }
        elif pattern == "Fish Scale":
            return {"sw": float(self._fish_w.text()), "sh": float(self._fish_h.text())}
        elif pattern == "Stipple Dots":
            return {
                "r": float(self._stip_r.text()),
                "spacing": float(self._stip_spacing.text()),
            }
        elif pattern == "Brick":
            return {
                "brick_w": float(self._brick_w_e.text()),
                "brick_h": float(self._brick_h_e.text()),
                "gap": float(self._brick_gap.text()),
            }
        elif pattern == "Diagonal Lines":
            return {
                "spacing": float(self._diag_spacing.text()),
                "angle": float(self._diag_angle.text()),
            }
        elif pattern == "Square Grid":
            return {"spacing": float(self._sq_spacing.text())}
        elif pattern == "Concentric Rings":
            return {"spacing": float(self._conc_spacing.text())}
        elif pattern == "Wave Fill":
            return {
                "spacing": float(self._wave_spacing.text()),
                "amplitude": float(self._wave_amplitude.text()),
                "wavelength": float(self._wave_wavelength.text()),
            }
        elif pattern == "Sunburst":
            return {
                "spacing_deg": float(self._sunburst_spacing.text()),
            }
        elif pattern == "Voronoi":
            return {
                "n_cells": int(float(self._vor_cells.text())),
                "gap": float(self._vor_gap.text()),
                "seed": int(float(self._vor_seed.text())),
            }
        elif pattern == "Triangle Grid":
            return {
                "size": float(self._tri_size.text()),
                "gap": float(self._tri_gap.text()),
            }
        elif pattern == "Custom Tile":
            tile_path = self._tile_path_edit.text().strip()
            if not tile_path:
                raise ValueError("No tile DXF selected.")
            return {
                "tile_path": tile_path,
                "gap": float(self._tile_gap.text()),
                "angle": float(self._tile_angle.text()),
            }
        else:  # Image Halftone
            img_path = self._htone_img_edit.text().strip()
            if not img_path:
                raise ValueError("No image selected.")
            return {
                "img_path": img_path,
                "r_min": float(self._htone_r_min.text()),
                "r_max": float(self._htone_r_max.text()),
                "spacing": float(self._htone_spacing.text()),
                "invert": self._htone_invert.isChecked(),
            }

    # ── Pure helpers (safe from any thread) ──────────────────────────────────

    def _apply_scale(
        self,
        polys: list[list[tuple[float, float]]],
        sw: float,
        sh: float,
    ) -> list[list[tuple[float, float]]]:
        if self._orig_w <= 0 or self._orig_h <= 0:
            return polys
        if sw <= 0 or sh <= 0:
            return polys
        sx = sw / self._orig_w
        sy = sh / self._orig_h
        if abs(sx - 1.0) < 1e-9 and abs(sy - 1.0) < 1e-9:
            return polys
        all_pts = [pt for p in polys for pt in p]
        if not all_pts:
            return polys
        xs, ys = zip(*all_pts)
        ox, oy = min(xs), min(ys)
        return [
            [(ox + (x - ox) * sx, oy + (y - oy) * sy) for x, y in poly]
            for poly in polys
        ]

    @staticmethod
    def _gen_pattern(
        outline,
        pattern: str,
        params: dict,
    ) -> list[list[tuple[float, float]]]:
        if pattern == "Honeycomb":
            return gen_honeycomb(outline, params["r"], params["gap"])
        elif pattern == "Gradient Honeycomb":
            return gen_gradient_honeycomb(
                outline,
                params["r_min"],
                params["r_max"],
                params["gap"],
                params["angle"],
            )
        elif pattern == "Diamond Checkering":
            return gen_diamond_checkering(outline, params["cell_size"], params["gap"])
        elif pattern == "Fish Scale":
            return gen_fish_scale(outline, params["sw"], params["sh"])
        elif pattern == "Stipple Dots":
            return gen_stipple_dots(outline, params["r"], params["spacing"])
        elif pattern == "Brick":
            return gen_brick(outline, params["brick_w"], params["brick_h"], params["gap"])
        elif pattern == "Diagonal Lines":
            return gen_diagonal_lines(outline, params["spacing"], params["angle"])
        elif pattern == "Square Grid":
            return gen_square_grid(outline, params["spacing"])
        elif pattern == "Concentric Rings":
            return gen_concentric_rings(outline, params["spacing"])
        elif pattern == "Wave Fill":
            return gen_wave_fill(
                outline, params["spacing"], params["amplitude"], params["wavelength"]
            )
        elif pattern == "Sunburst":
            return gen_sunburst(outline, params["spacing_deg"])
        elif pattern == "Voronoi":
            return gen_voronoi(outline, params["n_cells"], params["gap"], params["seed"])
        elif pattern == "Triangle Grid":
            return gen_triangle_grid(outline, params["size"], params["gap"])
        elif pattern == "Custom Tile":
            tile_polys = load_dxf_polylines(params["tile_path"])
            return gen_custom_tile(outline, tile_polys, params["gap"], params["angle"])
        else:  # Image Halftone
            return gen_image_halftone(
                outline,
                params["img_path"],
                params["r_min"],
                params["r_max"],
                params["spacing"],
                params["invert"],
            )

    def _reset_preview(self) -> None:
        if self._edit_polys:
            self._preview_canvas.reload(self._edit_polys)
            self._preview_status.setText("Preview reset — adjust params to regenerate")
            self._preview_status.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
            self._schedule_preview()
