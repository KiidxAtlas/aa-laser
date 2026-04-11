"""Pattern generators — return lists of polyline coord-lists.

Each generator clips its output to the provided Shapely outline polygon.
"""

from __future__ import annotations

import math

from shapely import prepared  # type: ignore[import-untyped]
from shapely.geometry import (  # type: ignore[import-untyped]
    LineString,
    MultiPolygon,
    Polygon,
)

try:
    from PIL import Image as _PIL_Image  # type: ignore[import-untyped]

    _PIL_OK = True
except ImportError:
    _PIL_OK = False


# ── Internal helpers ──────────────────────────────────────────────────────────


def _hex_verts(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    return [
        (
            cx + r * math.cos(math.pi / 6 + i * math.pi / 3),
            cy + r * math.sin(math.pi / 6 + i * math.pi / 3),
        )
        for i in range(6)
    ]


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


# ── Public generators ─────────────────────────────────────────────────────────


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
