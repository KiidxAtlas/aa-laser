"""Small layout helper functions for building PySide6 panels."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel


def _section_label(parent_layout, text: str) -> QLabel:
    """Compact muted section header with letter-spacing."""
    lb = QLabel(text.upper())
    lb.setStyleSheet(
        "color: #484f58;"
        "font-size: 10px;"
        "font-weight: 600;"
        "letter-spacing: 0.8px;"
        "padding-bottom: 2px;"
    )
    lb.setContentsMargins(0, 14, 0, 4)
    parent_layout.addWidget(lb)
    return lb


def _sep(parent_layout) -> QFrame:
    """Hairline horizontal separator."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #21262d;")
    line.setFixedHeight(1)
    parent_layout.addWidget(line)
    return line


def _row() -> QHBoxLayout:
    """Create a horizontal row layout."""
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    return h
