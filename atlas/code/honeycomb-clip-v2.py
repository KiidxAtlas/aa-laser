import math
import sys

import ezdxf  # type: ignore[attr-defined]
from shapely.geometry import MultiPolygon, Polygon  # type: ignore[import-untyped]
from shapely.ops import unary_union  # type: ignore[import-untyped]

# ── Settings ──────────────────────────────────────────
R = 1.75  # hex side length in mm
gap = 0.5  # wall-to-wall gap in mm
output = "honeycomb_clipped.dxf"
# ──────────────────────────────────────────────────────


def hex_verts(cx, cy, r):
    pts = []
    for i in range(6):
        angle = math.pi / 6 + i * math.pi / 3
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def load_outline(dxf_path):
    doc = ezdxf.readfile(dxf_path)  # type: ignore[attr-defined]
    msp = doc.modelspace()
    all_coords = []

    for entity in msp:
        if entity.dxftype() == "LWPOLYLINE":
            pts = list(entity.get_points())  # type: ignore[attr-defined]
            coords = [(p[0], p[1]) for p in pts]
            if len(coords) >= 3:
                all_coords.append(coords)
        elif entity.dxftype() == "LINE":
            pass  # lines handled below

    if not all_coords:
        raise ValueError(
            "No polylines found in outline DXF. Make sure it was converted with the updated fvi_to_dxf.py."
        )

    # Build shapely polygons from each polyline, take the union
    polys = []
    for coords in all_coords:
        try:
            p = Polygon(coords)
            if p.is_valid and p.area > 0:
                polys.append(p)
        except (ValueError, TypeError):
            continue

    if not polys:
        # fallback: treat all coords as one big polygon
        flat = [pt for coords in all_coords for pt in coords]
        return Polygon(flat).convex_hull

    if len(polys) == 1:
        return polys[0]

    # Try union, fall back to convex hull of largest
    result = unary_union(polys)
    if result.is_empty:
        return max(polys, key=lambda p: p.area).convex_hull
    return result


def generate_clipped_honeycomb(outline_poly, r, gap, out_path):
    apothem = math.sqrt(3) / 2 * r
    c2c = 2 * apothem + gap
    col_step = c2c
    row_step = c2c * math.sqrt(3) / 2  # actually use proper hex row spacing
    row_step = (3 / 2) * r + gap * math.sqrt(3) / 2

    # Bounding box of outline
    minx, miny, maxx, maxy = outline_poly.bounds

    # Add padding so edge hexagons get included
    pad = r * 2
    cols = int((maxx - minx + pad * 2) / col_step) + 2
    rows = int((maxy - miny + pad * 2) / row_step) + 2

    doc = ezdxf.new("R2010")  # type: ignore[attr-defined]
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()

    count = 0
    for row in range(rows):
        for col in range(cols):
            offset_x = col_step / 2 if row % 2 == 1 else 0
            cx = minx - pad + col * col_step + offset_x
            cy = miny - pad + row * row_step

            verts = hex_verts(cx, cy, r)
            hex_poly = Polygon(verts)

            if not outline_poly.intersects(hex_poly):
                continue

            clipped = outline_poly.intersection(hex_poly)

            if clipped.is_empty:
                continue

            # Extract and draw all rings from the clipped result
            geoms = []
            if isinstance(clipped, Polygon):
                geoms = [clipped]
            elif isinstance(clipped, MultiPolygon):
                geoms = list(clipped.geoms)
            else:
                # LineString or other — draw as-is
                try:
                    coords = list(clipped.coords)
                    if len(coords) >= 2:
                        msp.add_lwpolyline(coords)
                        count += 1
                except (ValueError, AttributeError):
                    continue
                continue

            for geom in geoms:
                if geom.is_empty or geom.area < 0.001:
                    continue
                geom = geom.simplify(0.01, preserve_topology=True)
                coords = [(round(x, 3), round(y, 3)) for x, y in geom.exterior.coords]  # type: ignore[attr-defined]
                if len(coords) >= 2:
                    msp.add_lwpolyline(coords, close=True)
                    count += 1

    doc.saveas(out_path)
    print(f"Done — {count} hexagon shapes written to {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python honeycomb_clip.py outline.dxf [output.dxf]")
        sys.exit(1)

    outline_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else output

    print(f"Loading outline: {outline_path}")
    outline_poly = load_outline(outline_path)
    print(f"Outline bounds: {outline_poly.bounds}")
    print("Generating clipped honeycomb...")
    generate_clipped_honeycomb(outline_poly, R, gap, out_path)
