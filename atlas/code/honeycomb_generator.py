import math

# ── Settings ──────────────────────────────────────────
R = 1.75  # hex side length in mm
gap = 1.0  # wall-to-wall gap in mm
cols = 10  # number of columns
rows = 10  # number of rows
output = "honeycomb.dxf"
# ──────────────────────────────────────────────────────

apothem = math.sqrt(3) / 2 * R
c2c = 2 * apothem + gap
col_step = c2c
row_step = c2c * math.sqrt(3) / 2


def hex_verts(cx, cy, R):
    pts = []
    for i in range(6):
        angle = math.pi / 6 + i * math.pi / 3
        pts.append((cx + R * math.cos(angle), cy + R * math.sin(angle)))
    return pts


hexagons = []
for row in range(rows):
    for col in range(cols):
        offset_x = col_step / 2 if row % 2 == 1 else 0
        cx = col * col_step + offset_x
        cy = row * row_step
        hexagons.append(hex_verts(cx, cy, R))

dxf = []
dxf += [
    "  0",
    "SECTION",
    "  2",
    "HEADER",
    "  9",
    "$ACADVER",
    "  1",
    "AC1009",
    "  9",
    "$INSUNITS",
    " 70",
    "4",
    "  0",
    "ENDSEC",
    "  0",
    "SECTION",
    "  2",
    "TABLES",
    "  0",
    "TABLE",
    "  2",
    "LTYPE",
    " 70",
    "1",
    "  0",
    "LTYPE",
    "  2",
    "CONTINUOUS",
    " 70",
    "0",
    "  3",
    "Solid line",
    " 72",
    "65",
    " 73",
    "0",
    " 40",
    "0.0",
    "  0",
    "ENDTAB",
    "  0",
    "TABLE",
    "  2",
    "LAYER",
    " 70",
    "1",
    "  0",
    "LAYER",
    "  2",
    "0",
    " 70",
    "0",
    " 62",
    "7",
    "  6",
    "CONTINUOUS",
    "  0",
    "ENDTAB",
    "  0",
    "ENDSEC",
    "  0",
    "SECTION",
    "  2",
    "BLOCKS",
    "  0",
    "ENDSEC",
    "  0",
    "SECTION",
    "  2",
    "ENTITIES",
]

for verts in hexagons:
    dxf += [
        "  0",
        "POLYLINE",
        "  8",
        "0",
        " 66",
        "1",
        " 70",
        "1",
        " 10",
        "0.0",
        " 20",
        "0.0",
        " 30",
        "0.0",
    ]
    for x, y in verts:
        dxf += [
            "  0",
            "VERTEX",
            "  8",
            "0",
            " 10",
            f"{x:.6f}",
            " 20",
            f"{y:.6f}",
            " 30",
            "0.0",
        ]
    dxf += ["  0", "SEQEND", "  8", "0"]

dxf += ["  0", "ENDSEC", "  0", "EOF"]

with open(output, "w") as f:
    f.write("\n".join(dxf))

print(f"Done — {len(hexagons)} hexagons written to {output}")
print(f"Grid size: {col_step * cols:.1f}mm wide x {row_step * rows:.1f}mm tall")
