import math
import os
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk  # type: ignore[import-untyped]
import ezdxf  # type: ignore[attr-defined]
from shapely import prepared  # type: ignore[import-untyped]
from shapely.geometry import MultiPolygon, Polygon  # type: ignore[import-untyped]
from shapely.ops import unary_union  # type: ignore[import-untyped]

# ── Core logic ────────────────────────────────────────


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
        raise ValueError("No polylines found in outline DXF.")

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
    parts = []
    for i, (x, y) in enumerate(coords):
        cmd = "M" if i == 0 else "L"
        parts.append(f"{cmd}{x:.3f},{y:.3f}")
    parts.append("Z")
    return "".join(parts)


def generate_clipped_honeycomb_svg(outline_poly, r, gap):
    apothem = math.sqrt(3) / 2 * r
    c2c = 2 * apothem + gap
    col_step = c2c
    row_step = (3 / 2) * r + gap * math.sqrt(3) / 2

    minx, miny, maxx, maxy = outline_poly.bounds

    pad = r * 2
    cols = int((maxx - minx + pad * 2) / col_step) + 2
    rows = int((maxy - miny + pad * 2) / row_step) + 2

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

            if not prep_outline.intersects(hex_poly):
                continue

            if prep_outline.contains(hex_poly):
                rounded = [(round(x, 3), round(y, 3)) for x, y in verts]
                paths.append(coords_to_svg_path(rounded))
                count += 1
                continue

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

    margin = 1.0
    vb_x = minx - margin
    vb_w = (maxx - minx) + 2 * margin
    vb_h = (maxy - miny) + 2 * margin

    combined_d = " ".join(paths)

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vb_x:.3f} {-maxy - margin:.3f} {vb_w:.3f} {vb_h:.3f}" '
        f'width="{vb_w:.3f}mm" height="{vb_h:.3f}mm">\n'
        f'  <g transform="scale(1,-1)" fill="none" stroke="black" stroke-width="0.05">\n'
        f'    <path d="{combined_d}"/>\n'
        f"  </g>\n"
        f"</svg>\n"
    )

    return svg, count


# ── GUI ───────────────────────────────────────────────


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Honeycomb Clip")
        self.geometry("480x380")
        self.resizable(False, False)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ── File picker ───────────────────────────────
        file_frame = ctk.CTkFrame(self)
        file_frame.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(file_frame, text="Outline DXF").pack(
            anchor="w", padx=8, pady=(8, 0)
        )

        row = ctk.CTkFrame(file_frame, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(4, 8))

        self.file_var = ctk.StringVar()
        self.file_entry = ctk.CTkEntry(
            row, textvariable=self.file_var, placeholder_text="Select a .dxf file…"
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(row, text="Browse", width=80, command=self._browse).pack(
            side="right"
        )

        # ── Parameters ────────────────────────────────
        param_frame = ctk.CTkFrame(self)
        param_frame.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(param_frame, text="Hex size (mm)").grid(
            row=0, column=0, padx=8, pady=(8, 4), sticky="w"
        )
        self.hex_size_var = ctk.StringVar(value="1.75")
        ctk.CTkEntry(param_frame, textvariable=self.hex_size_var, width=100).grid(
            row=0, column=1, padx=8, pady=(8, 4)
        )

        ctk.CTkLabel(param_frame, text="Gap (mm)").grid(
            row=1, column=0, padx=8, pady=(4, 8), sticky="w"
        )
        self.gap_var = ctk.StringVar(value="0.5")
        ctk.CTkEntry(param_frame, textvariable=self.gap_var, width=100).grid(
            row=1, column=1, padx=8, pady=(4, 8)
        )

        param_frame.columnconfigure(1, weight=1)

        # ── Generate button ───────────────────────────
        self.gen_btn = ctk.CTkButton(
            self, text="Generate SVG", height=40, command=self._generate
        )
        self.gen_btn.pack(padx=16, pady=(8, 4))

        # ── Status ────────────────────────────────────
        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.pack(padx=16, pady=(4, 4))

        self.progress = ctk.CTkProgressBar(self)
        self.progress.pack(fill="x", padx=16, pady=(0, 16))
        self.progress.set(0)

    # ── Actions ───────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select outline DXF",
            filetypes=[("DXF files", "*.dxf *.Dxf *.DXF"), ("All files", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def _set_status(self, text, color="gray"):
        self.status_label.configure(text=text, text_color=color)

    def _generate(self):
        dxf_path = self.file_var.get().strip()
        if not dxf_path or not os.path.isfile(dxf_path):
            self._set_status("Please select a valid DXF file.", "#e06060")
            return

        try:
            r = float(self.hex_size_var.get())
            gap = float(self.gap_var.get())
        except ValueError:
            self._set_status("Hex size and gap must be numbers.", "#e06060")
            return

        if r <= 0 or gap < 0:
            self._set_status("Hex size must be > 0, gap must be >= 0.", "#e06060")
            return

        out_path = filedialog.asksaveasfilename(
            title="Save SVG as",
            defaultextension=".svg",
            initialfile=Path(dxf_path).stem + "_honeycomb.svg",
            initialdir=str(Path(dxf_path).parent),
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
        )
        if not out_path:
            return

        self.gen_btn.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._set_status("Loading outline…")

        thread = threading.Thread(
            target=self._run, args=(dxf_path, r, gap, out_path), daemon=True
        )
        thread.start()

    def _run(self, dxf_path, r, gap, out_path):
        try:
            outline_poly = load_outline(dxf_path)
            self.after(0, self._set_status, "Generating honeycomb…")

            svg, count = generate_clipped_honeycomb_svg(outline_poly, r, gap)

            with open(out_path, "w") as f:
                f.write(svg)

            self.after(0, self._done, count, out_path)
        except Exception as exc:
            self.after(0, self._error, str(exc))

    def _done(self, count, out_path):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self.gen_btn.configure(state="normal")
        name = Path(out_path).name
        self._set_status(f"Done — {count} shapes → {name}", "#60c060")

    def _error(self, msg):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.gen_btn.configure(state="normal")
        self._set_status(f"Error: {msg}", "#e06060")


if __name__ == "__main__":
    App().mainloop()
