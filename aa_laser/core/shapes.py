"""Shape builders — generate polyline point lists centred at origin."""

from __future__ import annotations

import math


def shape_rect(w: float, h: float) -> list[tuple[float, float]]:
    hw, hh = w / 2, h / 2
    return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh), (-hw, -hh)]


def shape_rect_rounded(
    w: float, h: float, r: float, n_corner: int = 8
) -> list[tuple[float, float]]:
    """Rectangle with rounded corners, centred at origin."""
    r = min(r, w / 2, h / 2)
    hw, hh = w / 2, h / 2
    pts: list[tuple[float, float]] = []
    for cx, cy, start in [
        (hw - r, hh - r, 0.0),
        (-hw + r, hh - r, math.pi / 2),
        (-hw + r, -hh + r, math.pi),
        (hw - r, -hh + r, 3 * math.pi / 2),
    ]:
        for i in range(n_corner + 1):
            a = start + i * (math.pi / 2) / n_corner
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return pts


def shape_circle(r: float, n: int = 64) -> list[tuple[float, float]]:
    pts = [
        (r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    return pts + [pts[0]]


def shape_ellipse(rx: float, ry: float, n: int = 64) -> list[tuple[float, float]]:
    pts = [
        (rx * math.cos(2 * math.pi * i / n), ry * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    return pts + [pts[0]]


def shape_polygon(sides: int, r: float) -> list[tuple[float, float]]:
    pts = [
        (
            r * math.cos(2 * math.pi * i / sides - math.pi / 2),
            r * math.sin(2 * math.pi * i / sides - math.pi / 2),
        )
        for i in range(sides)
    ]
    return pts + [pts[0]]
