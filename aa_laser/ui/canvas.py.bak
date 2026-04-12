"""DxfCanvas — interactive pan/zoom canvas with polyline selection, measure, draw, and edit tools."""

from __future__ import annotations

import math
import tkinter as tk
import weakref

from PIL import Image as PILImage, ImageTk

from aa_laser.constants import _BG, _DIM, _DRAG_THRESH, _POLY, _SEL

# Edit-mode visual constants
_HANDLE = "#44aaff"  # vertex handle outline
_HANDLE_HOVER = "#44ff88"  # hovered vertex
_HANDLE_ACTIVE = "#ffdd44"  # actively dragged vertex
_SNAP_CLOSE = "#44ff88"  # close-polygon snap indicator
_HANDLE_R = 4  # vertex handle radius (screen px)
_SNAP_DIST = 10  # close-snap threshold (screen px)
_VERT_HIT = 8  # vertex hit-test radius (screen px)
_EDGE_HIT = 6  # edge hit-test distance (screen px)


class DxfCanvas(tk.Canvas):
    _registry: list = []

    """
    Displays polyline lists with Select / Draw / Edit modes.

    Modes:
    • ``select`` — click polylines to select/deselect, Shift+drag rubber-band
    • ``draw``   — click to place vertices, finish with dbl-click/Enter/right-click
    • ``edit``   — drag vertices, double-click edge to insert, right-click vertex to delete

    Set ``selectable=False`` for a display-only preview (no mode switching).
    ``on_change(sel_count)`` fires whenever the selection or data changes.
    ``on_mode_change(mode_str)`` fires when mode changes (for toolbar sync).
    """

    def __init__(
        self,
        master,
        selectable: bool = True,
        on_change: callable | None = None,
        on_mode_change: callable | None = None,
        **kw,
    ):
        kw.setdefault("bg", _BG)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, **kw)

        self._selectable = selectable
        self._on_change = on_change
        self._on_mode_change = on_mode_change

        self._polys: list[list[tuple[float, float]]] = []
        self._sel: set[int] = set()
        self._id2idx: dict[int, int] = {}

        self._scale = 1.0
        self._ox = 0.0
        self._oy = 0.0

        # LMB interaction state
        self._lmb_press: tuple[int, int] | None = None
        self._lmb_prev: tuple[int, int] | None = None
        self._lmb_target: int | None = None

        # MMB pan state
        self._mmb_prev: tuple[int, int] | None = None

        # Cursor world position (for overlay)
        self._cursor_wx: float | None = None
        self._cursor_wy: float | None = None

        # Rubber-band select state (Shift+drag)
        self._shift_drag: bool = False
        self._band_start: tuple[int, int] | None = None

        # Undo stack — each entry is a snapshot of self._polys before a mutation
        self._undo_stack: list[list] = []

        # Fit scale for zoom-% display
        self._fit_scale: float = 1.0

        # Measure tool state
        self._measure_mode: bool = False
        self._measure_anchor: tuple[float, float] | None = None
        self._measure_hover: tuple[float, float] | None = None
        self._mbtn_rect: tuple[int, int, int, int] = (0, 0, 0, 0)

        # Mode: "select" | "draw" | "edit"
        self._mode: str = "select"

        # Draw mode state
        self._draw_pts: list[tuple[float, float]] = []

        # Edit mode state
        self._edit_poly: int | None = None
        self._edit_vert: int | None = None
        self._edit_dragging: bool = False
        self._hover_vert: tuple[int, int] | None = None  # (poly_idx, vert_idx)

        # Image bounds for reference rectangle (w_mm, h_mm)
        self._img_bounds: tuple[float, float] | None = None

        # Background image overlay
        self._bg_pil: PILImage.Image | None = None
        self._bg_w_mm: float = 0.0
        self._bg_h_mm: float = 0.0
        self._bg_tk: ImageTk.PhotoImage | None = None
        self._bg_cached_scale: float = 0.0

        self.bind("<Configure>", lambda _: self._fit())
        self.bind("<Enter>", lambda e: self.focus_set())
        self.bind("<ButtonPress-1>", self._lmb_press_cb)
        self.bind("<B1-Motion>", self._lmb_drag_cb)
        self.bind("<ButtonRelease-1>", self._lmb_release_cb)
        self.bind("<ButtonPress-2>", lambda e: setattr(self, "_mmb_prev", (e.x, e.y)))
        self.bind("<B2-Motion>", self._mmb_drag_cb)
        self.bind("<ButtonRelease-2>", lambda _: setattr(self, "_mmb_prev", None))
        self.bind("<MouseWheel>", self._scroll_cb)
        self.bind("<Button-4>", self._scroll_cb)
        self.bind("<Button-5>", self._scroll_cb)
        DxfCanvas._registry.append(weakref.ref(self))
        self.bind("<Motion>", self._motion_cb)
        self.bind("<f>", lambda e: self.fit())
        self.bind("<F>", lambda e: self.fit())
        self.bind("<plus>", lambda e: self._zoom_by(1.15))
        self.bind("<equal>", lambda e: self._zoom_by(1.15))
        self.bind("<minus>", lambda e: self._zoom_by(1 / 1.15))
        self.bind("<m>", lambda e: self.toggle_measure())
        self.bind("<M>", lambda e: self.toggle_measure())
        if selectable:
            self.bind("<Delete>", lambda e: self._key_delete())
            self.bind("<BackSpace>", lambda e: self._key_backspace())
            self.bind("<Escape>", lambda e: self._escape_cb())
            self.bind("<Button-3>", self._rightclick_cb)
            self.bind("<Control-Button-1>", self._rightclick_cb)
            self.bind("<Double-ButtonPress-1>", self._lmb_double_cb)
            self.bind("<d>", lambda e: self.set_mode("draw" if self._mode != "draw" else "select"))
            self.bind("<D>", lambda e: self.set_mode("draw" if self._mode != "draw" else "select"))
            self.bind("<e>", lambda e: self.set_mode("edit" if self._mode != "edit" else "select"))
            self.bind("<E>", lambda e: self.set_mode("edit" if self._mode != "edit" else "select"))
            self.bind("<Return>", lambda e: self._finish_draw())
        else:
            self.bind("<Escape>", lambda e: self._escape_cb())

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, polys: list[list[tuple[float, float]]]) -> None:
        """Load new polylines and reset to fit view."""
        self._polys = list(polys)
        self._sel.clear()
        self._fit()
        self._notify()

    def reload(self, polys: list[list[tuple[float, float]]]) -> None:
        """Replace polylines without resetting zoom/pan."""
        self._polys = list(polys)
        self._sel &= set(range(len(self._polys)))
        self._draw()
        self._notify()

    def get_active(self) -> list[list[tuple[float, float]]]:
        """Polylines that are NOT selected (i.e. not marked for deletion)."""
        return [p for i, p in enumerate(self._polys) if i not in self._sel]

    def get_selected(self) -> list[list[tuple[float, float]]]:
        """Polylines that ARE currently selected."""
        return [p for i, p in enumerate(self._polys) if i in self._sel]

    def delete_selected(self) -> int:
        """Remove selected polylines; returns count removed."""
        n = len(self._sel)
        if n:
            self._push_undo()
        self._polys = [p for i, p in enumerate(self._polys) if i not in self._sel]
        self._sel.clear()
        self._draw()
        self._notify()
        return n

    def undo(self) -> bool:
        """Restore the last undo snapshot. Returns True if anything was undone."""
        if not self._undo_stack:
            return False
        self._polys = self._undo_stack.pop()
        self._sel.clear()
        self._edit_poly = None
        self._edit_vert = None
        self._edit_dragging = False
        self._hover_vert = None
        self._draw()
        self._notify()
        return True

    # Backward compat alias
    def undo_delete(self) -> bool:
        return self.undo()

    def invert_selection(self) -> None:
        self._sel = set(range(len(self._polys))) - self._sel
        self._draw()
        self._notify()

    def select_all(self) -> None:
        self._sel = set(range(len(self._polys)))
        self._draw()
        self._notify()

    def deselect_all(self) -> None:
        self._sel.clear()
        self._draw()
        self._notify()

    def toggle_measure(self) -> None:
        self._measure_mode = not self._measure_mode
        self._measure_anchor = None
        self._measure_hover = None
        self._update_cursor()
        self._draw()

    def set_image_bounds(self, w_mm: float, h_mm: float) -> None:
        self._img_bounds = (w_mm, h_mm)
        self._draw()

    def set_background_image(self, pil_img: PILImage.Image, w_mm: float, h_mm: float) -> None:
        """Set a faded background image (already alpha-blended) for visual reference."""
        self._bg_pil = pil_img
        self._bg_w_mm = w_mm
        self._bg_h_mm = h_mm
        self._bg_tk = None
        self._bg_cached_scale = 0.0
        self._draw()

    def clear_background_image(self) -> None:
        self._bg_pil = None
        self._bg_tk = None
        self._draw()

    # ── Mode management ───────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """Switch mode: 'select', 'draw', or 'edit'."""
        if mode == self._mode:
            return
        # Clean up old mode
        if self._mode == "draw":
            self._draw_pts.clear()
        elif self._mode == "edit":
            self._edit_poly = None
            self._edit_vert = None
            self._edit_dragging = False
            self._hover_vert = None
        self._mode = mode
        if mode in ("draw", "edit"):
            self._measure_mode = False
        self._update_cursor()
        self._draw()
        if self._on_mode_change:
            self._on_mode_change(mode)

    def get_mode(self) -> str:
        return self._mode

    # Backward compat wrappers
    def toggle_draw_mode(self) -> None:
        self.set_mode("draw" if self._mode != "draw" else "select")

    def get_draw_mode(self) -> bool:
        return self._mode == "draw"

    def _update_cursor(self) -> None:
        if self._measure_mode or self._mode in ("draw", "edit"):
            self.configure(cursor="crosshair")
        else:
            self.configure(cursor="")

    def _escape_cb(self) -> None:
        if self._mode == "draw":
            if self._draw_pts:
                self._draw_pts.clear()
                self._draw()
            else:
                self.set_mode("select")
        elif self._mode == "edit":
            if self._edit_dragging:
                self._edit_dragging = False
                self._draw()
            else:
                self.set_mode("select")
        elif self._measure_mode:
            self.toggle_measure()
        else:
            self.deselect_all()

    def _push_undo(self) -> None:
        self._undo_stack.append([list(p) for p in self._polys])
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _key_delete(self) -> None:
        if self._mode == "select":
            self.delete_selected()

    def _key_backspace(self) -> None:
        if self._mode == "draw" and self._draw_pts:
            self._draw_pts.pop()
            self._draw()
        elif self._mode == "select":
            self.delete_selected()

    def _finish_draw(self) -> None:
        """Finish current draw polygon (Enter key / right-click)."""
        if self._mode != "draw" or len(self._draw_pts) < 2:
            return
        self._push_undo()
        self._polys.append(list(self._draw_pts))
        self._notify()
        self._draw_pts.clear()
        self._draw()

    def fit(self) -> None:
        self._fit()

    @property
    def poly_count(self) -> int:
        return len(self._polys)

    @property
    def sel_count(self) -> int:
        return len(self._sel)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _bbox(self) -> tuple[float, float, float, float]:
        pts = [pt for p in self._polys for pt in p]
        if self._img_bounds:
            bw, bh = self._img_bounds
            pts.extend([(0.0, 0.0), (bw, bh)])
        if not pts:
            return 0.0, 0.0, 1.0, 1.0
        xs, ys = zip(*pts)
        return min(xs), min(ys), max(xs), max(ys)

    def _fit(self) -> None:
        self.update_idletasks()
        w = max(self.winfo_width(), 100)
        h = max(self.winfo_height(), 100)
        x0, y0, x1, y1 = self._bbox()
        dw, dh = x1 - x0, y1 - y0
        if dw > 0 and dh > 0:
            self._scale = min(w / dw, h / dh) * 0.85
            self._fit_scale = self._scale
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self._ox = w / 2 - cx * self._scale
        self._oy = h / 2 + cy * self._scale
        self._draw()

    def _w2c(self, x: float, y: float) -> tuple[float, float]:
        return x * self._scale + self._ox, -y * self._scale + self._oy

    def _c2w(self, cx: float, cy: float) -> tuple[float, float]:
        return (cx - self._ox) / self._scale, -(cy - self._oy) / self._scale

    def _draw(self) -> None:
        self.delete("all")
        self._id2idx.clear()
        w = max(self.winfo_width(), 100)
        h = max(self.winfo_height(), 100)

        # Background image overlay (rendered first, behind everything)
        if self._bg_pil and self._bg_w_mm > 0 and self._bg_h_mm > 0:
            self._draw_bg_image()

        # Image bounds reference rectangle
        if self._img_bounds:
            bw, bh = self._img_bounds
            cx0, cy0 = self._w2c(0.0, 0.0)
            cx1, cy1 = self._w2c(bw, bh)
            self.create_rectangle(
                cx0, cy0, cx1, cy1,
                outline="#334466", dash=(4, 4), fill="", width=1,
            )

        for idx, poly in enumerate(self._polys):
            if len(poly) < 2:
                continue
            flat = [c for pt in poly for c in self._w2c(*pt)]
            sel = idx in self._sel
            color = _SEL if sel else _POLY
            lw = 2.0 if sel else 1.5
            if len(poly) >= 3:
                item = self.create_polygon(
                    flat, outline=color, fill="", width=lw, tags=(f"p{idx}",)
                )
            else:
                item = self.create_line(flat, fill=color, width=lw, tags=(f"p{idx}",))
            self._id2idx[item] = idx

        # Edit mode: vertex handles
        if self._mode == "edit":
            self._draw_edit_handles()

        # In-progress draw polygon
        if self._draw_pts:
            self._draw_in_progress_poly()

        # Info overlay
        n, s = len(self._polys), len(self._sel)
        info = f"{n} polylines" + (f"  ·  {s} selected" if s else "")
        mode_label = self._mode.upper()
        if self._mode == "draw":
            pts_hint = f"  {len(self._draw_pts)} pt(s)" if self._draw_pts else ""
            info += f"  ·  DRAW{pts_hint}"
        elif self._mode == "edit":
            info += "  ·  EDIT"
        self.create_text(
            8, 8, anchor="nw", text=info, fill=_DIM, font=("Helvetica", 10)
        )

        zoom_pct = int(round(self._scale / max(self._fit_scale, 1e-9) * 100))
        if self._mode == "draw":
            hint = "[click=add  ⌫=undo pt  dbl/Enter=finish  near start=close  Esc=cancel  D=exit]"
        elif self._mode == "edit":
            hint = "[drag vert  dbl-click edge=insert  right-click vert=delete  E=exit]"
        else:
            hint = "[F=fit  +/-=zoom  Del=delete  Esc=desel  M=measure  D=draw  E=edit]"
        self.create_text(
            8, h - 6, anchor="sw",
            text=f"{zoom_pct}%  {hint}",
            fill=_DIM, font=("Helvetica", 9),
        )

        if not self._polys and not self._draw_pts:
            self.create_text(
                w // 2, h // 2,
                text="Load a DXF file to preview",
                fill="#333366", font=("Helvetica", 13),
            )

        self._draw_measure_button(w)

        if self._measure_mode and self._measure_anchor and self._measure_hover:
            self._draw_measure_overlay()

        if self._cursor_wx is not None:
            self.create_text(
                w - 6, h - 6, anchor="se",
                text=f"{self._cursor_wx:.2f}, {self._cursor_wy:.2f} mm",
                fill=_DIM, font=("Helvetica", 10), tags=("cursor_pos",),
            )

    def _draw_bg_image(self) -> None:
        """Render the faded background image at the correct position and scale."""
        target_w = max(1, int(self._bg_w_mm * self._scale))
        target_h = max(1, int(self._bg_h_mm * self._scale))
        # Cap rendered size for performance
        max_dim = 1200
        if max(target_w, target_h) > max_dim:
            ratio = max_dim / max(target_w, target_h)
            target_w = max(1, int(target_w * ratio))
            target_h = max(1, int(target_h * ratio))
        # Rebuild cache if scale changed significantly
        if self._bg_tk is None or abs(self._scale - self._bg_cached_scale) > self._bg_cached_scale * 0.01:
            try:
                resized = self._bg_pil.resize((target_w, target_h), PILImage.LANCZOS)
                self._bg_tk = ImageTk.PhotoImage(resized)
                self._bg_cached_scale = self._scale
            except Exception:
                return
        # Place at world (0, h_mm) → screen coords for top-left of image
        cx, cy = self._w2c(0.0, self._bg_h_mm)
        self.create_image(cx, cy, image=self._bg_tk, anchor="nw", tags=("bg_img",))

    def _draw_edit_handles(self) -> None:
        """Draw vertex handles for all polylines in edit mode."""
        for pi, poly in enumerate(self._polys):
            for vi, pt in enumerate(poly):
                cx, cy = self._w2c(*pt)
                is_hover = self._hover_vert == (pi, vi)
                is_active = self._edit_dragging and self._edit_poly == pi and self._edit_vert == vi
                if is_active:
                    color = _HANDLE_ACTIVE
                    r = _HANDLE_R + 2
                elif is_hover:
                    color = _HANDLE_HOVER
                    r = _HANDLE_R + 1
                else:
                    color = _HANDLE
                    r = _HANDLE_R
                fill = color if (is_active or is_hover) else ""
                self.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    outline=color, fill=fill, width=1.5,
                )

    def _draw_in_progress_poly(self) -> None:
        """Draw the in-progress draw polygon with close-snap indicator."""
        pts_screen = [c for pt in self._draw_pts for c in self._w2c(*pt)]
        if len(pts_screen) >= 4:
            self.create_line(pts_screen, fill="#ffdd44", width=1.5)
        for i, pt in enumerate(self._draw_pts):
            cx, cy = self._w2c(*pt)
            # First point gets special treatment for close-snap
            if i == 0 and len(self._draw_pts) >= 3 and self._cursor_wx is not None:
                start_cx, start_cy = self._w2c(*self._draw_pts[0])
                cur_cx, cur_cy = self._w2c(self._cursor_wx, self._cursor_wy)
                dist = math.hypot(cur_cx - start_cx, cur_cy - start_cy)
                if dist < _SNAP_DIST:
                    # Highlight start with snap indicator
                    self.create_oval(
                        cx - 7, cy - 7, cx + 7, cy + 7,
                        outline=_SNAP_CLOSE, fill="", width=2,
                    )
                    # Dashed closing line from last point to start
                    last_cx, last_cy = self._w2c(*self._draw_pts[-1])
                    self.create_line(
                        last_cx, last_cy, start_cx, start_cy,
                        fill=_SNAP_CLOSE, width=1.0, dash=(4, 3),
                    )
            self.create_oval(
                cx - 3, cy - 3, cx + 3, cy + 3, fill="#ffdd44", outline=""
            )
        # Rubber-band to cursor
        if self._cursor_wx is not None and self._draw_pts:
            last = self._w2c(*self._draw_pts[-1])
            cur_c = self._w2c(self._cursor_wx, self._cursor_wy)
            self.create_line(
                last[0], last[1], cur_c[0], cur_c[1],
                fill="#ffdd44", width=1.0, dash=(3, 3),
            )

    # ── Interaction ───────────────────────────────────────────────────────────

    def _draw_measure_button(self, canvas_w: int) -> None:
        """Draw the Measure toggle button in the top-right corner."""
        pad, bh, bw = 6, 22, 114
        label = "✕ Measure [M]" if self._measure_mode else "⊕ Measure [M]"
        color = "#00d8ff" if self._measure_mode else _DIM
        bg = "#002233" if self._measure_mode else "#14141e"
        x1, y1 = canvas_w - bw - pad, pad
        x2, y2 = canvas_w - pad, pad + bh
        self.create_rectangle(
            x1, y1, x2, y2, fill=bg, outline=color, width=1, tags=("measure_btn",)
        )
        self.create_text(
            (x1 + x2) // 2,
            (y1 + y2) // 2,
            text=label,
            fill=color,
            font=("Helvetica", 10),
            tags=("measure_btn",),
        )
        self._mbtn_rect = (x1, y1, x2, y2)

    def _hit_measure_button(self, cx: int, cy: int) -> bool:
        x1, y1, x2, y2 = self._mbtn_rect
        return x1 <= cx <= x2 and y1 <= cy <= y2

    def _draw_measure_overlay(self) -> None:
        """Draw live ruler line + distance badge. Call only when anchor+hover are set."""
        ax, ay = self._measure_anchor
        hx, hy = self._measure_hover
        cax, cay = self._w2c(ax, ay)
        chx, chy = self._w2c(hx, hy)
        dist = math.hypot(hx - ax, hy - ay)
        dx = abs(hx - ax)
        dy = abs(hy - ay)

        TAG = "measure_overlay"

        # Dashed ruler line
        self.create_line(
            cax, cay, chx, chy, fill="#00d8ff", width=1.5, dash=(6, 3), tags=(TAG,)
        )

        # Anchor dot (open circle)
        r = 5
        self.create_oval(
            cax - r,
            cay - r,
            cax + r,
            cay + r,
            outline="#00d8ff",
            fill="#001522",
            width=2,
            tags=(TAG,),
        )
        # Crosshair tick lines at anchor
        self.create_line(
            cax - 8, cay, cax + 8, cay, fill="#00d8ff", width=1, tags=(TAG,)
        )
        self.create_line(
            cax, cay - 8, cax, cay + 8, fill="#00d8ff", width=1, tags=(TAG,)
        )

        # Hover dot (filled)
        self.create_oval(
            chx - 3,
            chy - 3,
            chx + 3,
            chy + 3,
            outline="#00d8ff",
            fill="#00d8ff",
            tags=(TAG,),
        )

        # Distance badge at midpoint
        mx, my = (cax + chx) / 2, (cay + chy) / 2
        line1 = f"{dist:.2f} mm"
        line2 = f"\u0394x {dx:.2f}  \u0394y {dy:.2f}"
        # Slightly offset so badge doesn't overlap the line
        badge_y = my - 28
        self.create_rectangle(
            mx - 80,
            badge_y - 10 - 4,
            mx + 80,
            badge_y + 14 + 4,
            fill="#001522",
            outline="#00d8ff",
            width=1,
            tags=(TAG,),
        )
        self.create_text(
            mx,
            badge_y - 6,
            text=line1,
            fill="#ffffff",
            font=("Helvetica", 11, "bold"),
            anchor="center",
            tags=(TAG,),
        )
        self.create_text(
            mx,
            badge_y + 8,
            text=line2,
            fill="#00d8ff",
            font=("Helvetica", 9),
            anchor="center",
            tags=(TAG,),
        )

    def _lmb_press_cb(self, ev: tk.Event) -> None:
        # Measure button hit-test (always, regardless of mode)
        if self._hit_measure_button(ev.x, ev.y):
            self.toggle_measure()
            return
        # Measure anchor placement
        if self._measure_mode:
            wx, wy = self._c2w(ev.x, ev.y)
            self._measure_anchor = (wx, wy)
            self._measure_hover = (wx, wy)
            self._draw()
            return

        # Edit mode: vertex grab
        if self._mode == "edit":
            wx, wy = self._c2w(ev.x, ev.y)
            hit = self._find_nearest_vertex(ev.x, ev.y)
            if hit is not None:
                pi, vi = hit
                self._push_undo()
                self._edit_poly = pi
                self._edit_vert = vi
                self._edit_dragging = True
                self._draw()
                return
            # No vertex hit → pan
            self._lmb_press = (ev.x, ev.y)
            self._lmb_prev = (ev.x, ev.y)
            return

        # Draw mode: click adds a point (with close-snap)
        if self._mode == "draw":
            wx, wy = self._c2w(ev.x, ev.y)
            # Close-snap: clicking near start point closes the polygon
            if len(self._draw_pts) >= 3:
                start_cx, start_cy = self._w2c(*self._draw_pts[0])
                if math.hypot(ev.x - start_cx, ev.y - start_cy) < _SNAP_DIST:
                    # Close polygon by appending start point
                    self._draw_pts.append(self._draw_pts[0])
                    self._finish_draw()
                    return
            self._draw_pts.append((wx, wy))
            self._draw()
            return

        # Select mode
        shift = bool(ev.state & 0x0001)
        if self._selectable and shift:
            self._shift_drag = True
            self._band_start = (ev.x, ev.y)
            self._lmb_press = None
            self._lmb_prev = None
            self._lmb_target = None
        else:
            self._shift_drag = False
            self._band_start = None
            self._lmb_press = (ev.x, ev.y)
            self._lmb_prev = (ev.x, ev.y)
            nearby = self.find_closest(ev.x, ev.y, halo=6)
            self._lmb_target = self._id2idx.get(nearby[0]) if nearby else None

    def _lmb_drag_cb(self, ev: tk.Event) -> None:
        if self._measure_mode:
            return
        # Edit mode: drag vertex
        if self._mode == "edit" and self._edit_dragging:
            wx, wy = self._c2w(ev.x, ev.y)
            self._polys[self._edit_poly][self._edit_vert] = (wx, wy)
            self._draw()
            return
        if self._mode == "draw":
            return
        if self._shift_drag and self._band_start:
            self._draw()
            bx1, by1 = self._band_start
            self.create_rectangle(
                bx1, by1, ev.x, ev.y,
                outline="#ff8800", fill="", dash=(4, 2), tags=("rubberband",),
            )
            return
        if self._lmb_prev:
            self._ox += ev.x - self._lmb_prev[0]
            self._oy += ev.y - self._lmb_prev[1]
            self._lmb_prev = (ev.x, ev.y)
            self._draw()

    def _lmb_release_cb(self, ev: tk.Event) -> None:
        if self._measure_mode:
            return
        # Edit mode: finish drag
        if self._mode == "edit" and self._edit_dragging:
            self._edit_dragging = False
            self._draw()
            self._notify()
            return
        if self._mode == "draw":
            return
        if self._shift_drag and self._band_start and self._selectable:
            bx1, by1 = self._band_start
            x1c, x2c = min(bx1, ev.x), max(bx1, ev.x)
            y1c, y2c = min(by1, ev.y), max(by1, ev.y)
            for idx, poly in enumerate(self._polys):
                pts_c = [self._w2c(x, y) for x, y in poly]
                if any(x1c <= cx <= x2c and y1c <= cy <= y2c for cx, cy in pts_c):
                    self._sel.add(idx)
            self._draw()
            self._notify()
            self._shift_drag = False
            self._band_start = None
            return
        if (
            self._selectable
            and self._lmb_press is not None
            and self._lmb_target is not None
        ):
            dx = ev.x - self._lmb_press[0]
            dy = ev.y - self._lmb_press[1]
            if abs(dx) <= _DRAG_THRESH and abs(dy) <= _DRAG_THRESH:
                idx = self._lmb_target
                self._sel.discard(idx) if idx in self._sel else self._sel.add(idx)
                self._draw()
                self._notify()
        self._lmb_press = None
        self._lmb_prev = None
        self._lmb_target = None
        self._shift_drag = False
        self._band_start = None

    def _lmb_double_cb(self, ev: tk.Event) -> None:
        # Draw mode: finish polygon
        if self._mode == "draw":
            wx, wy = self._c2w(ev.x, ev.y)
            self._draw_pts.append((wx, wy))
            self._finish_draw()
            return
        # Edit mode: insert vertex on nearest edge
        if self._mode == "edit":
            hit = self._find_nearest_edge(ev.x, ev.y)
            if hit is not None:
                pi, seg_idx, pt = hit
                self._push_undo()
                self._polys[pi].insert(seg_idx + 1, pt)
                self._draw()
                self._notify()
            return

    def _mmb_drag_cb(self, ev: tk.Event) -> None:
        if self._mmb_prev:
            self._ox += ev.x - self._mmb_prev[0]
            self._oy += ev.y - self._mmb_prev[1]
            self._mmb_prev = (ev.x, ev.y)
            self._draw()

    def _scroll_cb(self, ev: tk.Event) -> str:
        factor = 1.15 if (ev.num == 4 or getattr(ev, "delta", 0) > 0) else 1 / 1.15
        wx, wy = self._c2w(ev.x, ev.y)
        self._scale *= factor
        self._ox = ev.x - wx * self._scale
        self._oy = ev.y + wy * self._scale
        self._draw()
        return "break"

    @staticmethod
    def _class_wheel_cb(ev: tk.Event) -> str:
        live: list = []
        match: DxfCanvas | None = None
        for ref in DxfCanvas._registry:
            canvas = ref()
            if canvas is None:
                continue
            try:
                if not canvas.winfo_exists():
                    continue
            except Exception:
                continue
            live.append(ref)
            try:
                if canvas.winfo_containing(ev.x_root, ev.y_root) is canvas:
                    match = canvas
            except Exception:
                pass
        DxfCanvas._registry[:] = live

        if match is not None:
            ev.x = ev.x_root - match.winfo_rootx()
            ev.y = ev.y_root - match.winfo_rooty()
            match._scroll_cb(ev)
            return "break"

        try:
            target = ev.widget.winfo_containing(ev.x_root, ev.y_root)
            delta = getattr(ev, "delta", 0)
            if ev.num == 4:
                delta = 120
            elif ev.num == 5:
                delta = -120
            if delta:
                # macOS trackpad: delta is small (±1‥5) — use directly.
                # Windows / Linux: delta is ±120 per notch — normalise.
                units = -delta if abs(delta) < 20 else -int(delta / 40)
                w = target
                while w is not None:
                    # CTkScrollableFrame owns a _parent_canvas (tk.Canvas
                    # configured with yscrollcommand).  Walk up until we
                    # find one.  Plain CTk background canvases lack this
                    # attribute and are skipped.
                    pc = getattr(w, "_parent_canvas", None)
                    if pc is not None and hasattr(pc, "yview_scroll"):
                        pc.yview_scroll(units, "units")
                        break
                    w = getattr(w, "master", None)
        except Exception:
            pass
        return "break"

    def _zoom_by(self, factor: float) -> None:
        w, h = max(self.winfo_width(), 100), max(self.winfo_height(), 100)
        cx, cy = w / 2, h / 2
        wx, wy = self._c2w(cx, cy)
        self._scale *= factor
        self._ox = cx - wx * self._scale
        self._oy = cy + wy * self._scale
        self._draw()

    def _motion_cb(self, ev: tk.Event) -> None:
        wx, wy = self._c2w(ev.x, ev.y)
        self._cursor_wx = wx
        self._cursor_wy = wy
        h = max(self.winfo_height(), 100)
        w = max(self.winfo_width(), 100)

        # Draw mode: full redraw for rubber-band
        if self._mode == "draw" and self._draw_pts:
            self._draw()
            return

        # Edit mode: update hover vertex for visual feedback
        if self._mode == "edit":
            old_hover = self._hover_vert
            self._hover_vert = self._find_nearest_vertex(ev.x, ev.y)
            if self._hover_vert != old_hover or self._edit_dragging:
                self._draw()
                return

        if self._measure_mode and self._measure_anchor is not None:
            self._measure_hover = (wx, wy)
            self.delete("measure_overlay")
            self.delete("cursor_pos")
            self._draw_measure_overlay()
            self.create_text(
                w - 6, h - 6, anchor="se",
                text=f"{wx:.2f}, {wy:.2f} mm",
                fill=_DIM, font=("Helvetica", 10), tags=("cursor_pos",),
            )
            return

        # Default lightweight update: only refresh the coordinate overlay
        self.delete("cursor_pos")
        self.create_text(
            w - 6, h - 6, anchor="se",
            text=f"{wx:.2f}, {wy:.2f} mm",
            fill=_DIM, font=("Helvetica", 10), tags=("cursor_pos",),
        )

    def _rightclick_cb(self, ev: tk.Event) -> None:
        # Draw mode: right-click finishes polygon  
        if self._mode == "draw" and len(self._draw_pts) >= 2:
            self._finish_draw()
            return

        # Edit mode: right-click near vertex → delete it
        if self._mode == "edit":
            hit = self._find_nearest_vertex(ev.x, ev.y)
            if hit is not None:
                pi, vi = hit
                poly = self._polys[pi]
                if len(poly) <= 3:
                    # Too few vertices — delete entire poly
                    self._push_undo()
                    self._polys.pop(pi)
                    self._sel = {i - (1 if i > pi else 0) for i in self._sel if i != pi}
                else:
                    self._push_undo()
                    poly.pop(vi)
                self._hover_vert = None
                self._draw()
                self._notify()
                return

        # Default: context menu (select mode)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Select All  [Shift+drag]", command=self.select_all)
        menu.add_command(label="Deselect All  [Esc]", command=self.deselect_all)
        menu.add_command(label="Invert Selection", command=self.invert_selection)
        if self._undo_stack:
            menu.add_separator()
            menu.add_command(label="Undo  [Ctrl+Z]", command=self.undo)
        if self._sel:
            menu.add_separator()
            menu.add_command(
                label=f"Delete {len(self._sel)} selected  [Del]",
                command=self.delete_selected,
            )
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            menu.grab_release()
        self._draw()

    # ── Edit mode hit-testing ─────────────────────────────────────────────────

    def _find_nearest_vertex(self, cx: int, cy: int) -> tuple[int, int] | None:
        """Find the vertex nearest to screen coords (cx, cy) within _VERT_HIT px."""
        best_dist = _VERT_HIT + 1
        best = None
        for pi, poly in enumerate(self._polys):
            for vi, pt in enumerate(poly):
                sx, sy = self._w2c(*pt)
                d = math.hypot(cx - sx, cy - sy)
                if d < best_dist:
                    best_dist = d
                    best = (pi, vi)
        return best

    def _find_nearest_edge(self, cx: int, cy: int) -> tuple[int, int, tuple[float, float]] | None:
        """Find the edge nearest to screen coords. Returns (poly_idx, seg_idx, world_point)."""
        best_dist = _EDGE_HIT + 1
        best = None
        for pi, poly in enumerate(self._polys):
            for si in range(len(poly) - 1):
                ax, ay = self._w2c(*poly[si])
                bx, by = self._w2c(*poly[si + 1])
                d, t = self._point_seg_dist(cx, cy, ax, ay, bx, by)
                if d < best_dist:
                    best_dist = d
                    # Compute world point on the segment
                    wx0, wy0 = poly[si]
                    wx1, wy1 = poly[si + 1]
                    pt = (wx0 + t * (wx1 - wx0), wy0 + t * (wy1 - wy0))
                    best = (pi, si, pt)
        return best

    @staticmethod
    def _point_seg_dist(px, py, ax, ay, bx, by) -> tuple[float, float]:
        """Distance from point (px,py) to segment (ax,ay)-(bx,by). Returns (dist, t)."""
        dx, dy = bx - ax, by - ay
        len_sq = dx * dx + dy * dy
        if len_sq < 1e-12:
            return math.hypot(px - ax, py - ay), 0.0
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
        nx, ny = ax + t * dx, ay + t * dy
        return math.hypot(px - nx, py - ny), t

    def _notify(self) -> None:
        if self._on_change:
            self._on_change(self.sel_count)
