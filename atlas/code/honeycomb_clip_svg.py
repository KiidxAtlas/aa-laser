import math
import sys

import ezdxf  # type: ignore[attr-defined]
from shapely import prepared  # type: ignore[import-untyped]
from shapely.geometry import MultiPolygon, Polygon  # type: ignore[import-untyped]
from shapely.ops import unary_union  # type: ignore[import-untyped]

# ── Settings ──────────────────────────────────────────
R = 1.75  # hex side length in mm
gap = 0.5  # wall-to-wall gap in mm
output = "honeycomb_clipped.svg"
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

    if not all_coords:
        raise ValueError(
            "No polylines found in outline DXF. "
            "Make sure it was converted with the updated fvi_to_dxf.py."
        )

    polys = []
    for coords in all_coords:
        try:
            p = Polygon(coords)
            if p.is_valid and p.area > 0:
                polys.append(p)
        except (ValueError, TypeError):
            continue

    if not polys:
        flat = [pt for coords in all_coords for pt in coords]
        return Polygon(flat).convex_hull

    if len(polys) == 1:
        return polys[0]

    result = unary_union(polys)
    if result.is_empty:
        return max(polys, key=lambda p: p.area).convex_hull
    return result


def coords_to_svg_path(coords):
    """Convert a list of (x, y) tuples to an SVG path d attribute."""
    parts = []
    for i, (x, y) in enumerate(coords):
        cmd = "M" if i == 0 else "L"
        parts.append(f"{cmd}{x:.3f},{y:.3f}")
    parts.append("Z")
    return "".join(parts)


def generate_clipped_honeycomb_svg(outline_poly, r, gap, out_path):
    apothem = math.sqrt(3) / 2 * r
    c2c = 2 * apothem + gap
    col_step = c2c
    row_step = (3 / 2) * r + gap * math.sqrt(3) / 2

    minx, miny, maxx, maxy = outline_poly.bounds

    pad = r * 2
    cols = int((maxx - minx + pad * 2) / col_step) + 2
    rows = int((maxy - miny + pad * 2) / row_step) + 2

    # Use prepared geometry for fast contains/intersects checks
    prep_outline = prepared.prep(outline_poly)

    paths = []
    count = 0

    for row in range(rows):
        for col in range(cols):
            offset_x = col_step / 2 if row % 2 == 1 else 0
            cx = minx - pad + col * col_step + offset_x
            cy = miny - pad + row * row_step

            verts = hex_verts(cx, cy, r)
            hex_poly = Polygon(verts)

            # Fast rejection — skip hexes that don't touch outline at all
            if not prep_outline.intersects(hex_poly):
                continue

            # Fast path — hex fully inside outline, no clipping needed
            if prep_outline.contains(hex_poly):
                rounded = [(round(x, 3), round(y, 3)) for x, y in verts]
                paths.append(coords_to_svg_path(rounded))
                count += 1
                continue

            # Slow path — clip hex to outline boundary
            clipped = outline_poly.intersection(hex_poly)

            if clipped.is_empty:
                continue

            geoms = []
            if isinstance(clipped, Polygon):
                geoms = [clipped]
            elif isinstance(clipped, MultiPolygon):
                geoms = list(clipped.geoms)
            else:
                continue

            for geom in geoms:
                if geom.is_empty or geom.area < 0.001:
                    continue
                geom = geom.simplify(0.01, preserve_topology=True)
                coords = [(round(x, 3), round(y, 3)) for x, y in geom.exterior.coords]  # type: ignore[attr-defined]
                if len(coords) >= 3:
                    paths.append(coords_to_svg_path(coords))
                    count += 1

    # Compute SVG viewBox from outline bounds with small margin
    margin = 1.0
    vb_x = minx - margin
    vb_y = miny - margin
    vb_w = (maxx - minx) + 2 * margin
    vb_h = (maxy - miny) + 2 * margin

    # Combine all hex paths into a single <path> element — much lighter than
    # thousands of individual elements, and renderers handle it far better.
    combined_d = " ".join(paths)

    # SVG coordinate system has Y increasing downward; our geometry has Y up.
    # We flip Y via a transform on the group.
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vb_x:.3f} {-maxy - margin:.3f} {vb_w:.3f} {vb_h:.3f}" '
        f'width="{vb_w:.3f}mm" height="{vb_h:.3f}mm">\n'
        f'  <g transform="scale(1,-1)" fill="none" stroke="black" stroke-width="0.05">\n'
        f'    <path d="{combined_d}"/>\n'
        f"  </g>\n"
        f"</svg>\n"
    )

    with open(out_path, "w") as f:
        f.write(svg)

    print(f"Done — {count} hexagon shapes written to {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python honeycomb_clip_svg.py outline.dxf [output.svg]")
        sys.exit(1)

    outline_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else output

    print(f"Loading outline: {outline_path}")
    outline_poly = load_outline(outline_path)
    print(f"Outline bounds: {outline_poly.bounds}")
    print("Generating clipped honeycomb...")
    generate_clipped_honeycomb_svg(outline_poly, R, gap, out_path)
