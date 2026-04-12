"""PolylineView — interactive pan/zoom QGraphicsView with polyline selection, measure, draw, and edit tools."""

from __future__ import annotations

import math

from PIL import Image as PILImage
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QLineEdit, QMenu, QWidget

from aa_laser.constants import _DIM, _DRAG_THRESH, _POLY, _SEL, Q_BG

# Edit-mode visual constants
_HANDLE = QColor("#4a9eff")  # vertex handle — matches poly accent
_HANDLE_HOVER = QColor("#00c8aa")  # hover — teal
_HANDLE_ACTIVE = QColor("#f5a623")  # active drag — amber
_SNAP_CLOSE = QColor("#00c8aa")  # snap ring — teal
_DRAW_COLOR = QColor("#f5a623")  # draw mode in-progress — amber
_MEASURE_COLOR = QColor("#22d3ee")  # measure — cyan
_HANDLE_R = 4
_SNAP_DIST = 10
_VERT_HIT = 8
_EDGE_HIT = 6


def _pil_to_qpixmap(pil_img: PILImage.Image) -> QPixmap:
    """Convert a PIL Image to QPixmap."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class PolylineView(QGraphicsView):
    """
    Displays polyline lists with Select / Draw / Edit modes.

    Modes:
    - ``select`` — click polylines to select/deselect, Shift+drag rubber-band
    - ``draw``   — click to place vertices, finish with dbl-click/Enter/right-click
    - ``edit``   — drag vertices, double-click edge to insert, right-click vertex to delete

    Set ``selectable=False`` for a display-only preview (no mode switching).
    """

    selectionChanged = Signal(int)  # type: ignore[assignment]
    modeChanged = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        selectable: bool = True,
        on_change=None,
        on_mode_change=None,
        on_poly_change=None,
    ):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(Q_BG))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._selectable = selectable
        self._on_change = on_change
        self._on_mode_change = on_mode_change
        self._on_poly_change = on_poly_change
        if on_change:
            self.selectionChanged.connect(on_change)
        if on_mode_change:
            self.modeChanged.connect(on_mode_change)

        self._polys: list[list[tuple[float, float]]] = []
        self._sel: set[int] = set()

        self._scale = 1.0
        self._ox = 0.0
        self._oy = 0.0

        # LMB interaction state
        self._lmb_press: QPointF | None = None
        self._lmb_prev: QPointF | None = None
        self._lmb_target: int | None = None

        # MMB pan state
        self._mmb_prev: QPointF | None = None

        # Cursor world position
        self._cursor_wx: float | None = None
        self._cursor_wy: float | None = None

        # Rubber-band select
        self._shift_drag: bool = False
        self._band_start: QPointF | None = None

        # Undo stack
        self._undo_stack: list[list] = []

        # Fit scale for zoom-% display
        self._fit_scale: float = 1.0

        # Measure tool
        self._measure_mode: bool = False
        self._measure_anchor: tuple[float, float] | None = None
        self._measure_hover: tuple[float, float] | None = None
        self._measure_locked: bool = False
        self._measure_end: tuple[float, float] | None = None
        self._measure_snapped_a: bool = False
        self._measure_snapped_b: bool = False
        self._measure_edit: QLineEdit | None = None

        # Mode: "select" | "draw" | "edit"
        self._mode: str = "select"

        # Draw mode state
        self._draw_pts: list[tuple[float, float]] = []

        # Edit mode state
        self._edit_poly: int | None = None
        self._edit_vert: int | None = None
        self._edit_dragging: bool = False
        self._hover_vert: tuple[int, int] | None = None

        # Move state (select mode drag-to-move)
        self._move_dragging: bool = False
        self._move_origin: tuple[float, float] | None = None
        self._move_undo_pushed: bool = False

        # Clipboard
        self._clipboard: list[list[tuple[float, float]]] = []

        # Nudge undo debounce
        self._nudge_undo_pushed: bool = False

        # Image bounds reference rectangle
        self._img_bounds: tuple[float, float] | None = None

        # Background image overlay
        self._bg_pil: PILImage.Image | None = None
        self._bg_w_mm: float = 0.0
        self._bg_h_mm: float = 0.0
        self._bg_pixmap: QPixmap | None = None
        self._bg_cached_scale: float = 0.0

        # Measure button rect
        self._mbtn_rect: tuple[float, float, float, float] = (0, 0, 0, 0)

        # Draw mode snap (world-space snap point under cursor)
        self._draw_snap: tuple[float, float] | None = None
        # Measure pre-anchor hover snap point
        self._measure_hover_pre: tuple[float, float] | None = None

        self._needs_fit = True
        self.setMouseTracking(True)

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, polys: list[list[tuple[float, float]]]) -> None:
        self._polys = list(polys)
        self._sel.clear()
        self._needs_fit = True
        self._fit()
        self._notify()

    def reload(self, polys: list[list[tuple[float, float]]]) -> None:
        self._polys = list(polys)
        self._sel &= set(range(len(self._polys)))
        self._redraw()
        self._notify()

    def get_active(self) -> list[list[tuple[float, float]]]:
        return [p for i, p in enumerate(self._polys) if i not in self._sel]

    def get_selected(self) -> list[list[tuple[float, float]]]:
        return [p for i, p in enumerate(self._polys) if i in self._sel]

    def delete_selected(self) -> int:
        n = len(self._sel)
        if n:
            self._push_undo()
        self._polys = [p for i, p in enumerate(self._polys) if i not in self._sel]
        self._sel.clear()
        self._redraw()
        self._notify()
        return n

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._polys = self._undo_stack.pop()
        self._sel.clear()
        self._edit_poly = None
        self._edit_vert = None
        self._edit_dragging = False
        self._hover_vert = None
        self._redraw()
        self._notify()
        return True

    def undo_delete(self) -> bool:
        return self.undo()

    def invert_selection(self) -> None:
        self._sel = set(range(len(self._polys))) - self._sel
        self._redraw()
        self._notify()

    def select_all(self) -> None:
        self._sel = set(range(len(self._polys)))
        self._redraw()
        self._notify()

    def deselect_all(self) -> None:
        self._sel.clear()
        self._redraw()
        self._notify()

    def toggle_measure(self) -> None:
        self._measure_mode = not self._measure_mode
        self._measure_anchor = None
        self._measure_hover = None
        self._measure_locked = False
        self._measure_end = None
        self._measure_snapped_a = False
        self._measure_snapped_b = False
        self._dismiss_measure_edit()
        self._update_cursor()
        self._redraw()

    def set_image_bounds(self, w_mm: float, h_mm: float) -> None:
        self._img_bounds = (w_mm, h_mm)
        self._redraw()

    def set_background_image(
        self, pil_img: PILImage.Image, w_mm: float, h_mm: float
    ) -> None:
        self._bg_pil = pil_img
        self._bg_w_mm = w_mm
        self._bg_h_mm = h_mm
        self._bg_pixmap = None
        self._bg_cached_scale = 0.0
        self._redraw()

    def clear_background_image(self) -> None:
        self._bg_pil = None
        self._bg_pixmap = None
        self._redraw()

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        if self._mode == "draw":
            self._draw_pts.clear()
        elif self._mode == "edit":
            self._edit_poly = None
            self._edit_vert = None
            self._edit_dragging = False
            self._hover_vert = None
        self._mode = mode
        if mode in ("draw", "edit"):
            self._measure_mode = False
        self._update_cursor()
        self._redraw()
        self.modeChanged.emit(mode)

    def get_mode(self) -> str:
        return self._mode

    def toggle_draw_mode(self) -> None:
        self.set_mode("draw" if self._mode != "draw" else "select")

    def get_draw_mode(self) -> bool:
        return self._mode == "draw"

    def fit(self) -> None:
        self._fit()

    @property
    def poly_count(self) -> int:
        return len(self._polys)

    @property
    def sel_count(self) -> int:
        return len(self._sel)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _w2c(self, x: float, y: float) -> tuple[float, float]:
        return x * self._scale + self._ox, -y * self._scale + self._oy

    def _c2w(self, cx: float, cy: float) -> tuple[float, float]:
        return (cx - self._ox) / self._scale, -(cy - self._oy) / self._scale

    # ── Internal ──────────────────────────────────────────────────────────────

    def _notify(self) -> None:
        self.selectionChanged.emit(len(self._sel))

    def _update_cursor(self) -> None:
        if self._measure_mode or self._mode in ("draw", "edit"):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()

    def _push_undo(self) -> None:
        self._undo_stack.append([list(p) for p in self._polys])
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _bbox(self) -> tuple[float, float, float, float]:
        pts = [pt for p in self._polys for pt in p]
        if self._img_bounds:
            bw, bh = self._img_bounds
            pts.extend([(0.0, 0.0), (bw, bh)])
        if not pts:
            return 0.0, 0.0, 1.0, 1.0
        xs, ys = zip(*pts)
        return min(xs), min(ys), max(xs), max(ys)

    def _fit(self) -> None:
        vp = self.viewport()
        w = max(vp.width(), 100)
        h = max(vp.height(), 100)
        x0, y0, x1, y1 = self._bbox()
        dw, dh = x1 - x0, y1 - y0
        if dw > 0 and dh > 0:
            self._scale = min(w / dw, h / dh) * 0.85
            self._fit_scale = self._scale
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self._ox = w / 2 - cx * self._scale
        self._oy = h / 2 + cy * self._scale
        self._redraw()

    def _escape_cb(self) -> None:
        if self._mode == "draw":
            if self._draw_pts:
                self._draw_pts.clear()
                self._redraw()
            else:
                self.set_mode("select")
        elif self._mode == "edit":
            if self._edit_dragging:
                self._edit_dragging = False
                self._redraw()
            else:
                self.set_mode("select")
        elif self._measure_mode:
            self.toggle_measure()
        else:
            self.deselect_all()

    def _key_delete(self) -> None:
        if self._mode == "select":
            self.delete_selected()

    def _key_backspace(self) -> None:
        if self._mode == "draw" and self._draw_pts:
            self._draw_pts.pop()
            self._redraw()
        elif self._mode == "select":
            self.delete_selected()

    def _finish_draw(self) -> None:
        if self._mode != "draw" or len(self._draw_pts) < 2:
            return
        self._push_undo()
        self._polys.append(list(self._draw_pts))
        # Split any existing polylines that the newly drawn segments cross
        self._split_existing_at_poly(self._polys[-1])
        self._notify()
        self._fire_poly_change()
        self._draw_pts.clear()
        self._redraw()

    def _zoom_by(self, factor: float) -> None:
        vp = self.viewport()
        w, h = max(vp.width(), 100), max(vp.height(), 100)
        cx, cy = w / 2, h / 2
        wx, wy = self._c2w(cx, cy)
        self._scale *= factor
        self._ox = cx - wx * self._scale
        self._oy = cy + wy * self._scale
        self._redraw()

    # ── Hit testing ───────────────────────────────────────────────────────────

    def _snap_to_polyline(self, cx: float, cy: float) -> tuple[float, float] | None:
        """Return the nearest world-space point on any polyline within _SNAP_DIST pixels.

        Checks vertices first (they take priority at equal distance), then edges.
        """
        best_dist = _SNAP_DIST
        best_pt: tuple[float, float] | None = None
        # Check vertices
        for poly in self._polys:
            for pt in poly:
                sx, sy = self._w2c(*pt)
                d = math.hypot(cx - sx, cy - sy)
                if d < best_dist:
                    best_dist = d
                    best_pt = pt
        # Check edges
        for poly in self._polys:
            n = len(poly)
            for vi in range(n):
                ax, ay = poly[vi]
                bx, by = poly[(vi + 1) % n]
                dx, dy = bx - ax, by - ay
                seg_len_sq = dx * dx + dy * dy
                if seg_len_sq < 1e-12:
                    continue
                wwx, wwy = self._c2w(cx, cy)
                t = max(
                    0.0,
                    min(
                        1.0,
                        ((wwx - ax) * dx + (wwy - ay) * dy) / seg_len_sq,
                    ),
                )
                px, py_ = ax + t * dx, ay + t * dy
                scx, scy = self._w2c(px, py_)
                d = math.hypot(cx - scx, cy - scy)
                if d < best_dist:
                    best_dist = d
                    best_pt = (px, py_)
        return best_pt

    @staticmethod
    def _angle_snap(ax: float, ay: float, wx: float, wy: float) -> tuple[float, float]:
        """Snap (wx, wy) to the nearest 45-degree ray from (ax, ay)."""
        dxx = wx - ax
        dyy = wy - ay
        dist = math.hypot(dxx, dyy)
        if dist < 1e-9:
            return (wx, wy)
        angle = math.atan2(dyy, dxx)
        # Round to nearest 45° (pi/4)
        snapped = round(angle / (math.pi / 4)) * (math.pi / 4)
        return (ax + dist * math.cos(snapped), ay + dist * math.sin(snapped))

    def _find_nearest_vertex(self, cx: float, cy: float) -> tuple[int, int] | None:
        best_dist = _VERT_HIT
        best = None
        for pi, poly in enumerate(self._polys):
            for vi, pt in enumerate(poly):
                sx, sy = self._w2c(*pt)
                d = math.hypot(cx - sx, cy - sy)
                if d < best_dist:
                    best_dist = d
                    best = (pi, vi)
        return best

    def _find_nearest_edge(
        self, cx: float, cy: float
    ) -> tuple[int, int, tuple[float, float]] | None:
        best_dist = _EDGE_HIT
        best = None
        wx, wy = self._c2w(cx, cy)
        for pi, poly in enumerate(self._polys):
            n = len(poly)
            for vi in range(n):
                ax, ay = poly[vi]
                bx, by = poly[(vi + 1) % n]
                dx, dy = bx - ax, by - ay
                seg_len_sq = dx * dx + dy * dy
                if seg_len_sq < 1e-12:
                    continue
                t = max(
                    0.0,
                    min(
                        1.0,
                        ((wx - ax) * dx + (wy - ay) * dy) / seg_len_sq,
                    ),
                )
                px, py_ = ax + t * dx, ay + t * dy
                scx, scy = self._w2c(px, py_)
                d = math.hypot(cx - scx, cy - scy)
                if d < best_dist:
                    best_dist = d
                    best = (pi, vi, (px, py_))
        return best

    def _find_poly_at(self, cx: float, cy: float) -> int | None:
        best_dist = 8.0
        best = None
        wx, wy = self._c2w(cx, cy)
        for pi, poly in enumerate(self._polys):
            n = len(poly)
            for vi in range(n):
                ax, ay = poly[vi]
                bx, by = poly[(vi + 1) % n]
                dx, dy = bx - ax, by - ay
                seg_len_sq = dx * dx + dy * dy
                if seg_len_sq < 1e-12:
                    d = math.hypot(cx - self._w2c(ax, ay)[0], cy - self._w2c(ax, ay)[1])
                else:
                    t = max(
                        0.0,
                        min(
                            1.0,
                            ((wx - ax) * dx + (wy - ay) * dy) / seg_len_sq,
                        ),
                    )
                    px, py_ = ax + t * dx, ay + t * dy
                    scx, scy = self._w2c(px, py_)
                    d = math.hypot(cx - scx, cy - scy)
                if d < best_dist:
                    best_dist = d
                    best = pi
        return best

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        vp = self.viewport()
        w = max(vp.width(), 100)
        h = max(vp.height(), 100)

        # Background image overlay
        if self._bg_pil and self._bg_w_mm > 0 and self._bg_h_mm > 0:
            self._paint_bg_image(painter)

        # Image bounds reference rectangle
        if self._img_bounds:
            bw, bh = self._img_bounds
            cx0, cy0 = self._w2c(0.0, 0.0)
            cx1, cy1 = self._w2c(bw, bh)
            pen = QPen(QColor("#334466"), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(QPointF(cx0, cy0), QPointF(cx1, cy1)))

        # Polylines
        for idx, poly in enumerate(self._polys):
            if len(poly) < 2:
                continue
            sel = idx in self._sel
            color = QColor(_SEL) if sel else QColor(_POLY)
            lw = 2.0 if sel else 1.5
            pen = QPen(color, lw)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            sx, sy = self._w2c(*poly[0])
            path.moveTo(sx, sy)
            for pt in poly[1:]:
                px, py_ = self._w2c(*pt)
                path.lineTo(px, py_)
            if (
                len(poly) >= 3
                and math.hypot(poly[-1][0] - poly[0][0], poly[-1][1] - poly[0][1]) < 0.5
            ):
                path.closeSubpath()
            painter.drawPath(path)

        # Selection bounding box
        if self._sel and self._mode == "select":
            sel_pts = [
                pt for i in self._sel if i < len(self._polys) for pt in self._polys[i]
            ]
            if sel_pts:
                xs, ys = zip(*sel_pts)
                bx0, by0 = self._w2c(min(xs), max(ys))
                bx1, by1 = self._w2c(max(xs), min(ys))
                pad = 4
                pen = QPen(QColor(_SEL), 1.0, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(
                    QRectF(
                        bx0 - pad, by0 - pad, bx1 - bx0 + 2 * pad, by1 - by0 + 2 * pad
                    )
                )

        # Edit mode: vertex handles
        if self._mode == "edit":
            self._paint_edit_handles(painter)

        # Draw mode: dim vertex guides + snap ring
        if self._mode == "draw":
            _dim_dot = QColor("#3a4a5a")
            for _dpoly in self._polys:
                for _dpt in _dpoly:
                    _dcx, _dcy = self._w2c(*_dpt)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(_dim_dot))
                    painter.drawEllipse(QPointF(_dcx, _dcy), 2, 2)
            if self._draw_snap is not None:
                _dsx, _dsy = self._w2c(*self._draw_snap)
                painter.setPen(QPen(_SNAP_CLOSE, 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(_dsx, _dsy), 6, 6)

        # In-progress draw polygon
        if self._draw_pts:
            self._paint_in_progress_poly(painter)

        # Rubber-band
        if self._shift_drag and self._band_start and self._lmb_prev:
            pen = QPen(QColor("#ff8800"), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            bx, by = self._band_start.x(), self._band_start.y()
            painter.drawRect(
                QRectF(
                    QPointF(bx, by),
                    QPointF(self._lmb_prev.x(), self._lmb_prev.y()),
                )
            )

        # Measure overlay
        if self._measure_mode and self._measure_anchor and self._measure_hover:
            self._paint_measure_overlay(painter)

        # Pre-anchor measure snap indicator
        if (
            self._measure_mode
            and self._measure_anchor is None
            and self._measure_hover_pre is not None
        ):
            _mpx, _mpy = self._w2c(*self._measure_hover_pre)
            painter.setPen(QPen(_SNAP_CLOSE, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(_mpx, _mpy), 6, 6)

        # Info overlay
        n, s = len(self._polys), len(self._sel)
        info = f"{n} polylines" + (f"  ·  {s} selected" if s else "")
        if self._mode == "draw":
            pts_hint = f"  {len(self._draw_pts)} pt(s)" if self._draw_pts else ""
            info += f"  ·  DRAW{pts_hint}"
        elif self._mode == "edit":
            info += "  ·  EDIT"

        painter.setPen(QColor(_DIM))
        painter.setFont(QFont("Helvetica", 10))
        painter.drawText(8, 18, info)

        zoom_pct = int(round(self._scale / max(self._fit_scale, 1e-9) * 100))
        if self._mode == "draw":
            hint = "[click=add  ⌫=undo pt  dbl/Enter=finish  near start=close  Esc=cancel  D=exit]"
        elif self._mode == "edit":
            hint = "[drag vert  dbl-click edge=insert  right-click vert=delete  E=exit]"
        else:
            hint = "[F=fit  \u2318Z=undo  \u2318A=all  \u2318C/V/D/X=clip  \u2190\u2191\u2192\u2193=nudge  Del  M D E=modes]"
        painter.setFont(QFont("Helvetica", 9))
        painter.drawText(8, h - 8, f"{zoom_pct}%  {hint}")

        if not self._polys and not self._draw_pts:
            painter.setPen(QColor("#3b4a6a"))
            painter.setFont(QFont("Helvetica", 12))
            painter.drawText(
                QRectF(0, 0, w, h),
                Qt.AlignmentFlag.AlignCenter,
                "No polylines loaded",
            )

        # Cursor position
        if self._cursor_wx is not None:
            painter.setPen(QColor(_DIM))
            painter.setFont(QFont("Helvetica", 10))
            text = f"{self._cursor_wx:.2f}, {self._cursor_wy:.2f} mm"
            fm = QFontMetrics(painter.font())
            tw = fm.horizontalAdvance(text)
            painter.drawText(w - tw - 8, h - 8, text)

        # Measure button
        self._paint_measure_button(painter, w)

        painter.end()

    def _paint_bg_image(self, painter: QPainter) -> None:
        target_w = max(1, int(self._bg_w_mm * self._scale))
        target_h = max(1, int(self._bg_h_mm * self._scale))
        max_dim = 1200
        if max(target_w, target_h) > max_dim:
            ratio = max_dim / max(target_w, target_h)
            target_w = max(1, int(target_w * ratio))
            target_h = max(1, int(target_h * ratio))
        if (
            self._bg_pixmap is None
            or abs(self._scale - self._bg_cached_scale) > self._bg_cached_scale * 0.01
        ):
            try:
                resized = self._bg_pil.resize((target_w, target_h), PILImage.LANCZOS)
                self._bg_pixmap = _pil_to_qpixmap(resized)
                self._bg_cached_scale = self._scale
            except Exception:
                return
        cx, cy = self._w2c(0.0, self._bg_h_mm)
        painter.drawPixmap(QPointF(cx, cy), self._bg_pixmap)

    def _paint_edit_handles(self, painter: QPainter) -> None:
        for pi, poly in enumerate(self._polys):
            for vi, pt in enumerate(poly):
                cx, cy = self._w2c(*pt)
                is_hover = self._hover_vert == (pi, vi)
                is_active = (
                    self._edit_dragging
                    and self._edit_poly == pi
                    and self._edit_vert == vi
                )
                if is_active:
                    color = _HANDLE_ACTIVE
                    r = _HANDLE_R + 2
                elif is_hover:
                    color = _HANDLE_HOVER
                    r = _HANDLE_R + 1
                else:
                    color = _HANDLE
                    r = _HANDLE_R
                pen = QPen(color, 1.5)
                painter.setPen(pen)
                if is_active or is_hover:
                    painter.setBrush(QBrush(color))
                else:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), r, r)

    def _paint_in_progress_poly(self, painter: QPainter) -> None:
        pts_screen = [self._w2c(*pt) for pt in self._draw_pts]

        if len(pts_screen) >= 2:
            pen = QPen(_DRAW_COLOR, 1.5)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(*pts_screen[0])
            for px, py_ in pts_screen[1:]:
                path.lineTo(px, py_)
            painter.drawPath(path)

        for i, pt in enumerate(self._draw_pts):
            cx, cy = self._w2c(*pt)
            if i == 0 and len(self._draw_pts) >= 3 and self._cursor_wx is not None:
                start_cx, start_cy = self._w2c(*self._draw_pts[0])
                cur_cx, cur_cy = self._w2c(self._cursor_wx, self._cursor_wy)
                dist = math.hypot(cur_cx - start_cx, cur_cy - start_cy)
                if dist < _SNAP_DIST:
                    pen = QPen(_SNAP_CLOSE, 2)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(cx, cy), 7, 7)
                    last_cx, last_cy = self._w2c(*self._draw_pts[-1])
                    pen = QPen(_SNAP_CLOSE, 1.0, Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.drawLine(
                        QPointF(last_cx, last_cy),
                        QPointF(start_cx, start_cy),
                    )

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(_DRAW_COLOR))
            painter.drawEllipse(QPointF(cx, cy), 3, 3)

        if self._cursor_wx is not None and self._draw_pts:
            last = self._w2c(*self._draw_pts[-1])
            cur_c = self._w2c(self._cursor_wx, self._cursor_wy)
            pen = QPen(_DRAW_COLOR, 1.0, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(*last), QPointF(*cur_c))

    def _paint_measure_button(self, painter: QPainter, canvas_w: int) -> None:
        pad, bh, bw = 6, 22, 114
        label = "\u2715 Measure [M]" if self._measure_mode else "\u2295 Measure [M]"
        color = _MEASURE_COLOR if self._measure_mode else QColor(_DIM)
        bg = QColor("#002233") if self._measure_mode else QColor("#14141e")
        x1, y1 = canvas_w - bw - pad, pad
        x2, y2 = canvas_w - pad, pad + bh
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRect(QRectF(x1, y1, bw, bh))
        painter.setFont(QFont("Helvetica", 10))
        painter.setPen(color)
        painter.drawText(QRectF(x1, y1, bw, bh), Qt.AlignmentFlag.AlignCenter, label)
        self._mbtn_rect = (x1, y1, x2, y2)

    def _hit_measure_button(self, cx: float, cy: float) -> bool:
        x1, y1, x2, y2 = self._mbtn_rect
        return x1 <= cx <= x2 and y1 <= cy <= y2

    def _paint_measure_overlay(self, painter: QPainter) -> None:
        ax, ay = self._measure_anchor
        hx, hy = self._measure_hover
        cax, cay = self._w2c(ax, ay)
        chx, chy = self._w2c(hx, hy)
        dist = math.hypot(hx - ax, hy - ay)
        dx = abs(hx - ax)
        dy = abs(hy - ay)
        angle_deg = math.degrees(math.atan2(hy - ay, hx - ax)) if dist > 1e-9 else 0.0

        pen = QPen(_MEASURE_COLOR, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(cax, cay), QPointF(chx, chy))

        # Snap rings on anchor
        if self._measure_snapped_a:
            painter.setPen(QPen(_SNAP_CLOSE, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cax, cay), 8, 8)

        r = 5
        painter.setPen(QPen(_MEASURE_COLOR, 2))
        painter.setBrush(QBrush(QColor("#001522")))
        painter.drawEllipse(QPointF(cax, cay), r, r)
        painter.setPen(QPen(_MEASURE_COLOR, 1))
        painter.drawLine(QPointF(cax - 8, cay), QPointF(cax + 8, cay))
        painter.drawLine(QPointF(cax, cay - 8), QPointF(cax, cay + 8))

        # Snap ring on hover/end
        if self._measure_snapped_b or (
            not self._measure_locked and self._snap_to_polyline(chx, chy) is not None
        ):
            painter.setPen(QPen(_SNAP_CLOSE, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(chx, chy), 8, 8)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_MEASURE_COLOR))
        painter.drawEllipse(QPointF(chx, chy), 3, 3)

        mx, my = (cax + chx) / 2, (cay + chy) / 2
        badge_y = my - 28

        if not self._measure_locked:
            painter.setPen(QPen(_MEASURE_COLOR, 1))
            painter.setBrush(QBrush(QColor("#001522")))
            painter.drawRect(QRectF(mx - 100, badge_y - 14, 200, 32))
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Helvetica", 11, QFont.Weight.Bold))
            painter.drawText(
                QRectF(mx - 100, badge_y - 14, 200, 18),
                Qt.AlignmentFlag.AlignCenter,
                f"{dist:.2f} mm  {angle_deg:.1f}\u00b0",
            )
            painter.setPen(_MEASURE_COLOR)
            painter.setFont(QFont("Helvetica", 9))
            painter.drawText(
                QRectF(mx - 100, badge_y, 200, 18),
                Qt.AlignmentFlag.AlignCenter,
                f"\u0394x {dx:.2f}  \u0394y {dy:.2f}  [\u21e7=snap angle]",
            )
        else:
            # When locked, draw the delta info below the badge
            painter.setPen(QPen(_MEASURE_COLOR, 1))
            painter.setBrush(QBrush(QColor("#001522")))
            painter.drawRect(QRectF(mx - 120, badge_y + 8, 240, 18))
            painter.setPen(_MEASURE_COLOR)
            painter.setFont(QFont("Helvetica", 9))
            painter.drawText(
                QRectF(mx - 120, badge_y + 8, 240, 18),
                Qt.AlignmentFlag.AlignCenter,
                f"\u0394x {dx:.2f}  \u0394y {dy:.2f}  {angle_deg:.1f}°  ·  click to reset",
            )

    # ── Events ────────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._needs_fit and self._polys:
            self._needs_fit = False
            self._fit()
        else:
            self._redraw()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift_mod = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # Standard keyboard shortcuts
        if ctrl and self._selectable:
            if key == Qt.Key.Key_Z:
                self.undo()
                return
            elif key == Qt.Key.Key_A:
                if shift_mod:
                    self.deselect_all()
                else:
                    self.select_all()
                return
            elif key == Qt.Key.Key_C:
                self._copy_selected()
                return
            elif key == Qt.Key.Key_V:
                self._paste_clipboard()
                return
            elif key == Qt.Key.Key_D:
                self._duplicate_selected()
                return
            elif key == Qt.Key.Key_X:
                self._cut_selected()
                return

        # Arrow key nudge
        if (
            self._selectable
            and self._sel
            and key
            in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down)
        ):
            amount = 1.0 if shift_mod else 0.1
            dx, dy = 0.0, 0.0
            if key == Qt.Key.Key_Left:
                dx = -amount
            elif key == Qt.Key.Key_Right:
                dx = amount
            elif key == Qt.Key.Key_Up:
                dy = amount
            elif key == Qt.Key.Key_Down:
                dy = -amount
            self._nudge_selected(dx, dy)
            return

        if key == Qt.Key.Key_F:
            self.fit()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom_by(1.15)
        elif key == Qt.Key.Key_Minus:
            self._zoom_by(1 / 1.15)
        elif key == Qt.Key.Key_M:
            self.toggle_measure()
        elif key == Qt.Key.Key_Escape:
            self._escape_cb()
        elif self._selectable:
            if key == Qt.Key.Key_Delete:
                self._key_delete()
            elif key == Qt.Key.Key_Backspace:
                self._key_backspace()
            elif key == Qt.Key.Key_D:
                self.set_mode("draw" if self._mode != "draw" else "select")
            elif key == Qt.Key.Key_E:
                self.set_mode("edit" if self._mode != "edit" else "select")
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._finish_draw()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta == 0:
            event.accept()
            return
        factor = max(0.9, min(1.1, 1.0 + delta * 0.0007))
        pos = event.position()
        wx, wy = self._c2w(pos.x(), pos.y())
        self._scale *= factor
        self._ox = pos.x() - wx * self._scale
        self._oy = pos.y() + wy * self._scale
        self._redraw()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()
        btn = event.button()

        if btn == Qt.MouseButton.MiddleButton:
            self._mmb_prev = pos
            return

        if btn == Qt.MouseButton.RightButton:
            if self._selectable:
                self._rightclick_cb(pos.x(), pos.y())
            return

        if btn != Qt.MouseButton.LeftButton:
            return

        if self._hit_measure_button(pos.x(), pos.y()):
            self.toggle_measure()
            return

        if self._measure_mode:
            if self._measure_locked:
                # Click again to reset measurement
                self._measure_locked = False
                self._measure_anchor = None
                self._measure_hover = None
                self._measure_end = None
                self._measure_snapped_a = False
                self._measure_snapped_b = False
                self._dismiss_measure_edit()
                self._redraw()
                return
            wx, wy = self._c2w(pos.x(), pos.y())
            snap_pt = self._snap_to_polyline(pos.x(), pos.y())
            snapped = snap_pt is not None
            if snapped:
                wx, wy = snap_pt
            # Angle snap with Shift
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if shift and self._measure_anchor is not None:
                wx, wy = self._angle_snap(*self._measure_anchor, wx, wy)
            if self._measure_anchor is None:
                self._measure_anchor = (wx, wy)
                self._measure_hover = (wx, wy)
                self._measure_snapped_a = snapped
            else:
                self._measure_end = (wx, wy)
                self._measure_hover = (wx, wy)
                self._measure_snapped_b = snapped
                self._measure_locked = True
                self._show_measure_edit()
            self._redraw()
            return

        if self._mode == "edit":
            hit = self._find_nearest_vertex(pos.x(), pos.y())
            if hit is not None:
                pi, vi = hit
                self._push_undo()
                self._edit_poly = pi
                self._edit_vert = vi
                self._edit_dragging = True
                self._redraw()
                return
            self._lmb_press = pos
            self._lmb_prev = pos
            return

        if self._mode == "draw":
            wx, wy = self._c2w(pos.x(), pos.y())
            if self._draw_snap is not None:
                wx, wy = self._draw_snap
            if len(self._draw_pts) >= 3:
                start_cx, start_cy = self._w2c(*self._draw_pts[0])
                if math.hypot(pos.x() - start_cx, pos.y() - start_cy) < _SNAP_DIST:
                    self._draw_pts.append(self._draw_pts[0])
                    self._finish_draw()
                    return
            self._draw_pts.append((wx, wy))
            self._redraw()
            return

        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._selectable and shift:
            self._shift_drag = True
            self._band_start = pos
            self._lmb_press = None
            self._lmb_prev = pos
            self._lmb_target = None
        else:
            self._shift_drag = False
            self._band_start = None
            self._lmb_press = pos
            self._lmb_prev = pos
            target = self._find_poly_at(pos.x(), pos.y())
            self._lmb_target = target
            # Prepare for move if clicking on an already-selected poly
            if target is not None and target in self._sel:
                wx, wy = self._c2w(pos.x(), pos.y())
                self._move_origin = (wx, wy)
                self._move_dragging = False
                self._move_undo_pushed = False

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        wx, wy = self._c2w(pos.x(), pos.y())
        self._cursor_wx = wx
        self._cursor_wy = wy

        if self._mmb_prev is not None and event.buttons() & Qt.MouseButton.MiddleButton:
            self._ox += pos.x() - self._mmb_prev.x()
            self._oy += pos.y() - self._mmb_prev.y()
            self._mmb_prev = pos
            self._redraw()
            return

        if self._measure_mode:
            if self._measure_locked:
                return
            snap_pt = self._snap_to_polyline(pos.x(), pos.y())
            if self._measure_anchor is None:
                # Pre-first-click: just track snap indicator
                self._measure_hover_pre = snap_pt
                self._redraw()
                return
            # After anchor placed — compute hover with snap + optional angle snap
            if snap_pt is not None:
                mx, my = snap_pt
            else:
                mx, my = wx, wy
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                mx, my = self._angle_snap(*self._measure_anchor, mx, my)
            self._measure_hover = (mx, my)
            self._redraw()
            return

        if self._mode == "edit" and self._edit_dragging:
            self._polys[self._edit_poly][self._edit_vert] = (wx, wy)
            self._redraw()
            return

        if self._mode == "edit":
            old_hover = self._hover_vert
            self._hover_vert = self._find_nearest_vertex(pos.x(), pos.y())
            if self._hover_vert != old_hover:
                self._redraw()
            return

        if self._mode == "draw":
            self._draw_snap = self._snap_to_polyline(pos.x(), pos.y())
            self._redraw()
            return

        if event.buttons() & Qt.MouseButton.LeftButton:
            if self._shift_drag and self._band_start:
                self._lmb_prev = pos
                self._redraw()
                return
            # Move selected shapes
            if self._move_origin is not None and self._lmb_press is not None:
                dx_px = pos.x() - self._lmb_press.x()
                dy_px = pos.y() - self._lmb_press.y()
                if not self._move_dragging and (
                    abs(dx_px) > _DRAG_THRESH or abs(dy_px) > _DRAG_THRESH
                ):
                    self._move_dragging = True
                    self._nudge_undo_pushed = False
                if self._move_dragging:
                    if not self._move_undo_pushed:
                        self._push_undo()
                        self._move_undo_pushed = True
                    new_wx, new_wy = self._c2w(pos.x(), pos.y())
                    dx_w = new_wx - self._move_origin[0]
                    dy_w = new_wy - self._move_origin[1]
                    for idx in self._sel:
                        self._polys[idx] = [
                            (x + dx_w, y + dy_w) for x, y in self._polys[idx]
                        ]
                    self._move_origin = (new_wx, new_wy)
                    self._redraw()
                    return
            if self._lmb_prev:
                self._ox += pos.x() - self._lmb_prev.x()
                self._oy += pos.y() - self._lmb_prev.y()
                self._lmb_prev = pos
                self._redraw()
        else:
            self._redraw()

    def mouseReleaseEvent(self, event: QMouseEvent):
        pos = event.position()

        if event.button() == Qt.MouseButton.MiddleButton:
            self._mmb_prev = None
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._measure_mode:
            return

        if self._mode == "edit" and self._edit_dragging:
            self._edit_dragging = False
            self._redraw()
            self._notify()
            self._fire_poly_change()
            return

        if self._mode == "draw":
            return

        if self._shift_drag and self._band_start and self._selectable:
            bx, by = self._band_start.x(), self._band_start.y()
            x1c, x2c = min(bx, pos.x()), max(bx, pos.x())
            y1c, y2c = min(by, pos.y()), max(by, pos.y())
            for idx, poly in enumerate(self._polys):
                pts_c = [self._w2c(x, y) for x, y in poly]
                if any(x1c <= cx <= x2c and y1c <= cy <= y2c for cx, cy in pts_c):
                    self._sel.add(idx)
            self._redraw()
            self._notify()
            self._shift_drag = False
            self._band_start = None
            return

        if self._move_dragging:
            # Move completed — already applied incrementally
            self._move_dragging = False
            self._move_origin = None
            self._move_undo_pushed = False
            self._lmb_press = None
            self._lmb_prev = None
            self._lmb_target = None
            self._redraw()
            self._notify()
            return

        if (
            self._selectable
            and self._lmb_press is not None
            and self._lmb_target is not None
        ):
            dx = pos.x() - self._lmb_press.x()
            dy = pos.y() - self._lmb_press.y()
            if abs(dx) <= _DRAG_THRESH and abs(dy) <= _DRAG_THRESH:
                idx = self._lmb_target
                if idx in self._sel:
                    self._sel.discard(idx)
                else:
                    self._sel.add(idx)
                self._redraw()
                self._notify()
        self._lmb_press = None
        self._lmb_prev = None
        self._lmb_target = None
        self._shift_drag = False
        self._band_start = None
        self._move_origin = None
        self._move_undo_pushed = False

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if self._mode == "draw":
            wx, wy = self._c2w(pos.x(), pos.y())
            self._draw_pts.append((wx, wy))
            self._finish_draw()
            return
        if self._mode == "edit":
            hit = self._find_nearest_edge(pos.x(), pos.y())
            if hit is not None:
                pi, seg_idx, pt = hit
                self._push_undo()
                self._polys[pi].insert(seg_idx + 1, pt)
                self._redraw()
                self._notify()

    def _show_measure_edit(self) -> None:
        """Show a QLineEdit overlay for editing the measured distance."""
        self._dismiss_measure_edit()
        if not self._measure_anchor or not self._measure_end:
            return
        ax, ay = self._measure_anchor
        hx, hy = self._measure_end
        dist = math.hypot(hx - ax, hy - ay)
        cax, cay = self._w2c(ax, ay)
        chx, chy = self._w2c(hx, hy)
        mx, my = (cax + chx) / 2, (cay + chy) / 2

        le = QLineEdit(self.viewport())
        le.setText(f"{dist:.2f}")
        le.setFixedWidth(100)
        le.setFixedHeight(24)
        le.setAlignment(Qt.AlignmentFlag.AlignCenter)
        le.setStyleSheet(
            "background: #001522; color: #ffffff; border: 1px solid #00d8ff;"
            "border-radius: 3px; font-size: 12px; font-weight: bold;"
        )
        le.move(int(mx - 50), int(my - 40))
        le.show()
        le.setFocus()
        le.selectAll()
        le.returnPressed.connect(self._apply_measure_scale)
        self._measure_edit = le

    def _dismiss_measure_edit(self) -> None:
        """Remove the measure distance QLineEdit overlay."""
        if self._measure_edit is not None:
            self._measure_edit.hide()
            self._measure_edit.deleteLater()
            self._measure_edit = None

    def _apply_measure_scale(self) -> None:
        """Read new distance from the edit overlay and scale all polylines."""
        if not self._measure_edit or not self._measure_anchor or not self._measure_end:
            self._dismiss_measure_edit()
            return
        try:
            new_dist = float(self._measure_edit.text())
        except ValueError:
            self._dismiss_measure_edit()
            return
        ax, ay = self._measure_anchor
        hx, hy = self._measure_end
        old_dist = math.hypot(hx - ax, hy - ay)
        if old_dist < 1e-9 or new_dist <= 0:
            self._dismiss_measure_edit()
            return
        factor = new_dist / old_dist
        self._scale_all(factor)
        self._dismiss_measure_edit()
        self._measure_locked = False
        self._measure_anchor = None
        self._measure_hover = None
        self._measure_end = None
        self._measure_snapped_a = False
        self._measure_snapped_b = False
        self._redraw()

    # ── Clipboard & nudge helpers ─────────────────────────────────────────────

    def _copy_selected(self) -> None:
        if not self._sel:
            return
        self._clipboard = [
            list(self._polys[i]) for i in sorted(self._sel) if i < len(self._polys)
        ]

    def _paste_clipboard(self) -> None:
        if not self._clipboard:
            return
        self._push_undo()
        offset = 1.0  # mm
        new_indices = []
        for poly in self._clipboard:
            new_poly = [(x + offset, y + offset) for x, y in poly]
            self._polys.append(new_poly)
            new_indices.append(len(self._polys) - 1)
        self._sel = set(new_indices)
        self._redraw()
        self._notify()

    def _duplicate_selected(self) -> None:
        if not self._sel:
            return
        self._copy_selected()
        self._paste_clipboard()

    def _cut_selected(self) -> None:
        if not self._sel:
            return
        self._copy_selected()
        self._push_undo()
        self._polys = [p for i, p in enumerate(self._polys) if i not in self._sel]
        self._sel.clear()
        self._redraw()
        self._notify()

    def _nudge_selected(self, dx: float, dy: float) -> None:
        if not self._sel:
            return
        if not self._nudge_undo_pushed:
            self._push_undo()
            self._nudge_undo_pushed = True
            QTimer.singleShot(500, self._reset_nudge_undo)
        for idx in self._sel:
            if idx < len(self._polys):
                self._polys[idx] = [(x + dx, y + dy) for x, y in self._polys[idx]]
        self._redraw()
        self._notify()

    def _reset_nudge_undo(self) -> None:
        self._nudge_undo_pushed = False

    def _scale_all(self, factor: float) -> None:
        """Scale all polylines uniformly around their bounding box center."""
        if not self._polys:
            return
        self._push_undo()
        all_pts = [pt for p in self._polys for pt in p]
        xs, ys = zip(*all_pts)
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        self._polys = [
            [(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in poly]
            for poly in self._polys
        ]
        self._redraw()
        self._notify()

    @staticmethod
    def _seg_intersect_t(
        ax: float,
        ay: float,
        bx: float,
        by: float,
        cx: float,
        cy: float,
        dx: float,
        dy: float,
    ) -> tuple[float, float, tuple[float, float]] | None:
        """Intersect drawn segment AB with poly edge CD.

        Returns (t_along_AB, s_along_CD, point) or None.
        t in [0, 1] (endpoints of drawn line included).
        s in [0, 1)  (includes start vertex of poly edge, excludes end to
                      avoid double-counting the shared vertex on the next edge).
        """
        denom = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
        if abs(denom) < 1e-12:
            return None
        t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denom
        s = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / denom
        _eps = 1e-6
        if -_eps <= t <= 1.0 + _eps and -_eps <= s < 1.0 - _eps:
            t = max(0.0, min(1.0, t))
            s = max(0.0, s)
            return t, s, (ax + t * (bx - ax), ay + t * (by - ay))
        return None

    @staticmethod
    def _subpath(
        poly: list[tuple[float, float]], t0: float, t1: float
    ) -> list[tuple[float, float]]:
        """Sub-path of poly from global float index t0 to t1.

        Integer part of t = segment index, fractional part = lerp within segment.
        If t0 > t1 the result is reversed.
        """
        rev = t0 > t1
        if rev:
            t0, t1 = t1, t0

        def _lerp(t: float) -> tuple[float, float]:
            i = min(int(t), len(poly) - 2)
            f = t - i
            ax, ay = poly[i]
            bx, by = poly[i + 1]
            return ax + f * (bx - ax), ay + f * (by - ay)

        pts: list[tuple[float, float]] = [_lerp(t0)]
        for i in range(int(t0) + 1, int(t1) + 1):
            if i < len(poly):
                pts.append(poly[i])
        end = _lerp(t1)
        if math.hypot(end[0] - pts[-1][0], end[1] - pts[-1][1]) > 1e-6:
            pts.append(end)
        if rev:
            pts.reverse()
        return pts

    def _split_existing_at_poly(self, new_poly: list[tuple[float, float]]) -> bool:
        """Split any existing polylines that any segment of new_poly crosses.

        When exactly 2 intersection points are found the existing poly is
        replaced by two *closed* shapes — each side is sealed by the
        corresponding portion of the drawn line.

        Returns True if at least one closed 2-hit split occurred (caller should
        discard the drawn line since it is already embedded in the shapes).
        The new poly itself (last in self._polys) is never touched.
        """
        closed_split = False
        new_polys: list[list[tuple[float, float]]] = []

        for poly in self._polys[:-1]:
            n = len(poly)
            if n < 2:
                new_polys.append(poly)
                continue

            # ── collect hits ────────────────────────────────────────────────
            # edge_pos = vi + s  (float position along closed poly)
            # t_drawn  = ni + t  (float position along new_poly)
            raw: list[tuple[float, float, tuple[float, float]]] = []
            for vi in range(n):  # include wrap-around edge (n-1 → 0)
                cx, cy = poly[vi]
                dx, dy = poly[(vi + 1) % n]
                for ni in range(len(new_poly) - 1):
                    ax, ay = new_poly[ni]
                    bx, by = new_poly[ni + 1]
                    r = self._seg_intersect_t(ax, ay, bx, by, cx, cy, dx, dy)
                    if r is not None:
                        t, s, pt = r
                        raw.append((vi + s, ni + t, pt))

            if not raw:
                new_polys.append(poly)
                continue

            # ── deduplicate within 0.05 mm ───────────────────────────────
            raw.sort(key=lambda h: h[0])
            hits: list[tuple[float, float, tuple[float, float]]] = []
            for h in raw:
                if (
                    hits
                    and math.hypot(h[2][0] - hits[-1][2][0], h[2][1] - hits[-1][2][1])
                    < 0.05
                ):
                    continue
                hits.append(h)

            # ── exactly 2 hits → two closed shapes ──────────────────────
            if len(hits) == 2:
                ep, t0, p0 = hits[0]
                eq, t1, p1 = hits[1]
                e0, e1 = int(ep), int(eq)

                if e0 != e1:
                    # seg_a: p0 → (forward along poly) → p1
                    steps_a = (e1 - e0) % n
                    seg_a: list[tuple[float, float]] = [p0]
                    for k in range(steps_a):
                        seg_a.append(poly[(e0 + 1 + k) % n])
                    seg_a.append(p1)

                    # seg_b: p1 → (forward, wrapping) → p0
                    steps_b = n - steps_a
                    seg_b: list[tuple[float, float]] = [p1]
                    for k in range(steps_b):
                        seg_b.append(poly[(e1 + 1 + k) % n])
                    seg_b.append(p0)

                    # closing edges along the drawn new_poly
                    c_fwd = self._subpath(new_poly, t0, t1)  # p0 → p1
                    c_rev = self._subpath(new_poly, t1, t0)  # p1 → p0

                    # append closing path skipping the duplicate endpoint
                    shape_a = seg_a + c_rev[1:]  # ends at p1, seals back to p0
                    shape_b = seg_b + c_fwd[1:]  # ends at p0, seals back to p1

                    if len(shape_a) >= 2:
                        new_polys.append(shape_a)
                    if len(shape_b) >= 2:
                        new_polys.append(shape_b)
                    closed_split = True
                    continue
                # fall through to open split if both on same edge

            # ── fallback: open splitting (>2 hits or same-edge) ─────────
            hits.sort(key=lambda h: h[0])
            pieces: list[list[tuple[float, float]]] = []
            start_idx = 0
            prev_pt: tuple[float, float] | None = None
            for edge_pos, _t_drawn, hit_pt in hits:
                vi = int(edge_pos)
                piece: list[tuple[float, float]] = []
                if prev_pt is not None:
                    piece.append(prev_pt)
                piece.extend(poly[start_idx : vi + 1])
                piece.append(hit_pt)
                if len(piece) >= 2:
                    pieces.append(piece)
                start_idx = vi + 1
                prev_pt = hit_pt
            tail: list[tuple[float, float]] = []
            if prev_pt:
                tail.append(prev_pt)
            tail.extend(poly[start_idx:])
            if len(tail) >= 2:
                pieces.append(tail)
            new_polys.extend(pieces)

        if not closed_split:
            new_polys.append(self._polys[-1])
        self._polys = new_polys
        return closed_split

    def _fire_poly_change(self) -> None:
        """Notify the on_poly_change callback when polylines are structurally modified."""
        if callable(self._on_poly_change):
            self._on_poly_change()

    def _rightclick_cb(self, cx: float, cy: float) -> None:
        if self._mode == "draw":
            self._finish_draw()
            return

        if self._mode == "edit":
            hit = self._find_nearest_vertex(cx, cy)
            if hit is not None:
                pi, vi = hit
                menu = QMenu(self)
                if len(self._polys[pi]) > 2:
                    menu.addAction("Delete vertex", lambda: self._delete_vertex(pi, vi))
                menu.addAction("Delete polyline", lambda: self._delete_poly(pi))
                menu.popup(self.mapToGlobal(QPointF(cx, cy).toPoint()))
            return

        # Select mode context menu
        menu = QMenu(self)
        poly_hit = self._find_poly_at(cx, cy)
        if poly_hit is not None:
            idx = poly_hit
            is_sel = idx in self._sel
            if not is_sel:
                menu.addAction("Select", lambda: self._ctx_select(idx))
            else:
                menu.addAction("Deselect", lambda: self._ctx_deselect(idx))
            menu.addAction("Delete", lambda: self._ctx_delete_poly(idx))
            menu.addSeparator()
        if self._sel:
            menu.addAction(f"Delete selected ({len(self._sel)})", self.delete_selected)
            menu.addAction("Invert selection", self.invert_selection)
            menu.addAction("Deselect all", self.deselect_all)
        else:
            menu.addAction("Select all", self.select_all)
        menu.addSeparator()
        menu.addAction("Fit view  [F]", self.fit)
        mode_menu = menu.addMenu("Mode")
        mode_menu.addAction("Select  [Esc]", lambda: self.set_mode("select"))
        mode_menu.addAction("Draw  [D]", lambda: self.set_mode("draw"))
        mode_menu.addAction("Edit  [E]", lambda: self.set_mode("edit"))
        menu.popup(self.mapToGlobal(QPointF(cx, cy).toPoint()))

    def _delete_vertex(self, pi: int, vi: int) -> None:
        self._push_undo()
        self._polys[pi].pop(vi)
        self._redraw()
        self._notify()

    def _delete_poly(self, pi: int) -> None:
        self._push_undo()
        self._polys.pop(pi)
        self._sel.discard(pi)
        self._sel = {i if i < pi else i - 1 for i in self._sel if i != pi}
        self._redraw()
        self._notify()

    def _ctx_select(self, idx: int) -> None:
        self._sel.add(idx)
        self._redraw()
        self._notify()

    def _ctx_deselect(self, idx: int) -> None:
        self._sel.discard(idx)
        self._redraw()
        self._notify()

    def _ctx_delete_poly(self, idx: int) -> None:
        self._push_undo()
        self._polys.pop(idx)
        self._sel.discard(idx)
        self._sel = {i if i < idx else i - 1 for i in self._sel if i != idx}
        self._redraw()
        self._notify()


# Backward-compat alias
DxfCanvas = PolylineView
