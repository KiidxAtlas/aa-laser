"""
AA Laser Studio
───────────────
Tab 1 · FVI → DXF   — single-file or batch folder conversion
Tab 2 · Pattern Gen  — load DXF, preview/edit polylines, clip a pattern
Tab 3 · Shape Creator — build rectangle / circle / ellipse / polygon → DXF
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import ezdxf  # type: ignore[attr-defined]
from shapely import prepared  # type: ignore[import-untyped]
from shapely.geometry import (  # type: ignore[import-untyped]
    LineString,
    MultiPolygon,
    Polygon,
)
from shapely.ops import unary_union  # type: ignore[import-untyped]

try:
    from PIL import Image as _PIL_Image  # type: ignore[import-untyped]

    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# Appearance
# ─────────────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_BG = "#16213e"  # canvas background
_POLY = "#4d94ff"  # normal polyline colour
_SEL = "#ff5252"  # selected polyline colour
_DIM = "#888888"  # status text

# ─────────────────────────────────────────────────────────────────────────────
# Settings persistence
# ─────────────────────────────────────────────────────────────────────────────

_SETTINGS_FILE = Path.home() / ".aa_laser_settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text())
    except Exception:
        return {}


def save_settings(d: dict) -> None:
    try:
        _SETTINGS_FILE.write_text(json.dumps(d, indent=2))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Core: FVI → DXF
# ─────────────────────────────────────────────────────────────────────────────

_FVI_SCALE = 0.254  # FVI units → mm


def convert_fvi_to_dxf(src: Path, dst: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    x = y = 0.0
    pts: list[tuple[float, float]] = []

    def _flush() -> None:
        if len(pts) >= 2:
            msp.add_lwpolyline(pts)

    with src.open() as f:
        for raw in f:
            ln = raw.strip()
            m = re.match(r"MOVEDIST\s+([-\d.]+),([-\d.]+)", ln)
            if m:
                _flush()
                pts = []
                x += float(m.group(1))
                y += float(m.group(2))
                pts.append((x * _FVI_SCALE, y * _FVI_SCALE))
                continue
            m = re.match(r"DRAWLINE\s+([-\d.]+),([-\d.]+)", ln)
            if m:
                x += float(m.group(1))
                y += float(m.group(2))
                pts.append((x * _FVI_SCALE, y * _FVI_SCALE))
    _flush()
    doc.saveas(str(dst))


# ─────────────────────────────────────────────────────────────────────────────
# Core: DXF I/O helpers
# ─────────────────────────────────────────────────────────────────────────────


def load_dxf_polylines(path: str) -> list[list[tuple[float, float]]]:
    """Return all LWPOLYLINE entities as lists of (x, y) tuples."""
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    result: list[list[tuple[float, float]]] = []
    for ent in msp:
        if ent.dxftype() == "LWPOLYLINE":
            pts = [(float(p[0]), float(p[1])) for p in ent.get_points()]
            if len(pts) >= 2:
                result.append(pts)
    return result


def polylines_to_outline(polylines: list[list[tuple[float, float]]]):
    """Build a Shapely union polygon from a list of closed polylines."""
    polys: list[Polygon] = []
    for c in polylines:
        if len(c) < 3:
            continue
        try:
            p = Polygon(c)
            if p.is_valid and p.area > 0:
                polys.append(p)
        except Exception:
            pass
    if not polys:
        flat = [pt for c in polylines for pt in c]
        return Polygon(flat).convex_hull
    result = unary_union(polys)
    return (
        result if not result.is_empty else max(polys, key=lambda p: p.area).convex_hull
    )


def write_polylines_dxf(
    polylines: list[list[tuple[float, float]]],
    out_path: str,
    close: bool = False,
) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for c in polylines:
        if len(c) >= 2:
            msp.add_lwpolyline(c, close=close)
    doc.saveas(out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Core: pattern generators  (return list of polyline coord-lists)
# ─────────────────────────────────────────────────────────────────────────────


def _hex_verts(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    return [
        (
            cx + r * math.cos(math.pi / 6 + i * math.pi / 3),
            cy + r * math.sin(math.pi / 6 + i * math.pi / 3),
        )
        for i in range(6)
    ]


def gen_honeycomb(
    outline_poly, r: float, gap: float
) -> list[list[tuple[float, float]]]:
    col_step = 2.0 * (math.sqrt(3) / 2.0 * r) + gap
    row_step = 1.5 * r + gap * math.sqrt(3) / 2.0
    minx, miny, maxx, maxy = outline_poly.bounds
    pad = r * 2.0
    nc = int((maxx - minx + pad * 2) / col_step) + 2
    nr = int((maxy - miny + pad * 2) / row_step) + 2
    prep = prepared.prep(outline_poly)
    result: list[list[tuple[float, float]]] = []

    for row in range(nr):
        for col in range(nc):
            off = col_step / 2.0 if row & 1 else 0.0
            cx = minx - pad + col * col_step + off
            cy = miny - pad + row * row_step
            verts = _hex_verts(cx, cy, r)
            hp = Polygon(verts)
            if not prep.intersects(hp):
                continue
            if prep.contains(hp):
                result.append(verts)
                continue
            clipped = outline_poly.intersection(hp)
            if clipped.is_empty:
                continue
            geoms = (
                [clipped]
                if isinstance(clipped, Polygon)
                else list(clipped.geoms)
                if isinstance(clipped, MultiPolygon)
                else []
            )
            for g in geoms:
                if not g.is_empty and g.area >= 0.001:
                    result.append(list(g.exterior.coords))
    return result


def _collect_lines(geom, out: list) -> None:
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "LineString":
        c = list(geom.coords)
        if len(c) >= 2:
            out.append(c)
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            _collect_lines(g, out)


def gen_diamond_checkering(
    outline_poly, spacing: float, angle_deg: float = 45.0
) -> list[list[tuple[float, float]]]:
    """Two families of parallel lines at ±angle creating a diamond grid."""
    a = math.radians(angle_deg)
    minx, miny, maxx, maxy = outline_poly.bounds
    diag = math.hypot(maxx - minx, maxy - miny) + spacing * 4
    result: list[list[tuple[float, float]]] = []
    for sign in (1.0, -1.0):
        dx, dy = math.cos(sign * a), math.sin(sign * a)
        nx, ny = -dy, dx
        corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
        projs = [x * nx + y * ny for x, y in corners]
        p = min(projs) - spacing
        p_max = max(projs) + spacing
        while p <= p_max:
            cx, cy = p * nx, p * ny
            ln = LineString([
                (cx - dx * diag, cy - dy * diag),
                (cx + dx * diag, cy + dy * diag),
            ])
            _collect_lines(outline_poly.intersection(ln), result)
            p += spacing
    return result


def gen_fish_scale(
    outline_poly, scale_w: float, scale_h: float, n_pts: int = 24
) -> list[list[tuple[float, float]]]:
    """Overlapping half-ellipse arcs forming a scallop / fish-scale pattern."""
    minx, miny, maxx, maxy = outline_poly.bounds
    pad = max(scale_w, scale_h) * 1.5
    result: list[list[tuple[float, float]]] = []
    row = 0
    y = miny - pad
    while y <= maxy + pad:
        offset = scale_w / 2.0 if row & 1 else 0.0
        x = minx - pad + offset
        while x <= maxx + pad:
            pts = [
                (
                    x + (scale_w / 2.0) * math.cos(math.pi - math.pi * i / n_pts),
                    y + scale_h * math.sin(math.pi * i / n_pts),
                )
                for i in range(n_pts + 1)
            ]
            _collect_lines(outline_poly.intersection(LineString(pts)), result)
            x += scale_w
        y += scale_h
        row += 1
    return result


def gen_stipple_dots(
    outline_poly, radius: float, spacing: float
) -> list[list[tuple[float, float]]]:
    """Grid of randomly-jittered filled circles clipped to the outline."""
    import random

    rng = random.Random(42)
    minx, miny, maxx, maxy = outline_poly.bounds
    prep = prepared.prep(outline_poly)
    result: list[list[tuple[float, float]]] = []
    n_seg = 16
    jitter = spacing * 0.30
    row = 0
    y = miny + spacing / 2.0
    while y <= maxy + spacing:
        offset = (spacing / 2.0) if row & 1 else 0.0
        x = minx + spacing / 2.0 + offset
        while x <= maxx + spacing:
            jx = rng.uniform(-jitter, jitter)
            jy = rng.uniform(-jitter, jitter)
            cx, cy = x + jx, y + jy
            pts = [
                (
                    cx + radius * math.cos(2 * math.pi * i / n_seg),
                    cy + radius * math.sin(2 * math.pi * i / n_seg),
                )
                for i in range(n_seg)
            ]
            pts.append(pts[0])
            circ = Polygon(pts)
            if not prep.intersects(circ):
                x += spacing
                continue
            clipped = outline_poly.intersection(circ)
            if clipped.is_empty:
                x += spacing
                continue
            geoms = (
                [clipped]
                if isinstance(clipped, Polygon)
                else list(clipped.geoms)
                if isinstance(clipped, MultiPolygon)
                else []
            )
            for g in geoms:
                if not g.is_empty and g.area >= radius * 0.05:
                    result.append(list(g.exterior.coords))
            x += spacing
        y += spacing
        row += 1
    return result


def gen_gradient_honeycomb(
    outline_poly, r_min: float, r_max: float, gap: float, angle_deg: float = 0.0
) -> list[list[tuple[float, float]]]:
    """Honeycomb where cell radius interpolates from r_min to r_max along angle_deg.
    0°=left(small)→right(large).  90°=bottom→top."""
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    minx, miny, maxx, maxy = outline_poly.bounds
    corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
    projs = [x * dx + y * dy for x, y in corners]
    p_min, p_max = min(projs), max(projs)
    p_range = max(p_max - p_min, 1e-9)
    r_avg = (r_min + r_max) / 2
    col_step = 2.0 * (math.sqrt(3) / 2.0 * r_avg) + gap
    row_step = 1.5 * r_avg + gap * math.sqrt(3) / 2.0
    pad = r_max * 2.5
    nc = int((maxx - minx + pad * 2) / col_step) + 2
    nr = int((maxy - miny + pad * 2) / row_step) + 2
    prep = prepared.prep(outline_poly)
    result: list[list[tuple[float, float]]] = []
    for row in range(nr):
        for col in range(nc):
            off = col_step / 2.0 if row & 1 else 0.0
            cx = minx - pad + col * col_step + off
            cy = miny - pad + row * row_step
            t = max(0.0, min(1.0, (cx * dx + cy * dy - p_min) / p_range))
            r = r_min + t * (r_max - r_min)
            if r < 0.05:
                continue
            verts = _hex_verts(cx, cy, r)
            hp = Polygon(verts)
            if not prep.intersects(hp):
                continue
            if prep.contains(hp):
                result.append(verts)
                continue
            clipped = outline_poly.intersection(hp)
            if clipped.is_empty:
                continue
            geoms = (
                [clipped]
                if isinstance(clipped, Polygon)
                else list(clipped.geoms)
                if isinstance(clipped, MultiPolygon)
                else []
            )
            for g in geoms:
                if not g.is_empty and g.area >= 0.001:
                    result.append(list(g.exterior.coords))
    return result


def gen_image_halftone(
    outline_poly,
    image_path: str,
    r_min: float,
    r_max: float,
    spacing: float,
    invert: bool = False,
) -> list[list[tuple[float, float]]]:
    """Map image brightness to hex cell radius tiled across the outline.
    Dark pixels → large cells, light pixels → small cells (swap with invert=True)."""
    if not _PIL_OK:
        raise RuntimeError("Pillow is not installed. Run: pip install Pillow")
    img = _PIL_Image.open(image_path).convert("L")
    img_w, img_h = img.size
    pix = img.load()
    minx, miny, maxx, maxy = outline_poly.bounds
    col_step = spacing
    row_step = spacing * math.sqrt(3) / 2.0
    pad = r_max
    prep = prepared.prep(outline_poly)
    result: list[list[tuple[float, float]]] = []
    row = 0
    y = miny - pad
    while y <= maxy + pad:
        off = col_step / 2.0 if row & 1 else 0.0
        x = minx - pad + off
        while x <= maxx + pad:
            tx = (x - minx) / max(maxx - minx, 1e-9)
            ty = 1.0 - (y - miny) / max(maxy - miny, 1e-9)
            px = int(max(0, min(img_w - 1, tx * (img_w - 1))))
            py = int(max(0, min(img_h - 1, ty * (img_h - 1))))
            brightness = pix[px, py] / 255.0
            if invert:
                brightness = 1.0 - brightness
            # dark (0) → r_max, light (1) → r_min
            r = r_max - brightness * (r_max - r_min)
            if r >= r_min * 0.3:
                verts = _hex_verts(x, y, r)
                hp = Polygon(verts)
                if prep.intersects(hp):
                    if prep.contains(hp):
                        result.append(verts)
                    else:
                        clipped = outline_poly.intersection(hp)
                        if not clipped.is_empty:
                            geoms = (
                                [clipped]
                                if isinstance(clipped, Polygon)
                                else list(clipped.geoms)
                                if isinstance(clipped, MultiPolygon)
                                else []
                            )
                            for g in geoms:
                                if not g.is_empty and g.area >= 0.001:
                                    result.append(list(g.exterior.coords))
            x += col_step
        y += row_step
        row += 1
    return result


def gen_custom_tile(
    outline_poly,
    tile_polys: list[list[tuple[float, float]]],
    gap: float,
    angle_deg: float = 0.0,
) -> list[list[tuple[float, float]]]:
    """Tile an arbitrary DXF shape across the outline, clipped to it.
    Tiles are offset in brickwork rows. angle_deg rotates each instance."""
    all_pts = [pt for p in tile_polys for pt in p]
    if not all_pts or not tile_polys:
        return []
    txs = [p[0] for p in all_pts]
    tys = [p[1] for p in all_pts]
    t_cx = (min(txs) + max(txs)) / 2
    t_cy = (min(tys) + max(tys)) / 2
    tw = max(txs) - min(txs)
    th = max(tys) - min(tys)
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    col_step = max(tw + gap, 0.01)
    row_step = max(th + gap, 0.01)
    minx, miny, maxx, maxy = outline_poly.bounds
    pad = max(tw, th) * 2.0 + gap
    prep = prepared.prep(outline_poly)
    result: list[list[tuple[float, float]]] = []
    row = 0
    y = miny - pad
    while y <= maxy + pad:
        off = col_step / 2.0 if row & 1 else 0.0
        x = minx - pad + off
        while x <= maxx + pad:
            for tile_pts in tile_polys:
                if len(tile_pts) < 3:
                    continue
                transformed = [
                    (
                        x + (px - t_cx) * ca - (py - t_cy) * sa,
                        y + (px - t_cx) * sa + (py - t_cy) * ca,
                    )
                    for px, py in tile_pts
                ]
                try:
                    shape = Polygon(transformed)
                    if not shape.is_valid or shape.is_empty:
                        continue
                except Exception:
                    continue
                if not prep.intersects(shape):
                    continue
                if prep.contains(shape):
                    result.append(transformed)
                else:
                    clipped = outline_poly.intersection(shape)
                    if clipped.is_empty:
                        continue
                    geoms = (
                        [clipped]
                        if isinstance(clipped, Polygon)
                        else list(clipped.geoms)
                        if isinstance(clipped, MultiPolygon)
                        else []
                    )
                    for g in geoms:
                        if not g.is_empty and g.area >= 0.001:
                            result.append(list(g.exterior.coords))
            x += col_step
        y += row_step
        row += 1
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Core: shape builders  (all centred at origin)
# ─────────────────────────────────────────────────────────────────────────────


def shape_rect(w: float, h: float) -> list[tuple[float, float]]:
    hw, hh = w / 2, h / 2
    return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh), (-hw, -hh)]


def shape_rect_rounded(
    w: float, h: float, r: float, n_corner: int = 8
) -> list[tuple[float, float]]:
    """Rectangle with rounded corners, centred at origin."""
    r = min(r, w / 2, h / 2)
    hw, hh = w / 2, h / 2
    pts: list[tuple[float, float]] = []
    for cx, cy, start in [
        (hw - r, hh - r, 0.0),
        (-hw + r, hh - r, math.pi / 2),
        (-hw + r, -hh + r, math.pi),
        (hw - r, -hh + r, 3 * math.pi / 2),
    ]:
        for i in range(n_corner + 1):
            a = start + i * (math.pi / 2) / n_corner
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return pts


def shape_circle(r: float, n: int = 64) -> list[tuple[float, float]]:
    pts = [
        (r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    return pts + [pts[0]]


def shape_ellipse(rx: float, ry: float, n: int = 64) -> list[tuple[float, float]]:
    pts = [
        (rx * math.cos(2 * math.pi * i / n), ry * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    return pts + [pts[0]]


def shape_polygon(sides: int, r: float) -> list[tuple[float, float]]:
    pts = [
        (
            r * math.cos(2 * math.pi * i / sides - math.pi / 2),
            r * math.sin(2 * math.pi * i / sides - math.pi / 2),
        )
        for i in range(sides)
    ]
    return pts + [pts[0]]


# ─────────────────────────────────────────────────────────────────────────────
# DxfCanvas  –  interactive pan/zoom canvas with optional polyline selection
# ─────────────────────────────────────────────────────────────────────────────

_DRAG_THRESH = 5


class DxfCanvas(tk.Canvas):
    """
    Displays polyline lists.
    • Scroll wheel → zoom (point under cursor stays fixed)
    • Left-drag on empty space → pan
    • Left-click on polyline → toggle selection (red highlight)
    • Middle-drag → pan (alternative)

    Set ``selectable=False`` for a display-only preview.
    ``on_change(sel_count)`` fires whenever the selection or data changes.
    """

    def __init__(
        self,
        master,
        selectable: bool = True,
        on_change: "callable | None" = None,
        **kw,
    ):
        kw.setdefault("bg", _BG)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, **kw)

        self._selectable = selectable
        self._on_change = on_change

        self._polys: list[list[tuple[float, float]]] = []
        self._sel: set[int] = set()
        self._id2idx: dict[int, int] = {}

        self._scale = 1.0
        self._ox = 0.0
        self._oy = 0.0

        # LMB interaction state
        self._lmb_press: tuple[int, int] | None = None
        self._lmb_prev: tuple[int, int] | None = None
        self._lmb_target: int | None = None

        # MMB pan state
        self._mmb_prev: tuple[int, int] | None = None

        # Cursor world position (for overlay)
        self._cursor_wx: float | None = None
        self._cursor_wy: float | None = None

        # Rubber-band select state (Shift+drag)
        self._shift_drag: bool = False
        self._band_start: tuple[int, int] | None = None

        # Undo stack — each entry is a snapshot of self._polys before a delete
        self._undo_stack: list[list] = []

        # Fit scale for zoom-% display
        self._fit_scale: float = 1.0

        # Measure tool state
        self._measure_mode: bool = False
        self._measure_anchor: tuple[float, float] | None = None  # world coords
        self._measure_hover: tuple[float, float] | None = None  # world coords
        self._mbtn_rect: tuple[int, int, int, int] = (0, 0, 0, 0)

        self.bind("<Configure>", lambda _: self._fit())
        self.bind(
            "<Enter>", lambda e: self.focus_set()
        )  # focus → wheel/key events work
        self.bind("<ButtonPress-1>", self._lmb_press_cb)
        self.bind("<B1-Motion>", self._lmb_drag_cb)
        self.bind("<ButtonRelease-1>", self._lmb_release_cb)
        self.bind("<ButtonPress-2>", lambda e: setattr(self, "_mmb_prev", (e.x, e.y)))
        self.bind("<B2-Motion>", self._mmb_drag_cb)
        self.bind("<ButtonRelease-2>", lambda _: setattr(self, "_mmb_prev", None))
        self.bind("<MouseWheel>", self._scroll_cb)
        self.bind("<Button-4>", self._scroll_cb)
        self.bind("<Button-5>", self._scroll_cb)
        self.bind("<Motion>", self._motion_cb)
        # Keyboard shortcuts (work when canvas is focused)
        self.bind("<f>", lambda e: self.fit())
        self.bind("<F>", lambda e: self.fit())
        self.bind("<plus>", lambda e: self._zoom_by(1.15))
        self.bind("<equal>", lambda e: self._zoom_by(1.15))
        self.bind("<minus>", lambda e: self._zoom_by(1 / 1.15))
        self.bind("<m>", lambda e: self.toggle_measure())
        self.bind("<M>", lambda e: self.toggle_measure())
        if selectable:
            self.bind("<Delete>", lambda e: self.delete_selected())
            self.bind("<BackSpace>", lambda e: self.delete_selected())
            self.bind("<Escape>", lambda e: self._escape_cb())
            self.bind("<Button-3>", self._rightclick_cb)
            self.bind("<Control-Button-1>", self._rightclick_cb)
        else:
            self.bind("<Escape>", lambda e: self._escape_cb())

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, polys: list[list[tuple[float, float]]]) -> None:
        """Load new polylines and reset to fit view."""
        self._polys = list(polys)
        self._sel.clear()
        self._fit()
        self._notify()

    def reload(self, polys: list[list[tuple[float, float]]]) -> None:
        """Replace polylines without resetting zoom/pan."""
        self._polys = list(polys)
        self._sel &= set(range(len(self._polys)))
        self._draw()
        self._notify()

    def get_active(self) -> list[list[tuple[float, float]]]:
        """Polylines that are NOT selected (i.e. not marked for deletion)."""
        return [p for i, p in enumerate(self._polys) if i not in self._sel]

    def delete_selected(self) -> int:
        """Remove selected polylines; returns count removed."""
        n = len(self._sel)
        if n:
            self._undo_stack.append(list(self._polys))
            if len(self._undo_stack) > 20:
                self._undo_stack.pop(0)
        self._polys = [p for i, p in enumerate(self._polys) if i not in self._sel]
        self._sel.clear()
        self._draw()
        self._notify()
        return n

    def undo_delete(self) -> bool:
        """Restore the last delete snapshot. Returns True if anything was undone."""
        if not self._undo_stack:
            return False
        self._polys = self._undo_stack.pop()
        self._sel.clear()
        self._draw()
        self._notify()
        return True

    def invert_selection(self) -> None:
        self._sel = set(range(len(self._polys))) - self._sel
        self._draw()
        self._notify()

    def select_all(self) -> None:
        self._sel = set(range(len(self._polys)))
        self._draw()
        self._notify()

    def deselect_all(self) -> None:
        self._sel.clear()
        self._draw()
        self._notify()

    def toggle_measure(self) -> None:
        """Toggle measure mode. M key or clicking the canvas button."""
        self._measure_mode = not self._measure_mode
        self._measure_anchor = None
        self._measure_hover = None
        self.configure(cursor="crosshair" if self._measure_mode else "")
        self._draw()

    def _escape_cb(self) -> None:
        if self._measure_mode:
            self.toggle_measure()
        else:
            self.deselect_all()

    def fit(self) -> None:
        self._fit()

    @property
    def poly_count(self) -> int:
        return len(self._polys)

    @property
    def sel_count(self) -> int:
        return len(self._sel)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _bbox(self) -> tuple[float, float, float, float]:
        pts = [pt for p in self._polys for pt in p]
        if not pts:
            return 0.0, 0.0, 1.0, 1.0
        xs, ys = zip(*pts)
        return min(xs), min(ys), max(xs), max(ys)

    def _fit(self) -> None:
        self.update_idletasks()
        w = max(self.winfo_width(), 100)
        h = max(self.winfo_height(), 100)
        x0, y0, x1, y1 = self._bbox()
        dw, dh = x1 - x0, y1 - y0
        if dw > 0 and dh > 0:
            self._scale = min(w / dw, h / dh) * 0.85
            self._fit_scale = self._scale
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self._ox = w / 2 - cx * self._scale
        self._oy = h / 2 + cy * self._scale
        self._draw()

    def _w2c(self, x: float, y: float) -> tuple[float, float]:
        return x * self._scale + self._ox, -y * self._scale + self._oy

    def _c2w(self, cx: float, cy: float) -> tuple[float, float]:
        return (cx - self._ox) / self._scale, -(cy - self._oy) / self._scale

    def _draw(self) -> None:
        self.delete("all")
        self._id2idx.clear()
        w = max(self.winfo_width(), 100)
        h = max(self.winfo_height(), 100)

        for idx, poly in enumerate(self._polys):
            if len(poly) < 2:
                continue
            flat = [c for pt in poly for c in self._w2c(*pt)]
            sel = idx in self._sel
            color = _SEL if sel else _POLY
            lw = 2.0 if sel else 1.5
            if len(poly) >= 3:
                item = self.create_polygon(
                    flat, outline=color, fill="", width=lw, tags=(f"p{idx}",)
                )
            else:
                item = self.create_line(flat, fill=color, width=lw, tags=(f"p{idx}",))
            self._id2idx[item] = idx

        n, s = len(self._polys), len(self._sel)
        info = f"{n} polylines" + (f"  ·  {s} selected" if s else "")
        self.create_text(
            8, 8, anchor="nw", text=info, fill=_DIM, font=("Helvetica", 10)
        )
        zoom_pct = int(round(self._scale / max(self._fit_scale, 1e-9) * 100))
        self.create_text(
            8,
            h - 6,
            anchor="sw",
            text=f"{zoom_pct}%  [F=fit  +/-=zoom  Del=delete  Esc=deselect  M=measure]",
            fill=_DIM,
            font=("Helvetica", 9),
        )

        if not self._polys:
            self.create_text(
                w // 2,
                h // 2,
                text="Load a DXF file to preview",
                fill="#333366",
                font=("Helvetica", 13),
            )

        # Measure toggle button (top-right corner)
        self._draw_measure_button(w)

        # Live measure overlay (drawn on top)
        if self._measure_mode and self._measure_anchor and self._measure_hover:
            self._draw_measure_overlay()

        # Cursor coordinate overlay
        if self._cursor_wx is not None:
            self.create_text(
                w - 6,
                h - 6,
                anchor="se",
                text=f"{self._cursor_wx:.2f}, {self._cursor_wy:.2f} mm",
                fill=_DIM,
                font=("Helvetica", 10),
                tags=("cursor_pos",),
            )

    # ── Interaction ───────────────────────────────────────────────────────────

    def _draw_measure_button(self, canvas_w: int) -> None:
        """Draw the Measure toggle button in the top-right corner."""
        pad, bh, bw = 6, 22, 114
        label = "✕ Measure [M]" if self._measure_mode else "⊕ Measure [M]"
        color = "#00d8ff" if self._measure_mode else _DIM
        bg = "#002233" if self._measure_mode else "#14141e"
        x1, y1 = canvas_w - bw - pad, pad
        x2, y2 = canvas_w - pad, pad + bh
        self.create_rectangle(
            x1, y1, x2, y2, fill=bg, outline=color, width=1, tags=("measure_btn",)
        )
        self.create_text(
            (x1 + x2) // 2,
            (y1 + y2) // 2,
            text=label,
            fill=color,
            font=("Helvetica", 10),
            tags=("measure_btn",),
        )
        self._mbtn_rect = (x1, y1, x2, y2)

    def _hit_measure_button(self, cx: int, cy: int) -> bool:
        x1, y1, x2, y2 = self._mbtn_rect
        return x1 <= cx <= x2 and y1 <= cy <= y2

    def _draw_measure_overlay(self) -> None:
        """Draw live ruler line + distance badge. Call only when anchor+hover are set."""
        ax, ay = self._measure_anchor
        hx, hy = self._measure_hover
        cax, cay = self._w2c(ax, ay)
        chx, chy = self._w2c(hx, hy)
        dist = math.hypot(hx - ax, hy - ay)
        dx = abs(hx - ax)
        dy = abs(hy - ay)

        TAG = "measure_overlay"

        # Dashed ruler line
        self.create_line(
            cax, cay, chx, chy, fill="#00d8ff", width=1.5, dash=(6, 3), tags=(TAG,)
        )

        # Anchor dot (open circle)
        r = 5
        self.create_oval(
            cax - r,
            cay - r,
            cax + r,
            cay + r,
            outline="#00d8ff",
            fill="#001522",
            width=2,
            tags=(TAG,),
        )
        # Crosshair tick lines at anchor
        self.create_line(
            cax - 8, cay, cax + 8, cay, fill="#00d8ff", width=1, tags=(TAG,)
        )
        self.create_line(
            cax, cay - 8, cax, cay + 8, fill="#00d8ff", width=1, tags=(TAG,)
        )

        # Hover dot (filled)
        self.create_oval(
            chx - 3,
            chy - 3,
            chx + 3,
            chy + 3,
            outline="#00d8ff",
            fill="#00d8ff",
            tags=(TAG,),
        )

        # Distance badge at midpoint
        mx, my = (cax + chx) / 2, (cay + chy) / 2
        line1 = f"{dist:.2f} mm"
        line2 = f"\u0394x {dx:.2f}  \u0394y {dy:.2f}"
        pad_x, pad_y = 8, 4
        # Slightly offset so badge doesn't overlap the line
        badge_y = my - 28
        self.create_rectangle(
            mx - 80,
            badge_y - 10 - pad_y,
            mx + 80,
            badge_y + 14 + pad_y,
            fill="#001522",
            outline="#00d8ff",
            width=1,
            tags=(TAG,),
        )
        self.create_text(
            mx,
            badge_y - 6,
            text=line1,
            fill="#ffffff",
            font=("Helvetica", 11, "bold"),
            anchor="center",
            tags=(TAG,),
        )
        self.create_text(
            mx,
            badge_y + 8,
            text=line2,
            fill="#00d8ff",
            font=("Helvetica", 9),
            anchor="center",
            tags=(TAG,),
        )

    def _lmb_press_cb(self, ev: tk.Event) -> None:
        # Measure button hit-test (always, regardless of mode)
        if self._hit_measure_button(ev.x, ev.y):
            self.toggle_measure()
            return
        # Measure anchor placement
        if self._measure_mode:
            wx, wy = self._c2w(ev.x, ev.y)
            self._measure_anchor = (wx, wy)
            self._measure_hover = (wx, wy)
            self._draw()
            return
        shift = bool(ev.state & 0x0001)
        if self._selectable and shift:
            # Shift+drag = rubber-band rectangle select
            self._shift_drag = True
            self._band_start = (ev.x, ev.y)
            self._lmb_press = None
            self._lmb_prev = None
            self._lmb_target = None
        else:
            self._shift_drag = False
            self._band_start = None
            self._lmb_press = (ev.x, ev.y)
            self._lmb_prev = (ev.x, ev.y)
            nearby = self.find_closest(ev.x, ev.y, halo=6)
            self._lmb_target = self._id2idx.get(nearby[0]) if nearby else None

    def _lmb_drag_cb(self, ev: tk.Event) -> None:
        if self._measure_mode:
            return  # no pan or rubber-band in measure mode
        if self._shift_drag and self._band_start:
            # Draw rubber-band rectangle without full redraw cost
            self._draw()
            bx1, by1 = self._band_start
            self.create_rectangle(
                bx1,
                by1,
                ev.x,
                ev.y,
                outline="#ff8800",
                fill="",
                dash=(4, 2),
                tags=("rubberband",),
            )
            return
        if self._lmb_prev:
            self._ox += ev.x - self._lmb_prev[0]
            self._oy += ev.y - self._lmb_prev[1]
            self._lmb_prev = (ev.x, ev.y)
            self._draw()

    def _lmb_release_cb(self, ev: tk.Event) -> None:
        if self._measure_mode:
            return  # all release actions are suppressed in measure mode
        if self._shift_drag and self._band_start and self._selectable:
            bx1, by1 = self._band_start
            x1c, x2c = min(bx1, ev.x), max(bx1, ev.x)
            y1c, y2c = min(by1, ev.y), max(by1, ev.y)
            for idx, poly in enumerate(self._polys):
                pts_c = [self._w2c(x, y) for x, y in poly]
                if any(x1c <= cx <= x2c and y1c <= cy <= y2c for cx, cy in pts_c):
                    self._sel.add(idx)
            self._draw()
            self._notify()
            self._shift_drag = False
            self._band_start = None
            return
        if (
            self._selectable
            and self._lmb_press is not None
            and self._lmb_target is not None
        ):
            dx = ev.x - self._lmb_press[0]
            dy = ev.y - self._lmb_press[1]
            if abs(dx) <= _DRAG_THRESH and abs(dy) <= _DRAG_THRESH:
                idx = self._lmb_target
                self._sel.discard(idx) if idx in self._sel else self._sel.add(idx)
                self._draw()
                self._notify()
        self._lmb_press = None
        self._lmb_prev = None
        self._lmb_target = None
        self._shift_drag = False
        self._band_start = None

    def _mmb_drag_cb(self, ev: tk.Event) -> None:
        if self._mmb_prev:
            self._ox += ev.x - self._mmb_prev[0]
            self._oy += ev.y - self._mmb_prev[1]
            self._mmb_prev = (ev.x, ev.y)
            self._draw()

    def _scroll_cb(self, ev: tk.Event) -> None:
        factor = 1.15 if (ev.num == 4 or getattr(ev, "delta", 0) > 0) else 1 / 1.15
        wx, wy = self._c2w(ev.x, ev.y)
        self._scale *= factor
        self._ox = ev.x - wx * self._scale
        self._oy = ev.y + wy * self._scale
        self._draw()

    def _zoom_by(self, factor: float) -> None:
        w, h = max(self.winfo_width(), 100), max(self.winfo_height(), 100)
        cx, cy = w / 2, h / 2
        wx, wy = self._c2w(cx, cy)
        self._scale *= factor
        self._ox = cx - wx * self._scale
        self._oy = cy + wy * self._scale
        self._draw()

    def _motion_cb(self, ev: tk.Event) -> None:
        wx, wy = self._c2w(ev.x, ev.y)
        self._cursor_wx = wx
        self._cursor_wy = wy
        h = max(self.winfo_height(), 100)
        w = max(self.winfo_width(), 100)
        if self._measure_mode and self._measure_anchor is not None:
            # Lightweight: only redraw the measure overlay + cursor pos
            self._measure_hover = (wx, wy)
            self.delete("measure_overlay")
            self.delete("cursor_pos")
            self._draw_measure_overlay()
            self.create_text(
                w - 6,
                h - 6,
                anchor="se",
                text=f"{wx:.2f}, {wy:.2f} mm",
                fill=_DIM,
                font=("Helvetica", 10),
                tags=("cursor_pos",),
            )
            return
        # Default lightweight update: only refresh the coordinate overlay
        self.delete("cursor_pos")
        self.create_text(
            w - 6,
            h - 6,
            anchor="se",
            text=f"{wx:.2f}, {wy:.2f} mm",
            fill=_DIM,
            font=("Helvetica", 10),
            tags=("cursor_pos",),
        )

    def _rightclick_cb(self, ev: tk.Event) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Select All  [Shift+drag]", command=self.select_all)
        menu.add_command(label="Deselect All  [Esc]", command=self.deselect_all)
        menu.add_command(label="Invert Selection", command=self.invert_selection)
        if self._undo_stack:
            menu.add_separator()
            menu.add_command(label="Undo Last Delete", command=self.undo_delete)
        if self._sel:
            menu.add_separator()
            menu.add_command(
                label=f"Delete {len(self._sel)} selected  [Del]",
                command=self.delete_selected,
            )
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            menu.grab_release()
        self._draw()

    def _notify(self) -> None:
        if self._on_change:
            self._on_change(self.sel_count)


# ─────────────────────────────────────────────────────────────────────────────
# Small layout helpers
# ─────────────────────────────────────────────────────────────────────────────


def _row(parent, **kw) -> ctk.CTkFrame:
    kw.setdefault("fg_color", "transparent")
    f = ctk.CTkFrame(parent, **kw)
    f.pack(fill="x")
    return f


def _label(parent, text: str, **kw) -> ctk.CTkLabel:
    # Route pack-only kwargs away from CTkLabel constructor
    pady = kw.pop("pady", 0)
    pack_padx = kw.pop("padx", 8)
    kw.setdefault("anchor", "w")
    lb = ctk.CTkLabel(parent, text=text, **kw)
    lb.pack(anchor="w", padx=pack_padx, pady=pady)
    return lb


def _entry(
    parent, default: str = "", placeholder: str = "", width: int = 120
) -> ctk.CTkEntry:
    var = ctk.StringVar(value=default)
    e = ctk.CTkEntry(
        parent, textvariable=var, placeholder_text=placeholder, width=width
    )
    e.pack(side="left", padx=(0, 6))
    return e


def _sep(parent) -> None:
    ctk.CTkFrame(parent, height=1, fg_color="#2a2a4a").pack(fill="x", padx=8, pady=6)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 · FVI → DXF
# ─────────────────────────────────────────────────────────────────────────────


class FviTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict | None = None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings: dict = settings or {}

        # ── Mode ──────────────────────────────────────────────────────────────
        mode_row = ctk.CTkFrame(self, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(mode_row, text="Mode:", anchor="w").pack(side="left", padx=(0, 10))
        self._mode = ctk.StringVar(value="Single file")
        ctk.CTkSegmentedButton(
            mode_row,
            values=["Single file", "Folder (batch)"],
            variable=self._mode,
        ).pack(side="left")

        # ── Source ────────────────────────────────────────────────────────────
        src_card = ctk.CTkFrame(self)
        src_card.pack(fill="x", padx=16, pady=4)
        _label(src_card, "Source", pady=(8, 2))
        src_row = ctk.CTkFrame(src_card, fg_color="transparent")
        src_row.pack(fill="x", padx=8, pady=(0, 8))
        self._src_var = ctk.StringVar()
        ctk.CTkEntry(
            src_row,
            textvariable=self._src_var,
            placeholder_text="Select a .fvi file or folder…",
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(src_row, text="Browse", width=80, command=self._browse_src).pack(
            side="right"
        )

        # ── Output ────────────────────────────────────────────────────────────
        out_card = ctk.CTkFrame(self)
        out_card.pack(fill="x", padx=16, pady=4)
        _label(out_card, "Output folder  (blank = same as source)", pady=(8, 2))
        out_row = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=8, pady=(0, 8))
        self._out_var = ctk.StringVar()
        ctk.CTkEntry(
            out_row,
            textvariable=self._out_var,
            placeholder_text="Optional output folder…",
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(out_row, text="Browse", width=80, command=self._browse_out).pack(
            side="right"
        )

        # ── Convert button ────────────────────────────────────────────────────
        self._btn = ctk.CTkButton(self, text="Convert", height=38, command=self._run)
        self._btn.pack(padx=16, pady=(10, 4))

        # ── Log ───────────────────────────────────────────────────────────────
        _label(self, "Log")
        self._log = ctk.CTkTextbox(
            self, state="disabled", height=260, font=("Courier", 12)
        )
        self._log.pack(fill="both", expand=True, padx=16, pady=(2, 16))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse_src(self) -> None:
        idir = self._settings.get("fvi_source_dir", "")
        if self._mode.get() == "Single file":
            path = filedialog.askopenfilename(
                title="Select FVI file",
                initialdir=idir or None,
                filetypes=[("FVI files", "*.fvi *.Fvi *.FVI"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askdirectory(
                title="Select folder containing FVI files",
                initialdir=idir or None,
            )
        if path:
            self._src_var.set(path)

    def _browse_out(self) -> None:
        idir = self._settings.get("fvi_output_dir", "")
        path = filedialog.askdirectory(
            title="Select output folder",
            initialdir=idir or None,
        )
        if path:
            self._out_var.set(path)

    def _log_write(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _log_clear(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_output_dir(self, d: str) -> None:
        self._last_out_dir = d
        self._open_folder_btn.configure(state="normal")

    def _open_output_folder(self) -> None:
        if self._last_out_dir:
            subprocess.run(["open", self._last_out_dir])

    def _run(self) -> None:
        src = self._src_var.get().strip()
        if not src:
            messagebox.showerror("Error", "Please select a source file or folder.")
            return
        self._btn.configure(state="disabled")
        self._log_clear()
        out_dir = self._out_var.get().strip() or None
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
            self.after(0, self._log_write, "No .fvi files found.")
            self.after(0, lambda: self._btn.configure(state="normal"))
            return

        self.after(0, self._log_write, f"Found {len(files)} file(s)\n")
        ok = err = 0
        for fvi in files:
            dest_dir = Path(out_dir) if out_dir else fvi.parent
            dest = dest_dir / fvi.with_suffix(".dxf").name
            try:
                convert_fvi_to_dxf(fvi, dest)
                self.after(0, self._log_write, f"  ✓  {fvi.name}  →  {dest.name}")
                ok += 1
            except Exception as exc:
                self.after(0, self._log_write, f"  ✗  {fvi.name}: {exc}")
                err += 1

        summary = f"\nDone — {ok} converted, {err} error(s)."
        self.after(0, self._log_write, summary)
        self.after(0, lambda: self._btn.configure(state="normal"))
        if files:
            final_dir = out_dir or str(files[0].parent)
            self.after(0, lambda d=final_dir: self._set_output_dir(d))


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 · Pattern Generator
# ─────────────────────────────────────────────────────────────────────────────

_PATTERNS = [
    "Honeycomb",
    "Gradient Honeycomb",
    "Diamond Checkering",
    "Fish Scale",
    "Stipple Dots",
    "Custom Tile",
    "Image Halftone",
]


class PatternTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict | None = None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings: dict = settings or {}

        # Runtime state
        self._orig_polys: list[list[tuple[float, float]]] = []
        self._orig_w: float = 0.0  # bounding-box width of loaded DXF (mm)
        self._orig_h: float = 0.0  # bounding-box height
        self._ar_locked: bool = True  # aspect-ratio lock state
        self._updating_dims: bool = False  # re-entrance guard

        # Two-column layout
        left = ctk.CTkFrame(self, width=310)
        left.pack(side="left", fill="y", padx=(10, 4), pady=10)
        left.pack_propagate(False)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        self._build_left(left)
        self._build_right(right)

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        # ── DXF file ──────────────────────────────────────────────────────────
        ctk.CTkLabel(
            parent,
            text="Outline DXF",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(12, 0))

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

        _sep(parent)

        # ── Dimensions & Scale ────────────────────────────────────────────────
        ctk.CTkLabel(
            parent,
            text="Dimensions & Scale",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(0, 2))

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

        ctk.CTkLabel(dims_g, text="Height (mm)", anchor="w", width=90).grid(
            row=1, column=0, padx=6, pady=2, sticky="w"
        )
        self._scale_h = ctk.CTkEntry(dims_g, width=80, placeholder_text="auto")
        self._scale_h.grid(row=1, column=1, padx=4, pady=2)
        self._scale_h.bind("<KeyRelease>", self._on_scale_h_changed)

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

        _sep(parent)

        # ── Polyline Editor ───────────────────────────────────────────────────
        ctk.CTkLabel(
            parent,
            text="Polyline Editor",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(0, 4))

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

        _sep(parent)

        # ── Pattern selector ─────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="Pattern", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).pack(anchor="w", padx=10, pady=(0, 4))
        self._pattern_var = ctk.StringVar(value="Honeycomb")
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
        self._switch_pattern("Honeycomb")

        _sep(parent)

        # ── Generate ──────────────────────────────────────────────────────────
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
        ctk.CTkLabel(g, text="Gap (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._hex_gap = ctk.CTkEntry(g, width=80)
        self._hex_gap.insert(0, "0.5")
        self._hex_gap.grid(row=1, column=1, padx=4, pady=3)
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
        ctk.CTkLabel(g, text="Angle (°)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._check_angle = ctk.CTkEntry(g, width=80)
        self._check_angle.insert(0, "45")
        self._check_angle.grid(row=1, column=1, padx=4, pady=3)
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
        ctk.CTkLabel(g, text="Scale height (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._fish_h = ctk.CTkEntry(g, width=80)
        self._fish_h.insert(0, "2.0")
        self._fish_h.grid(row=1, column=1, padx=4, pady=3)
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
        ctk.CTkLabel(g, text="Spacing (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._stip_spacing = ctk.CTkEntry(g, width=80)
        self._stip_spacing.insert(0, "1.2")
        self._stip_spacing.grid(row=1, column=1, padx=4, pady=3)
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
        ctk.CTkLabel(g, text="Max size (mm)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._grad_r_max = ctk.CTkEntry(g, width=80)
        self._grad_r_max.insert(0, "2.5")
        self._grad_r_max.grid(row=1, column=1, padx=4, pady=3)
        ctk.CTkLabel(g, text="Gap (mm)", anchor="w", width=145).grid(
            row=2, column=0, padx=6, pady=3, sticky="w"
        )
        self._grad_gap = ctk.CTkEntry(g, width=80)
        self._grad_gap.insert(0, "0.5")
        self._grad_gap.grid(row=2, column=1, padx=4, pady=3)
        ctk.CTkLabel(g, text="Direction (°)", anchor="w", width=145).grid(
            row=3, column=0, padx=6, pady=3, sticky="w"
        )
        self._grad_angle = ctk.CTkEntry(g, width=80)
        self._grad_angle.insert(0, "0")
        self._grad_angle.grid(row=3, column=1, padx=4, pady=3)
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
        ctk.CTkLabel(g, text="Tile rotation (°)", anchor="w", width=145).grid(
            row=1, column=0, padx=6, pady=3, sticky="w"
        )
        self._tile_angle = ctk.CTkEntry(g, width=80)
        self._tile_angle.insert(0, "0")
        self._tile_angle.grid(row=1, column=1, padx=4, pady=3)
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
        ctk.CTkLabel(g, text="Grid spacing (mm)", anchor="w", width=145).grid(
            row=2, column=0, padx=6, pady=3, sticky="w"
        )
        self._htone_spacing = ctk.CTkEntry(g, width=80)
        self._htone_spacing.insert(0, "2.2")
        self._htone_spacing.grid(row=2, column=1, padx=4, pady=3)
        self._htone_invert = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            f,
            text="Invert  (dark → small cells)",
            variable=self._htone_invert,
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
        {
            "Honeycomb": self._honeycomb_frame,
            "Gradient Honeycomb": self._gradient_frame,
            "Diamond Checkering": self._checkering_frame,
            "Fish Scale": self._fishscale_frame,
            "Stipple Dots": self._stipple_frame,
            "Custom Tile": self._custom_tile_frame,
            "Image Halftone": self._halftone_frame,
        }.get(value, self._honeycomb_frame).pack(fill="x", padx=4)

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
        hint = ctk.CTkLabel(
            parent,
            text="Click to select · Shift+drag = rubber-band · drag to pan · scroll/+- to zoom · Del=delete · Esc=deselect · F=fit · right-click for menu",
            text_color=_DIM,
            font=("Helvetica", 11),
            wraplength=580,
        )
        hint.pack(anchor="w", padx=4, pady=(0, 4))
        self._canvas = DxfCanvas(
            parent,
            selectable=True,
            on_change=self._on_sel_change,
        )
        self._canvas.pack(fill="both", expand=True)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_sel_change(self, count: int) -> None:
        self._sel_label.configure(
            text=f"{count} selected" if count else "0 selected",
            text_color=_SEL if count else _DIM,
        )

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
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def _delete_selected(self) -> None:
        n = self._canvas.delete_selected()
        if n:
            self._set_status(f"Deleted {n} polyline(s). Use ↩ Undo to restore.")

    def _undo_delete(self) -> None:
        if not self._canvas.undo_delete():
            self._set_status("Nothing to undo.")
        else:
            self._set_status("Undo: polylines restored.")

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

    def _set_status(self, text: str, color: str = _DIM) -> None:
        self._status.configure(text=text, text_color=color)

    def _generate(self) -> None:
        active = self._canvas.get_active()
        if not active:
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
            target=self._run_generate, args=(active, out_path), daemon=True
        ).start()

    def _run_generate(
        self, active: list[list[tuple[float, float]]], out_path: str
    ) -> None:
        try:
            scaled = self._get_scaled_polys(active)
            outline = polylines_to_outline(scaled)
            pattern = self._pattern_var.get()

            if pattern == "Honeycomb":
                r = float(self._hex_r.get())
                gap = float(self._hex_gap.get())
                polys = gen_honeycomb(outline, r, gap)
                write_polylines_dxf(polys, out_path, close=True)
            elif pattern == "Diamond Checkering":
                spacing = float(self._check_spacing.get())
                angle = float(self._check_angle.get())
                polys = gen_diamond_checkering(outline, spacing, angle)
                write_polylines_dxf(polys, out_path, close=False)
            elif pattern == "Fish Scale":
                sw = float(self._fish_w.get())
                sh = float(self._fish_h.get())
                polys = gen_fish_scale(outline, sw, sh)
                write_polylines_dxf(polys, out_path, close=False)
            elif pattern == "Stipple Dots":
                r = float(self._stip_r.get())
                spacing = float(self._stip_spacing.get())
                polys = gen_stipple_dots(outline, r, spacing)
                write_polylines_dxf(polys, out_path, close=True)
            elif pattern == "Gradient Honeycomb":
                r_min = float(self._grad_r_min.get())
                r_max = float(self._grad_r_max.get())
                gap = float(self._grad_gap.get())
                angle = float(self._grad_angle.get())
                polys = gen_gradient_honeycomb(outline, r_min, r_max, gap, angle)
                write_polylines_dxf(polys, out_path, close=True)
            elif pattern == "Custom Tile":
                tile_path = self._tile_path_var.get().strip()
                if not tile_path:
                    raise ValueError("No tile DXF selected. Use Browse to pick one.")
                tile_polys = load_dxf_polylines(tile_path)
                gap = float(self._tile_gap.get())
                angle = float(self._tile_angle.get())
                polys = gen_custom_tile(outline, tile_polys, gap, angle)
                write_polylines_dxf(polys, out_path, close=True)
            else:  # Image Halftone
                img_path = self._htone_img_var.get().strip()
                if not img_path:
                    raise ValueError("No image selected. Use Browse to pick one.")
                r_min = float(self._htone_r_min.get())
                r_max = float(self._htone_r_max.get())
                spacing = float(self._htone_spacing.get())
                invert = bool(self._htone_invert.get())
                polys = gen_image_halftone(
                    outline, img_path, r_min, r_max, spacing, invert
                )
                write_polylines_dxf(polys, out_path, close=True)

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
                # Show result in canvas
                self._canvas.load(polys)

            self.after(0, _done)

        except Exception as exc:

            def _err():
                self._progress.stop()
                self._progress.configure(mode="determinate")
                self._progress.set(0)
                self._gen_btn.configure(state="normal")
                self._set_status(f"Error: {exec}", "#e06060")

            self.after(0, _err)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 · Shape Creator
# ─────────────────────────────────────────────────────────────────────────────

_SHAPES = ["Rectangle", "Circle", "Ellipse", "Regular Polygon"]


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
        ctk.CTkLabel(
            parent, text="Shape", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).pack(anchor="w", padx=10, pady=(12, 6))

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

        _sep(parent)

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
        ctk.CTkLabel(
            parent,
            text="Preview  (scroll to zoom · drag to pan)",
            text_color=_DIM,
            font=("Helvetica", 11),
        ).pack(anchor="w", padx=4, pady=(0, 4))
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


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4 · Repository
# ─────────────────────────────────────────────────────────────────────────────


class RepoTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings = settings
        self._build()

    def _build(self) -> None:
        left = ctk.CTkFrame(self, width=300)
        left.pack(side="left", fill="y", padx=(10, 4), pady=10)
        left.pack_propagate(False)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Repository",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(12, 4))

        ctk.CTkLabel(parent, text="Local path", anchor="w", text_color=_DIM).pack(
            anchor="w", padx=10
        )
        path_row = ctk.CTkFrame(parent, fg_color="transparent")
        path_row.pack(fill="x", padx=8, pady=(2, 4))
        self._repo_path = ctk.CTkEntry(path_row, placeholder_text="Path to repo…")
        self._repo_path.insert(0, self._settings.get("repo_path", ""))
        self._repo_path.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            path_row, text="…", width=28, height=28, command=self._browse_repo
        ).pack(side="right")

        ctk.CTkLabel(parent, text="Remote URL", anchor="w", text_color=_DIM).pack(
            anchor="w", padx=10
        )
        self._remote_url = ctk.CTkEntry(parent, placeholder_text="https://github.com/…")
        self._remote_url.insert(0, self._settings.get("repo_remote", ""))
        self._remote_url.pack(fill="x", padx=8, pady=(2, 4))

        _sep(parent)
        self._branch_label = ctk.CTkLabel(parent, text="—", anchor="w", text_color=_DIM)
        self._branch_label.pack(anchor="w", padx=10)
        self._commit_label = ctk.CTkLabel(
            parent,
            text="",
            anchor="w",
            text_color=_DIM,
            wraplength=270,
            font=("Helvetica", 11),
        )
        self._commit_label.pack(anchor="w", padx=10, pady=(2, 0))
        ctk.CTkButton(
            parent,
            text="↺  Refresh status",
            height=28,
            fg_color="transparent",
            border_width=1,
            command=self._refresh_status,
        ).pack(fill="x", padx=8, pady=(6, 0))

        _sep(parent)

        ctk.CTkLabel(
            parent, text="Sync", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).pack(anchor="w", padx=10, pady=(0, 4))
        self._pull_btn = ctk.CTkButton(
            parent, text="⬇  Pull", height=34, command=self._pull
        )
        self._pull_btn.pack(fill="x", padx=8, pady=(0, 6))

        _sep(parent)

        ctk.CTkLabel(
            parent,
            text="Commit & Push",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(0, 4))
        ctk.CTkLabel(parent, text="Commit message", anchor="w", text_color=_DIM).pack(
            anchor="w", padx=10
        )
        self._commit_msg = ctk.CTkEntry(parent, placeholder_text="Update patterns…")
        self._commit_msg.pack(fill="x", padx=8, pady=(2, 6))
        self._push_btn = ctk.CTkButton(
            parent,
            text="⬆  Commit & Push",
            height=34,
            fg_color="#1a5c1a",
            hover_color="#227722",
            command=self._push,
        )
        self._push_btn.pack(fill="x", padx=8, pady=(0, 6))

    def _build_right(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Git output",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=4, pady=(0, 4))
        self._log = ctk.CTkTextbox(parent, font=("Menlo", 11), state="disabled")
        self._log.pack(fill="both", expand=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _repo_dir(self) -> str | None:
        d = self._repo_path.get().strip()
        return d if d else None

    def _browse_repo(self) -> None:
        d = filedialog.askdirectory(title="Select local repository folder")
        if d:
            self._repo_path.delete(0, "end")
            self._repo_path.insert(0, d)
            self._settings["repo_path"] = d
            save_settings(self._settings)

    def _git(self, *args: str) -> tuple[int, str]:
        repo = self._repo_dir()
        if not repo:
            return 1, "No repository path set."
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = (result.stdout + result.stderr).strip()
            return result.returncode, out
        except FileNotFoundError:
            return 1, "git not found — is git installed and in PATH?"
        except subprocess.TimeoutExpired:
            return 1, "git command timed out."

    def _log_write(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _log_clear(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_btns(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._pull_btn.configure(state=state)
        self._push_btn.configure(state=state)

    # ── Status ────────────────────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        rc, branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0:
            self._branch_label.configure(text=f"Branch: {branch}", text_color="#60c060")
        else:
            self._branch_label.configure(text="Not a git repo", text_color="#e06060")
            self._commit_label.configure(text="")
            return
        rc2, log = self._git("log", "--oneline", "-1")
        if rc2 == 0:
            self._commit_label.configure(text=log, text_color=_DIM)

    # ── Pull ──────────────────────────────────────────────────────────────────

    def _pull(self) -> None:
        self._set_btns(False)
        self._log_clear()
        threading.Thread(target=self._run_pull, daemon=True).start()

    def _run_pull(self) -> None:
        self.after(0, self._log_write, "$ git pull")
        rc, out = self._git("pull")
        self.after(0, self._log_write, out)
        if rc == 0:
            self.after(0, self._refresh_status)
        self.after(0, self._set_btns, True)

    # ── Push ──────────────────────────────────────────────────────────────────

    def _push(self) -> None:
        msg = self._commit_msg.get().strip() or "app commit"
        self._set_btns(False)
        self._log_clear()
        threading.Thread(target=self._run_push, args=(msg,), daemon=True).start()

    def _run_push(self, msg: str) -> None:
        self.after(0, self._log_write, "$ git add -A")
        rc, out = self._git("add", "-A")
        if out:
            self.after(0, self._log_write, out)

        self.after(0, self._log_write, f'$ git commit -m "{msg}"')
        rc, out = self._git("commit", "-m", msg)
        self.after(0, self._log_write, out)
        if rc != 0 and "nothing to commit" not in out:
            self.after(0, self._set_btns, True)
            return

        self.after(0, self._log_write, "$ git push")
        rc, out = self._git("push")
        self.after(0, self._log_write, out)
        if rc == 0:
            self.after(0, self._refresh_status)
            self.after(0, lambda: self._commit_msg.delete(0, "end"))
        self.after(0, self._set_btns, True)

    # ── Auto-pull on startup ──────────────────────────────────────────────────

    def auto_pull(self) -> None:
        """Called by App on startup. Only pulls if a repo path is configured."""
        if not self._repo_dir():
            return
        self._refresh_status()
        rc, remote = self._git("remote")
        if rc == 0 and remote.strip():
            threading.Thread(target=self._run_pull, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Settings dialog
# ─────────────────────────────────────────────────────────────────────────────


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
            title=f"Select folder",
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


# ─────────────────────────────────────────────────────────────────────────────
# Main application window
# ─────────────────────────────────────────────────────────────────────────────


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AA Laser Studio")
        self.geometry("1100x740")
        self.minsize(860, 580)

        self._settings = load_settings()

        # ── Header bar ────────────────────────────────────────────────────────
        header = ctk.CTkFrame(
            self, height=42, corner_radius=0, fg_color=("#0d1b3e", "#0a0e1e")
        )
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="AA Laser Studio",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#8ab4f8",
        ).pack(side="left", padx=14)

        ctk.CTkButton(
            header,
            text="⚙",
            width=34,
            height=28,
            font=ctk.CTkFont(size=14),
            fg_color="transparent",
            hover_color=("#1c2e5e", "#1a203a"),
            command=self._open_settings,
        ).pack(side="right", padx=10)

        # ── Tabs ──────────────────────────────────────────────────────────────
        tabs = ctk.CTkTabview(self, anchor="nw")
        tabs.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        tabs.add("FVI → DXF")
        tabs.add("Pattern Generator")
        tabs.add("Shape Creator")
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
        self._repo_tab = RepoTab(tabs.tab("Repository"), settings=self._settings)
        self._repo_tab.pack(fill="both", expand=True)

        # ── Status bar ────────────────────────────────────────────────────────
        statusbar = ctk.CTkFrame(
            self, height=22, corner_radius=0, fg_color=("#0d1b3e", "#0a0e1e")
        )
        statusbar.pack(fill="x", side="bottom")
        statusbar.pack_propagate(False)
        self._status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(
            statusbar,
            textvariable=self._status_var,
            text_color=_DIM,
            font=("Helvetica", 11),
            anchor="w",
        ).pack(side="left", padx=10)

        # ── Keyboard shortcuts ────────────────────────────────────────────────
        self.bind_all("<Command-comma>", lambda _: self._open_settings())

        # ── Auto-pull on open ─────────────────────────────────────────────────
        self.after(800, self._repo_tab.auto_pull)

    def _open_settings(self) -> None:
        SettingsDialog(self, self._settings)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    App().mainloop()
