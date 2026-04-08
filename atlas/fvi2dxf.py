import sys
import re
import ezdxf
from pathlib import Path


def convert_fvi_to_dxf(input_path, output_path):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    with open(input_path, "r") as f:
        lines = f.readlines()

    x, y = 0.0, 0.0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match_move = re.match(r"MOVEDIST\s+([-\d.]+),([-\d.]+)", line)
        match_draw = re.match(r"DRAWLINE\s+([-\d.]+),([-\d.]+)", line)

        if match_move:
            dx, dy = float(match_move.group(1)), float(match_move.group(2))
            x += dx
            y += dy

        elif match_draw:
            dx, dy = float(match_draw.group(1)), float(match_draw.group(2))
            x2 = x + dx
            y2 = y + dy
            msp.add_line((x * 0.254, y * 0.254), (x2 * 0.254, y2 * 0.254))
            x, y = x2, y2

    doc.saveas(output_path)


def batch_convert(folder):
    folder = Path(folder)
    fvi_files = [p for p in folder.rglob("*") if p.suffix.lower() == ".fvi"]

    if not fvi_files:
        print(f"No .fvi files found in {folder}")
        return

    print(f"Found {len(fvi_files)} file(s)")

    for fvi in fvi_files:
        out = fvi.with_suffix(".dxf")
        try:
            convert_fvi_to_dxf(fvi, out)
            print(f"  OK  {fvi.name} -> {out.name}")
        except Exception as e:
            print(f"  ERR {fvi.name}: {e}")

    print("Done.")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    batch_convert(folder)
