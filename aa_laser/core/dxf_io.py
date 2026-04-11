"""DXF I/O helpers — read and write LWPOLYLINE entities."""

from __future__ import annotations

import ezdxf  # type: ignore[attr-defined]
from shapely.geometry import Polygon  # type: ignore[import-untyped]
from shapely.ops import unary_union  # type: ignore[import-untyped]


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
