"""Batch-run honeycomb clip on all outline DXFs.

Produces both DXF and SVG outputs in a `hex/` subfolder next to each outline.

Usage:
    python batch_hex_clip.py [--dry-run | --apply]
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import ezdxf  # type: ignore[attr-defined]
from shapely import prepared  # type: ignore[import-untyped]
from shapely.geometry import MultiPolygon, Polygon  # type: ignore[import-untyped]
from shapely.ops import unary_union  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
OUTLINES_DIR = ROOT / "outlines"
SKIP_DIRS = {"_originals", "_reference"}
SKIP_NAME_CONTAINS = {"hex"}

# ── Hex settings ──────────────────────────────────────
R = 1.75  # hex side length in mm
GAP = 0.5  # wall-to-wall gap in mm
# ──────────────────────────────────────────────────────


# ── Shared geometry helpers ───────────────────────────


def hex_verts(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    return [
        (
            cx + r * math.cos(math.pi / 6 + i * math.pi / 3),
            cy + r * math.sin(math.pi / 6 + i * math.pi / 3),
        )
        for i in range(6)
    ]


def load_outline(dxf_path: Path) -> Polygon | MultiPolygon:
    doc = ezdxf.readfile(str(dxf_path))  # type: ignore[attr-defined]
    msp = doc.modelspace()
    all_coords: list[list[tuple[float, float]]] = []

    for entity in msp:
        if entity.dxftype() == "LWPOLYLINE":
            pts = list(entity.get_points())  # type: ignore[attr-defined]
            coords = [(p[0], p[1]) for p in pts]
            if len(coords) >= 3:
                all_coords.append(coords)
        elif entity.dxftype() == "POLYLINE":
            pts = list(entity.points())  # type: ignore[attr-defined]
            coords = [(p[0], p[1]) for p in pts]
            if len(coords) >= 3:
                all_coords.append(coords)

    if not all_coords:
        return None  # type: ignore[return-value]

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


# ── Grid parameters ──────────────────────────────────


def _grid_params(outline_poly, r, gap):
    apothem = math.sqrt(3) / 2 * r
    c2c = 2 * apothem + gap
    col_step = c2c
    row_step = (3 / 2) * r + gap * math.sqrt(3) / 2

    minx, miny, maxx, maxy = outline_poly.bounds
    pad = r * 2
    cols = int((maxx - minx + pad * 2) / col_step) + 2
    rows = int((maxy - miny + pad * 2) / row_step) + 2

    return col_step, row_step, minx, miny, maxx, maxy, pad, cols, rows


# ── DXF output ───────────────────────────────────────


def _round_coords(coords, decimals=3):
    return [(round(x, decimals), round(y, decimals)) for x, y in coords]


def generate_dxf(outline_poly, r, gap, out_path: Path) -> int:
    col_step, row_step, minx, miny, maxx, maxy, pad, cols, rows = _grid_params(
        outline_poly, r, gap
    )
    prep_outline = prepared.prep(outline_poly)

    doc = ezdxf.new("R2010")  # type: ignore[attr-defined]
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()

    # Define a reusable BLOCK for full (unclipped) hexagons at the origin.
    # Each interior hex becomes a lightweight INSERT instead of 6-vertex polyline.
    hex_block = doc.blocks.new(name="HEX")  # type: ignore[attr-defined]
    origin_verts = hex_verts(0.0, 0.0, r)
    hex_block.add_lwpolyline(_round_coords(origin_verts), close=True)

    count = 0

    for row in range(rows):
        for col in range(cols):
            offset_x = col_step / 2 if row % 2 == 1 else 0
            cx = minx - pad + col * col_step + offset_x
            cy = miny - pad + row * row_step

            verts = hex_verts(cx, cy, r)
            hex_poly = Polygon(verts)

            if not prep_outline.intersects(hex_poly):
                continue

            # Full hex inside outline → lightweight block INSERT
            if prep_outline.contains(hex_poly):
                msp.add_blockref("HEX", insert=(round(cx, 3), round(cy, 3)))
                count += 1
                continue

            # Partial hex on boundary → clip and simplify
            clipped = outline_poly.intersection(hex_poly)
            if clipped.is_empty:
                continue

            geoms: list = []
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
                coords = _round_coords(geom.exterior.coords)  # type: ignore[attr-defined]
                if len(coords) >= 3:
                    msp.add_lwpolyline(coords, close=True)
                    count += 1

    doc.saveas(str(out_path))
    return count


# ── SVG output ───────────────────────────────────────


def _coords_to_svg_path(coords) -> str:
    parts = []
    for i, (x, y) in enumerate(coords):
        cmd = "M" if i == 0 else "L"
        parts.append(f"{cmd}{x:.3f},{y:.3f}")
    parts.append("Z")
    return "".join(parts)


def generate_svg(outline_poly, r, gap, out_path: Path) -> int:
    col_step, row_step, minx, miny, maxx, maxy, pad, cols, rows = _grid_params(
        outline_poly, r, gap
    )
    prep_outline = prepared.prep(outline_poly)

    paths: list[str] = []
    count = 0

    for row in range(rows):
        for col in range(cols):
            offset_x = col_step / 2 if row % 2 == 1 else 0
            cx = minx - pad + col * col_step + offset_x
            cy = miny - pad + row * row_step

            verts = hex_verts(cx, cy, r)
            hex_poly = Polygon(verts)

            if not prep_outline.intersects(hex_poly):
                continue

            if prep_outline.contains(hex_poly):
                rounded = [(round(x, 3), round(y, 3)) for x, y in verts]
                paths.append(_coords_to_svg_path(rounded))
                count += 1
                continue

            clipped = outline_poly.intersection(hex_poly)
            if clipped.is_empty:
                continue

            geoms: list = []
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
                    paths.append(_coords_to_svg_path(coords))
                    count += 1

    margin = 1.0
    vb_w = (maxx - minx) + 2 * margin
    vb_h = (maxy - miny) + 2 * margin

    combined_d = " ".join(paths)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{minx - margin:.3f} {-maxy - margin:.3f} {vb_w:.3f} {vb_h:.3f}" '
        f'width="{vb_w:.3f}mm" height="{vb_h:.3f}mm">\n'
        f'  <g transform="scale(1,-1)" fill="none" stroke="black" stroke-width="0.05">\n'
        f'    <path d="{combined_d}"/>\n'
        f"  </g>\n"
        f"</svg>\n"
    )

    out_path.write_text(svg)
    return count


# ── Batch runner ─────────────────────────────────────


def collect_outlines() -> list[Path]:
    """Find all outline DXFs, skipping backup/meta dirs."""
    files: list[Path] = []
    for dxf in sorted(OUTLINES_DIR.rglob("*.dxf")):
        rel_parts = dxf.relative_to(OUTLINES_DIR).parts
        # Skip backup/meta dirs
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        # Skip existing hex output folders and files named 'honeycomb'/'untitled'
        if any("hex" in part for part in rel_parts[:-1]):  # 'hex' in any parent dir
            continue
        if dxf.stem in ("honeycomb", "untitled"):
            continue
        files.append(dxf)
    return files


def process_one(dxf_path: Path, dry_run: bool) -> tuple[str, str]:
    """Process a single outline. Returns (status, detail)."""
    hex_dir = dxf_path.parent / "hex"
    stem = dxf_path.stem
    dxf_out = hex_dir / f"{stem}-hex.dxf"
    svg_out = hex_dir / f"{stem}-hex.svg"

    rel = dxf_path.relative_to(ROOT)

    if dry_run:
        return "would-generate", f"{rel} → hex/{stem}-hex.{{dxf,svg}}"

    try:
        outline_poly = load_outline(dxf_path)
    except (ValueError, Exception) as exc:  # noqa: BLE001
        return "error", f"{rel}: {exc}"

    if outline_poly is None:
        return "skipped", f"{rel}: empty / no polylines"

    hex_dir.mkdir(parents=True, exist_ok=True)

    dxf_count = generate_dxf(outline_poly, R, GAP, dxf_out)
    svg_count = generate_svg(outline_poly, R, GAP, svg_out)

    return "ok", f"{rel} → {dxf_count} dxf / {svg_count} svg hexes"


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch honeycomb clip on all outlines")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview without writing")
    group.add_argument("--apply", action="store_true", help="Generate all files")
    args = parser.parse_args()

    outlines = collect_outlines()
    print(f"Found {len(outlines)} outline DXFs\n")

    ok = err = skipped = 0
    t0 = time.monotonic()

    for i, dxf_path in enumerate(outlines, 1):
        status, detail = process_one(dxf_path, dry_run=args.dry_run)
        tag = {"ok": "✓", "would-generate": "·", "error": "✗", "skipped": "–"}.get(
            status, "?"
        )
        print(f"[{i:3d}/{len(outlines)}] {tag} {detail}")

        if status in ("ok", "would-generate"):
            ok += 1
        elif status == "skipped":
            skipped += 1
        else:
            err += 1

    elapsed = time.monotonic() - t0
    print(f"\n{'=' * 70}")
    print(
        f"Generated: {ok}  |  Skipped: {skipped}  |  Errors: {err}  |  Time: {elapsed:.1f}s"
    )
    if args.dry_run:
        print("Dry run — no files written. Use --apply to generate.")


if __name__ == "__main__":
    main()
