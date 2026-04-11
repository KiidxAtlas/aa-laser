"""Small layout helper functions for building customtkinter panels."""

from __future__ import annotations

import customtkinter as ctk


def _row(parent, **kw) -> ctk.CTkFrame:
    kw.setdefault("fg_color", "transparent")
    f = ctk.CTkFrame(parent, **kw)
    f.pack(fill="x")
    return f


def _label(parent, text: str, **kw) -> ctk.CTkLabel:
    # Route pack-only kwargs away from CTkLabel constructor
    pady = kw.pop("pady", 0)
    pack_padx = kw.pop("padx", 8)
    kw.setdefault("anchor", "w")
    lb = ctk.CTkLabel(parent, text=text, **kw)
    lb.pack(anchor="w", padx=pack_padx, pady=pady)
    return lb


def _entry(
    parent, default: str = "", placeholder: str = "", width: int = 120
) -> ctk.CTkEntry:
    var = ctk.StringVar(value=default)
    e = ctk.CTkEntry(
        parent, textvariable=var, placeholder_text=placeholder, width=width
    )
    e.pack(side="left", padx=(0, 6))
    return e


def _sep(parent) -> None:
    ctk.CTkFrame(parent, height=1, fg_color="#2a2a4a").pack(fill="x", padx=8, pady=6)


def _section_label(parent, text: str, padx: int = 10, pady=(12, 4)) -> ctk.CTkLabel:
    """Compact muted uppercase section header — replaces bold header + separator combos."""
    lb = ctk.CTkLabel(
        parent,
        text=text.upper(),
        font=ctk.CTkFont(size=10, weight="bold"),
        text_color="#888888",
        anchor="w",
    )
    lb.pack(anchor="w", padx=padx, pady=pady)
    return lb
