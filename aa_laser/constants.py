"""Shared visual constants and list constants."""

from PySide6.QtGui import QColor

# ── Canvas colors ────────────────────────────────────────────────────────────
# (hex strings kept for convenience; QColor versions for Qt)
_BG = "#0d1117"  # canvas background — deepest layer
_POLY = "#4a9eff"  # polyline normal
_SEL = "#f47067"  # polyline selected / danger accent
_DIM = "#8b949e"  # muted labels / secondary text

Q_BG = QColor(_BG)
Q_POLY = QColor(_POLY)
Q_SEL = QColor(_SEL)
Q_DIM = QColor(_DIM)

# ── Semantic status colors (for setStyleSheet calls in tabs) ─────────────────
_SUCCESS = "#3fb950"  # green — saved, done, ok
_ERROR = "#f85149"  # red   — failed, error
_WARN = "#d29922"  # amber — warning

# Interaction
_DRAG_THRESH = 5  # pixels

# Pattern and shape option lists
_PATTERNS = [
    "— None —",
    "Honeycomb",
    "Gradient Honeycomb",
    "Diamond Checkering",
    "Fish Scale",
    "Stipple Dots",
    "Brick",
    "Diagonal Lines",
    "Square Grid",
    "Concentric Rings",
    "Wave Fill",
    "Sunburst",
    "Voronoi",
    "Triangle Grid",
    "Custom Tile",
    "Image Halftone",
]

_SHAPES = ["Rectangle", "Circle", "Ellipse", "Regular Polygon"]
