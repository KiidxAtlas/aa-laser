"""Utilities tab — FVI → DXF | DXF Fixer | DXF → SVG."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aa_laser.core.dxf_fix import fix_dxf
from aa_laser.core.dxf_io import load_dxf_polylines
from aa_laser.core.dxf_svg import dxf_to_svg
from aa_laser.core.fvi import convert_fvi_to_dxf
from aa_laser.ui.canvas import DxfCanvas
from aa_laser.ui.helpers import _section_label


class UtilitiesTab(QWidget):
    """Utilities — FVI→DXF conversion, DXF fixer, and DXF→SVG export."""

    def __init__(self, parent: QWidget | None = None, settings: dict | None = None):
        super().__init__(parent)
        self._settings: dict = settings or {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left sidebar (sub-tabs + small preview) ───────────────────────────
        left_w = QWidget()
        left_w.setFixedWidth(310)
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)

        self._sub_tabs = QTabWidget()
        self._sub_tabs.setTabPosition(QTabWidget.TabPosition.North)

        self._fvi_subtab = _FviSubTab(settings=self._settings)
        self._fix_subtab = _FixerSubTab(settings=self._settings)
        self._svg_subtab = _SvgSubTab(settings=self._settings)
        self._sub_tabs.addTab(self._fvi_subtab, "FVI → DXF")
        self._sub_tabs.addTab(self._fix_subtab, "DXF Fixer")
        self._sub_tabs.addTab(self._svg_subtab, "DXF → SVG")
        left.addWidget(self._sub_tabs, stretch=1)

        # Small DXF preview at bottom of sidebar
        preview_section = QWidget()
        preview_section.setFixedHeight(180)
        ps_layout = QVBoxLayout(preview_section)
        ps_layout.setContentsMargins(6, 4, 6, 6)
        ps_layout.setSpacing(2)
        preview_lbl = QLabel("Preview")
        preview_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        ps_layout.addWidget(preview_lbl)
        self._preview_canvas = DxfCanvas(selectable=False)
        self._preview_canvas.setFixedHeight(160)
        ps_layout.addWidget(self._preview_canvas)
        left.addWidget(preview_section)

        root.addWidget(left_w)

        # ── Right: shared log ─────────────────────────────────────────────────
        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(6, 8, 8, 8)
        right.setSpacing(4)
        log_lbl = QLabel("Log")
        log_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        right.addWidget(log_lbl)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet("font-family: Menlo, Courier; font-size: 11px;")
        right.addWidget(self._log, stretch=1)
        root.addWidget(right_w, stretch=1)

        # Connect sub-tab signals to shared log and preview
        for tab in (self._fvi_subtab, self._fix_subtab, self._svg_subtab):
            tab.log_line.connect(self._log.appendPlainText)
            tab.preview_path.connect(self._load_preview)

    def _load_preview(self, dxf_path: str) -> None:
        try:
            polys = load_dxf_polylines(dxf_path)
            if polys:
                self._preview_canvas.load(polys)
        except Exception:
            pass


# ─── FVI → DXF sub-tab ───────────────────────────────────────────────────────


class _FviSubTab(QWidget):
    log_line = Signal(str)  # → parent shared log
    preview_path = Signal(str)  # → parent preview canvas
    _btn_state = Signal(bool)  # → self._btn.setEnabled
    _out_dir_sig = Signal(str)  # → self._set_output_dir

    def __init__(
        self,
        parent: QWidget | None = None,
        settings: dict | None = None,
        preview_signal=None,  # legacy arg, ignored
    ):
        super().__init__(parent)
        self._settings: dict = settings or {}
        self._last_out_dir: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self._build(layout)

    def _build(self, layout: QVBoxLayout) -> None:
        _section_label(layout, "Mode")
        mode_row = QHBoxLayout()
        self._mode_single = QPushButton("Single file")
        self._mode_batch = QPushButton("Folder (batch)")
        self._mode_single.setProperty("active", True)
        self._mode_batch.setProperty("active", False)
        self._mode_single.clicked.connect(lambda: self._set_mode("single"))
        self._mode_batch.clicked.connect(lambda: self._set_mode("batch"))
        mode_row.addWidget(self._mode_single)
        mode_row.addWidget(self._mode_batch)
        layout.addLayout(mode_row)

        _section_label(layout, "Source")
        src_row = QHBoxLayout()
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("Select a .fvi file or folder…")
        src_btn = QPushButton("Browse")
        src_btn.setFixedWidth(70)
        src_btn.clicked.connect(self._browse_src)
        src_row.addWidget(self._src_edit, stretch=1)
        src_row.addWidget(src_btn)
        layout.addLayout(src_row)

        _section_label(layout, "Output folder")
        out_row = QHBoxLayout()
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("Optional (blank = same as source)…")
        out_btn = QPushButton("Browse")
        out_btn.setFixedWidth(70)
        out_btn.clicked.connect(self._browse_out)
        out_row.addWidget(self._out_edit, stretch=1)
        out_row.addWidget(out_btn)
        layout.addLayout(out_row)

        self._btn = QPushButton("Convert")
        self._btn.setMinimumHeight(38)
        self._btn.setProperty("role", "primary")
        self._btn.clicked.connect(self._run)
        layout.addWidget(self._btn)

        self._open_folder_btn = QPushButton("Open Output Folder")
        self._open_folder_btn.setMinimumHeight(28)
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._open_output_folder)
        layout.addWidget(self._open_folder_btn)

        layout.addStretch()

        # Wire internal signals (thread-safe)
        self._btn_state.connect(self._btn.setEnabled)
        self._out_dir_sig.connect(self._set_output_dir)

    def _set_mode(self, mode: str) -> None:
        for b, active in [
            (self._mode_single, mode == "single"),
            (self._mode_batch, mode == "batch"),
        ]:
            b.setProperty("active", active)
            b.style().unpolish(b)
            b.style().polish(b)

    def _is_batch(self) -> bool:
        return self._mode_batch.property("active") is True

    def _browse_src(self) -> None:
        idir = self._settings.get("fvi_source_dir", "")
        if not self._is_batch():
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select FVI file",
                idir,
                "FVI files (*.fvi *.Fvi *.FVI);;All files (*)",
            )
        else:
            path = QFileDialog.getExistingDirectory(
                self, "Select folder containing FVI files", idir
            )
        if path:
            self._src_edit.setText(path)

    def _browse_out(self) -> None:
        idir = self._settings.get("fvi_output_dir", "")
        path = QFileDialog.getExistingDirectory(self, "Select output folder", idir)
        if path:
            self._out_edit.setText(path)

    def _set_output_dir(self, d: str) -> None:
        self._last_out_dir = d
        self._open_folder_btn.setEnabled(True)

    def _open_output_folder(self) -> None:
        if self._last_out_dir:
            subprocess.run(["open", self._last_out_dir])

    def _run(self) -> None:
        src = self._src_edit.text().strip()
        if not src:
            QMessageBox.critical(
                self, "Error", "Please select a source file or folder."
            )
            return
        self._btn.setEnabled(False)
        out_dir = self._out_edit.text().strip() or None
        threading.Thread(target=self._convert, args=(src, out_dir), daemon=True).start()

    def _convert(self, src: str, out_dir: str | None) -> None:
        p = Path(src)
        if p.is_file():
            files = [p]
        else:
            raw = (
                list(p.rglob("*.fvi")) + list(p.rglob("*.Fvi")) + list(p.rglob("*.FVI"))
            )
            seen: set[str] = set()
            files = []
            for f in raw:
                k = str(f).lower()
                if k not in seen:
                    seen.add(k)
                    files.append(f)

        if not files:
            self.log_line.emit("No .fvi files found.")
            self._btn_state.emit(True)
            return

        self.log_line.emit(f"Found {len(files)} file(s)\n")
        ok = err = 0
        last_dxf: str | None = None
        for fvi in files:
            dest_dir = Path(out_dir) if out_dir else fvi.parent
            dest = dest_dir / fvi.with_suffix(".dxf").name
            try:
                convert_fvi_to_dxf(fvi, dest)
                self.log_line.emit(f"  ✓  {fvi.name}  →  {dest.name}")
                ok += 1
                last_dxf = str(dest)
            except Exception as exc:
                self.log_line.emit(f"  ✗  {fvi.name}: {exc}")
                err += 1

        self.log_line.emit(f"\nDone — {ok} converted, {err} error(s).")
        self._btn_state.emit(True)
        if files:
            final_dir = out_dir or str(files[0].parent)
            self._out_dir_sig.emit(final_dir)
        if last_dxf:
            self.preview_path.emit(last_dxf)


# ─── DXF Fixer sub-tab ───────────────────────────────────────────────────────


class _FixerSubTab(QWidget):
    log_line = Signal(str)
    preview_path = Signal(str)
    _btn_state = Signal(bool)
    _reveal_state = Signal(bool)
    _status_sig = Signal(str, str)  # text, color

    def __init__(
        self,
        parent: QWidget | None = None,
        settings: dict | None = None,
        preview_signal=None,  # legacy arg, ignored
    ):
        super().__init__(parent)
        self._settings: dict = settings or {}
        self._last_out: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self._build(root)

    def _build(self, layout: QVBoxLayout) -> None:
        _section_label(layout, "Input DXF")
        src_row = QHBoxLayout()
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("Select a .dxf file…")
        src_btn = QPushButton("Browse")
        src_btn.setFixedWidth(70)
        src_btn.clicked.connect(self._browse_src)
        src_row.addWidget(self._src_edit, stretch=1)
        src_row.addWidget(src_btn)
        layout.addLayout(src_row)

        _section_label(layout, "Output DXF")
        out_row = QHBoxLayout()
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("Leave blank to overwrite input…")
        out_btn = QPushButton("Browse")
        out_btn.setFixedWidth(70)
        out_btn.clicked.connect(self._browse_out)
        out_row.addWidget(self._out_edit, stretch=1)
        out_row.addWidget(out_btn)
        layout.addLayout(out_row)

        self._btn = QPushButton("Fix DXF")
        self._btn.setMinimumHeight(38)
        self._btn.setProperty("role", "primary")
        self._btn.clicked.connect(self._run)
        layout.addWidget(self._btn)

        self._reveal_btn = QPushButton("Show in Finder")
        self._reveal_btn.setMinimumHeight(26)
        self._reveal_btn.setEnabled(False)
        self._reveal_btn.clicked.connect(self._reveal)
        layout.addWidget(self._reveal_btn)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._btn_state.connect(self._btn.setEnabled)
        self._reveal_state.connect(self._reveal_btn.setEnabled)
        self._status_sig.connect(self._set_status)

    def _browse_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DXF file",
            "",
            "DXF files (*.dxf *.DXF);;All files (*)",
        )
        if path:
            self._src_edit.setText(path)

    def _browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save fixed DXF",
            "",
            "DXF files (*.dxf);;All files (*)",
        )
        if path:
            self._out_edit.setText(path)

    def _set_status(self, text: str, color: str = "#8b949e") -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color};")

    def _run(self) -> None:
        src = self._src_edit.text().strip()
        if not src:
            QMessageBox.critical(self, "Error", "Please select an input DXF file.")
            return
        out = self._out_edit.text().strip() or src
        self._btn.setEnabled(False)
        self._set_status("Fixing…")
        threading.Thread(target=self._fix, args=(src, out), daemon=True).start()

    def _fix(self, src: str, out: str) -> None:
        try:
            stats = fix_dxf(src, out)
            msg = (
                f"Done — {stats['polylines_in']} in → {stats['polylines_out']} out"
                f"  · closed {stats['closed']}"
                f"  · simplified {stats['simplified']}"
                f"  · discarded {stats['discarded']}"
            )
            self.log_line.emit(msg)
            self._btn_state.emit(True)
            self._reveal_state.emit(True)
            self._status_sig.emit("Done", "#3fb950")
            self._last_out = out
            self.preview_path.emit(out)
        except Exception as exc:
            self.log_line.emit(f"Error: {exc}")
            self._btn_state.emit(True)
            self._status_sig.emit(f"Error: {exc}", "#f85149")

    def _reveal(self) -> None:
        if self._last_out:
            subprocess.run(["open", "-R", self._last_out])


# ─── DXF → SVG sub-tab ───────────────────────────────────────────────────────


class _SvgSubTab(QWidget):
    log_line = Signal(str)
    preview_path = Signal(str)
    _btn_state = Signal(bool)
    _reveal_state = Signal(bool)
    _status_sig = Signal(str, str)  # text, color

    def __init__(
        self,
        parent: QWidget | None = None,
        settings: dict | None = None,
        preview_signal=None,  # legacy arg, ignored
    ):
        super().__init__(parent)
        self._settings: dict = settings or {}
        self._last_out: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self._build(root)

    def _build(self, layout: QVBoxLayout) -> None:
        _section_label(layout, "Input DXF")
        src_row = QHBoxLayout()
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("Select a .dxf file…")
        src_btn = QPushButton("Browse")
        src_btn.setFixedWidth(70)
        src_btn.clicked.connect(self._browse_src)
        src_row.addWidget(self._src_edit, stretch=1)
        src_row.addWidget(src_btn)
        layout.addLayout(src_row)

        _section_label(layout, "Output SVG")
        out_row = QHBoxLayout()
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("Leave blank to auto-name…")
        out_btn = QPushButton("Browse")
        out_btn.setFixedWidth(70)
        out_btn.clicked.connect(self._browse_out)
        out_row.addWidget(self._out_edit, stretch=1)
        out_row.addWidget(out_btn)
        layout.addLayout(out_row)

        self._btn = QPushButton("Convert to SVG")
        self._btn.setMinimumHeight(38)
        self._btn.setProperty("role", "primary")
        self._btn.clicked.connect(self._run)
        layout.addWidget(self._btn)

        self._reveal_btn = QPushButton("Show in Finder")
        self._reveal_btn.setMinimumHeight(26)
        self._reveal_btn.setEnabled(False)
        self._reveal_btn.clicked.connect(self._reveal)
        layout.addWidget(self._reveal_btn)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        layout.addStretch()

        self._btn_state.connect(self._btn.setEnabled)
        self._reveal_state.connect(self._reveal_btn.setEnabled)
        self._status_sig.connect(self._set_status)

    def _browse_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DXF file",
            "",
            "DXF files (*.dxf *.DXF);;All files (*)",
        )
        if path:
            self._src_edit.setText(path)
            if not self._out_edit.text().strip():
                self._out_edit.setText(str(Path(path).with_suffix(".svg")))

    def _browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save SVG",
            "",
            "SVG files (*.svg);;All files (*)",
        )
        if path:
            self._out_edit.setText(path)

    def _set_status(self, text: str, color: str = "#8b949e") -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color};")

    def _run(self) -> None:
        src = self._src_edit.text().strip()
        if not src:
            QMessageBox.critical(self, "Error", "Please select an input DXF file.")
            return
        out = self._out_edit.text().strip()
        if not out:
            out = str(Path(src).with_suffix(".svg"))
            self._out_edit.setText(out)
        self._btn.setEnabled(False)
        self._set_status("Converting…")
        threading.Thread(target=self._convert, args=(src, out), daemon=True).start()

    def _convert(self, src: str, out: str) -> None:
        try:
            stats = dxf_to_svg(src, out)
            msg = (
                f"Done — {stats['polylines']} polyline(s)"
                f"  · {stats['width_mm']:.1f} × {stats['height_mm']:.1f} mm"
            )
            self.log_line.emit(msg)
            self._btn_state.emit(True)
            self._reveal_state.emit(True)
            self._status_sig.emit("Done", "#3fb950")
            self._last_out = out
            self.preview_path.emit(src)
        except Exception as exc:
            self.log_line.emit(f"Error: {exc}")
            self._btn_state.emit(True)
            self._status_sig.emit(f"Error: {exc}", "#f85149")

    def _reveal(self) -> None:
        if self._last_out:
            subprocess.run(["open", "-R", self._last_out])


# Keep old name as alias for backward compatibility
FviTab = UtilitiesTab
