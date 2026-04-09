#!/usr/bin/env python3
"""
Remove slide outlines from gun DXF files, keeping only grip/frame geometry.

The slide is identified by finding the tallest polyline (the grip handle),
then removing all polylines that are entirely on the "slide side" of
the grip's upper edge.

Usage:
    python remove_slide.py --dry-run    # preview changes (default)
    python remove_slide.py --apply      # execute changes (backs up originals)
"""

import os
import shutil
import sys
from pathlib import Path

import ezdxf  # type: ignore[attr-defined]

BASE = Path(__file__).resolve().parent.parent.parent / "outlines"
BACKUP_DIR = BASE / "_originals"

# Skip these — they're already grip-only, top views, or non-standard
SKIP_SUFFIXES = ("-grip", "-top", "-backstrap", "-frontstrap", "-front-strap",
                 "-back-strap", "untitled")


def should_process(dxf_path: Path) -> bool:
    """Return True if this DXF is a left/right outline that may have a slide."""
    stem = dxf_path.stem.lower()

    for suffix in SKIP_SUFFIXES:
        if stem.endswith(suffix):
            return False

    # Only process files that have "left" or "right" in the name
    if "left" not in stem and "right" not in stem:
        return False

    # Skip work-in-progress folders
    rel = str(dxf_path.relative_to(BASE))
    if "g43-&-43x-new" in rel or "_originals" in rel or "_reference" in rel:
        return False

    return True


def find_dxf_files():
    """Find all .dxf files to process."""
    results = []
    for root, _dirs, files in os.walk(BASE):
        for f in files:
            if f.lower().endswith(".dxf"):
                p = Path(root) / f
                if should_process(p):
                    results.append(p)
    results.sort()
    return results


def analyze_polylines(msp):
    """Extract bounding box info for each LWPOLYLINE entity."""
    polys = []
    for entity in msp:
        if entity.dxftype() == "LWPOLYLINE":
            pts = list(entity.get_points())  # type: ignore[attr-defined]
            if not pts:
                continue
            ys = [p[1] for p in pts]
            xs = [p[0] for p in pts]
            polys.append({
                "entity": entity,
                "npts": len(pts),
                "min_y": min(ys),
                "max_y": max(ys),
                "min_x": min(xs),
                "max_x": max(xs),
                "height": max(ys) - min(ys),
                "width": max(xs) - min(xs),
            })
    return polys


def detect_slide_direction(polys):
    """Determine whether the slide is at max_y or min_y.

    The grip handle is the tallest polyline and extends the furthest in the
    "down" direction (away from the slide). We detect which direction is "down"
    by looking at where the tallest polyline extends furthest.

    Returns 'max' if the slide is at the max_y end, 'min' if at min_y.
    """
    if not polys:
        return "max"

    # The overall bounding box
    overall_min_y = min(p["min_y"] for p in polys)
    overall_max_y = max(p["max_y"] for p in polys)
    overall_mid_y = (overall_min_y + overall_max_y) / 2

    # Find the tallest polyline (the grip handle)
    grip_poly = max(polys, key=lambda p: p["height"])

    # The grip extends away from the slide. If the grip's center is below
    # the overall midpoint, the slide is at max_y. Otherwise at min_y.
    grip_center_y = (grip_poly["min_y"] + grip_poly["max_y"]) / 2

    if grip_center_y < overall_mid_y:
        return "max"  # grip goes down (min_y), slide is up (max_y)
    else:
        return "min"  # grip goes up (max_y), slide is down (min_y)


def find_slide_boundary(polys, direction):
    """Find the Y value that separates slide from grip.

    The grip polyline (tallest) defines the boundary: its edge closest to
    the slide is the dividing line. Polylines entirely on the slide side
    of this line are removed.
    """
    grip_poly = max(polys, key=lambda p: p["height"])

    if direction == "max":
        # Slide is at max_y, grip extends toward min_y
        # The boundary is the grip's max_y (its upper edge)
        return grip_poly["max_y"]
    else:
        # Slide is at min_y, grip extends toward max_y
        # The boundary is the grip's min_y (its lower edge)
        return grip_poly["min_y"]


def classify_polylines(polys, boundary_y, direction):
    """Classify each polyline as 'keep' or 'slide'."""
    results = []
    for p in polys:
        if direction == "max":
            # Slide is above (higher Y). Remove if entirely above boundary.
            is_slide = p["min_y"] > boundary_y
        else:
            # Slide is below (lower Y). Remove if entirely below boundary.
            is_slide = p["max_y"] < boundary_y

        results.append({
            **p,
            "action": "REMOVE" if is_slide else "KEEP",
        })
    return results


def process_file(dxf_path, dry_run=True):
    """Analyze and optionally modify a single DXF file."""
    doc = ezdxf.readfile(str(dxf_path))  # type: ignore[attr-defined]
    msp = doc.modelspace()
    polys = analyze_polylines(msp)

    if len(polys) <= 1:
        return None  # Nothing to remove if only one polyline

    direction = detect_slide_direction(polys)
    boundary_y = find_slide_boundary(polys, direction)
    classified = classify_polylines(polys, boundary_y, direction)

    to_remove = [c for c in classified if c["action"] == "REMOVE"]
    to_keep = [c for c in classified if c["action"] == "KEEP"]

    if not to_remove:
        return None  # No slide detected

    result = {
        "file": str(dxf_path.relative_to(BASE)),
        "total_polys": len(polys),
        "removing": len(to_remove),
        "keeping": len(to_keep),
        "direction": direction,
        "boundary_y": boundary_y,
        "details": classified,
    }

    if not dry_run:
        # Backup original
        rel = dxf_path.relative_to(BASE)
        backup_path = BACKUP_DIR / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(dxf_path), str(backup_path))

        # Remove slide entities
        for c in to_remove:
            msp.delete_entity(c["entity"])

        doc.saveas(str(dxf_path))

    return result


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    dry_run = mode != "--apply"

    files = find_dxf_files()
    print(f"Found {len(files)} DXF files to process")
    print("=" * 70)

    modified = 0
    skipped = 0
    errors = []

    for f in files:
        try:
            result = process_file(f, dry_run=dry_run)
            if result is None:
                skipped += 1
                continue

            modified += 1
            action = "Would remove" if dry_run else "Removed"
            print(f"\n{result['file']}")
            print(f"  {action} {result['removing']}/{result['total_polys']} polylines "
                  f"(slide at {result['direction']}_y, boundary={result['boundary_y']:.1f})")

            for d in result["details"]:
                marker = "  ✗" if d["action"] == "REMOVE" else "  ✓"
                print(f"  {marker} {d['npts']:4d}pts  "
                      f"y=[{d['min_y']:7.1f}, {d['max_y']:7.1f}]  "
                      f"h={d['height']:5.1f}  "
                      f"w={d['width']:5.1f}")
        except Exception as e:
            errors.append(f"{f.relative_to(BASE)}: {e}")

    print("\n" + "=" * 70)
    print(f"Modified: {modified}  |  Skipped (no slide): {skipped}  |  Errors: {len(errors)}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  {e}")

    if dry_run:
        if modified > 0:
            print("\nDry run — no changes made. Use --apply to execute.")
            print("Originals will be backed up to outlines/_originals/")
    else:
        if modified > 0:
            print("\nDone. Originals backed up to outlines/_originals/")


if __name__ == "__main__":
    main()
