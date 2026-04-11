"""FVI → DXF conversion."""

from __future__ import annotations

import re
from pathlib import Path

import ezdxf  # type: ignore[attr-defined]

_FVI_SCALE = 0.254  # FVI units → mm


def convert_fvi_to_dxf(src: Path, dst: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    x = y = 0.0
    pts: list[tuple[float, float]] = []

    def _flush() -> None:
        if len(pts) >= 2:
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
    _flush()
    doc.saveas(str(dst))
