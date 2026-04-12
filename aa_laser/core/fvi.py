"""FVI → DXF conversion."""

from __future__ import annotations

import math
import re
from pathlib import Path

import ezdxf  # type: ignore[attr-defined]

_FVI_SCALE = 0.254  # FVI units → mm
_ARC_STEPS = 32  # tessellation segments per full circle (scales with arc angle)


def _arc_pts(
    x: float,
    y: float,
    ex: float,
    ey: float,
    cx: float,
    cy: float,
) -> list[tuple[float, float]]:
    """Tessellate a DRAWARC into line pts (excluding the start point).

    All args are in FVI units (pre-scale).
    ex, ey = endpoint delta from (x, y)
    cx, cy = center offset from (x, y)
    Returns a list of (world_x, world_y) points in mm, start-exclusive.
    """
    # Absolute world coords
    sx, sy = x, y
    px, py = x + cx, y + cy  # arc center
    endx, endy = x + ex, y + ey  # arc endpoint

    r = math.hypot(sx - px, sy - py)
    if r < 1e-9:
        return [(endx * _FVI_SCALE, endy * _FVI_SCALE)]

    ang_start = math.atan2(sy - py, sx - px)
    ang_end = math.atan2(endy - py, endx - px)

    # Choose sweep direction: pick the shorter arc (CCW or CW).
    # FVI arcs use the sign of the cross-product to determine winding.
    # Cross product of (start→end) × (start→center) gives winding.
    cross = (ex) * (cy) - (ey) * (cx)
    # cross > 0 → CCW, cross < 0 → CW
    if cross >= 0:
        # CCW
        sweep = ang_end - ang_start
        if sweep < 0:
            sweep += 2 * math.pi
    else:
        # CW
        sweep = ang_end - ang_start
        if sweep > 0:
            sweep -= 2 * math.pi

    n = max(2, int(abs(sweep) / (2 * math.pi) * _ARC_STEPS + 0.5))
    result: list[tuple[float, float]] = []
    for i in range(1, n + 1):
        a = ang_start + sweep * i / n
        wx = (px + r * math.cos(a)) * _FVI_SCALE
        wy = (py + r * math.sin(a)) * _FVI_SCALE
        result.append((wx, wy))
    return result


def convert_fvi_to_dxf(src: Path, dst: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    x = y = 0.0
    pts: list[tuple[float, float]] = []

    _CLOSE_TOL_FVI = 1.0  # mm — treat shape as closed if start≈end within this

    def _flush() -> None:
        if len(pts) < 2:
            return
        p0, p1 = pts[0], pts[-1]
        is_closed = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < _CLOSE_TOL_FVI
        if is_closed:
            # Drop the duplicate closing point and set the DXF close flag
            msp.add_lwpolyline(pts[:-1], close=True)
        else:
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
                continue
            m = re.match(r"DRAWARC\s+([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", ln)
            if m:
                ex = float(m.group(1))
                ey = float(m.group(2))
                cx = float(m.group(3))
                cy = float(m.group(4))
                arc_pts = _arc_pts(x, y, ex, ey, cx, cy)
                pts.extend(arc_pts)
                x += ex
                y += ey
    _flush()
    doc.saveas(str(dst))
