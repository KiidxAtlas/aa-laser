"""Image-to-outline tracing — converts a raster image to polyline lists.

Dependencies: Pillow (already required), numpy (shapely transitive dep).

Pipeline
--------
1. _load_image        — load, composite on white, downscale, return gray array
2. _threshold_mask    — threshold → filled binary mask (dark objects by default)
3. _morph_close       — optional PIL-based morphological closing to fill gaps
4. _marching_squares  — ISO-contour extraction → clean closed polygons
5. simplify_contours  — Ramer-Douglas-Peucker
6. filter_contours    — drop by area (min / optional max)
7. scale_to_mm        — pixel coords → millimetres
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageFilter

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

Poly = list[tuple[float, float]]

# ---------------------------------------------------------------------------
# Step 1 — load image
# ---------------------------------------------------------------------------


def _load_image(path: str, max_px: int = 1200) -> tuple[Image.Image, np.ndarray]:
    """Load image, composite on white, downscale; return (rgb_img, gray_array)."""
    img = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")
    w, h = img.size
    scale = min(max_px / max(w, h, 1), 1.0)
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    gray = np.array(img.convert("L"), dtype=np.uint8)
    return img, gray


# ---------------------------------------------------------------------------
# Step 2 — hard-threshold binary (filled mask)
# ---------------------------------------------------------------------------


def _otsu_threshold(gray: np.ndarray) -> int:
    """Compute Otsu's optimal binarisation threshold from a grayscale array."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = float(gray.size)
    sum_all = float(np.dot(np.arange(256, dtype=float), hist))
    sum_fg, count_fg, best_var, best_t = 0.0, 0.0, 0.0, 128
    for t in range(256):
        count_fg += hist[t]
        if count_fg == 0:
            continue
        count_bg = total - count_fg
        if count_bg == 0:
            break
        sum_fg += t * hist[t]
        mean_fg = sum_fg / count_fg
        mean_bg = (sum_all - sum_fg) / count_bg
        var = count_fg * count_bg * (mean_fg - mean_bg) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def _threshold_mask(
    gray: np.ndarray,
    blur: float = 1.5,
    threshold: int | None = None,
    invert: bool = False,
) -> np.ndarray:
    """
    Apply blur + threshold, return a filled binary mask.

    ``invert=False`` (default) — dark pixels are foreground.  Use this for
    dark objects on a white/light background (most gun-outline photos).

    ``invert=True``            — bright pixels are foreground.

    ``threshold=None``         — auto-select using Otsu's method.
    """
    img = Image.fromarray(gray)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    arr = np.array(img, dtype=np.uint8)
    t = _otsu_threshold(arr) if threshold is None else int(threshold)
    fg = (arr > t) if invert else (arr <= t)
    return fg.astype(np.uint8)


# ---------------------------------------------------------------------------
# Marching squares contour extraction (threshold mode)
# ---------------------------------------------------------------------------

# Lookup table: config (TL<<3 | TR<<2 | BR<<1 | BL) → list of (ea, eb) edge pairs.
# Edge indices: 0=top, 1=right, 2=bottom, 3=left.
# The two edges for each segment are the midpoints that the iso-contour passes through.
_MS_SEGS: list[list[tuple[int, int]]] = [
    [],  # 0:  ....
    [(3, 2)],  # 1:  ...X  BL
    [(2, 1)],  # 2:  ..X.  BR
    [(3, 1)],  # 3:  ..XX  BL,BR
    [(0, 1)],  # 4:  .X..  TR
    [(0, 1), (3, 2)],  # 5:  .X.X  TR,BL  (saddle-A)
    [(0, 2)],  # 6:  .XX.  TR,BR
    [(0, 3)],  # 7:  .XXX  TR,BR,BL
    [(3, 0)],  # 8:  X...  TL
    [(0, 2)],  # 9:  X..X  TL,BL
    [(3, 0), (2, 1)],  # 10: X.X.  TL,BR  (saddle-A)
    [(0, 1)],  # 11: X.XX  TL,BL,BR
    [(3, 1)],  # 12: XX..  TL,TR
    [(1, 2)],  # 13: XX.X  TL,TR,BL
    [(3, 2)],  # 14: XXX.  TL,TR,BR
    [],  # 15: XXXX
]


def _marching_squares(filled: np.ndarray) -> list[Poly]:
    """
    Extract closed iso-contours from a binary filled mask using marching squares.

    Returns polylines as (x, y) float coordinates with y pointing upward and
    origin at the lower-left corner of the image.  Pixel scale (1 unit = 1 px).

    The mask is padded by one pixel on each side so that shapes touching the
    image border produce properly closed contours.
    """
    # Pad with zeros so every shape gets a closed contour.
    p = np.pad(filled.astype(np.uint8), 1, mode="constant", constant_values=0)
    ph, pw = p.shape
    orig_h = ph - 2  # original image height (rows)

    # Vectorised config computation over every 2×2 cell.
    tl = p[:-1, :-1].astype(np.uint16)
    tr = p[:-1, 1:].astype(np.uint16)
    br = p[1:, 1:].astype(np.uint16)
    bl = p[1:, :-1].astype(np.uint16)
    config = (tl << 3) | (tr << 2) | (br << 1) | bl

    # Edge midpoints are stored in a 2× integer coordinate system so we can
    # use integer tuples as dictionary keys without float precision issues.
    # For cell (r, c):
    #   TOP    midpoint → (2r,   2c+1)
    #   RIGHT  midpoint → (2r+1, 2c+2)
    #   BOTTOM midpoint → (2r+2, 2c+1)
    #   LEFT   midpoint → (2r+1, 2c  )
    _MIDPT = (
        lambda r, c: (2 * r, 2 * c + 1),  # 0 top
        lambda r, c: (2 * r + 1, 2 * c + 2),  # 1 right
        lambda r, c: (2 * r + 2, 2 * c + 1),  # 2 bottom
        lambda r, c: (2 * r + 1, 2 * c),  # 3 left
    )

    # Build segment list and per-endpoint adjacency map.
    segs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    adj: dict[tuple[int, int], list[tuple[int, tuple[int, int]]]] = {}

    for r, c in zip(*np.where((config > 0) & (config < 15))):
        r, c = int(r), int(c)
        for ea, eb in _MS_SEGS[int(config[r, c])]:
            pa = _MIDPT[ea](r, c)
            pb = _MIDPT[eb](r, c)
            idx = len(segs)
            segs.append((pa, pb))
            adj.setdefault(pa, []).append((idx, pb))
            adj.setdefault(pb, []).append((idx, pa))

    # Chain segments into closed (or open) polylines.
    used: set[int] = set()
    chains: list[list[tuple[int, int]]] = []

    for i, (p1, p2) in enumerate(segs):
        if i in used:
            continue
        used.add(i)
        chain: list[tuple[int, int]] = [p1, p2]

        # Extend forward from p2 until the loop closes or we dead-end.
        while True:
            tail = chain[-1]
            nexts = [(j, pt) for j, pt in adj.get(tail, []) if j not in used]
            if not nexts:
                break
            j, pt = nexts[0]
            used.add(j)
            if pt == chain[0]:
                break  # closed
            chain.append(pt)

        if len(chain) >= 4:
            chains.append(chain)

    # Convert 2× padded-grid (R, C) → original image (x, y) with y pointing up.
    # R/2 is the padded-grid row; subtract 1 for padding offset.
    # C/2 is the padded-grid col; subtract 1 for padding offset.
    # x = C/2 − 1
    # y = orig_h − (R/2 − 1) = orig_h + 1 − R/2  (y-up, origin at bottom-left)
    polys: list[Poly] = []
    for chain in chains:
        poly = [(C / 2.0 - 1.0, orig_h + 1.0 - R / 2.0) for R, C in chain]
        polys.append(poly)

    return polys


# ---------------------------------------------------------------------------
# Step 3 — morphological close (fill small gaps)
# ---------------------------------------------------------------------------


def _morph_close(binary: np.ndarray, radius: int) -> np.ndarray:
    """Morphological close: PIL MaxFilter (dilate) then MinFilter (erode)."""
    if radius <= 0:
        return binary
    sz = radius * 2 + 1
    img = Image.fromarray(binary.astype(np.uint8) * 255)
    dilated = img.filter(ImageFilter.MaxFilter(sz))
    closed = dilated.filter(ImageFilter.MinFilter(sz))
    return (np.array(closed) > 0).astype(np.uint8)


# ---------------------------------------------------------------------------
# Step 4 — Ramer-Douglas-Peucker simplification
# ---------------------------------------------------------------------------


def _rdp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    if len(pts) <= 2:
        return list(pts)
    arr = np.array(pts, dtype=float)
    start, end = arr[0], arr[-1]
    seg = end - start
    seg_len = math.hypot(seg[0], seg[1])
    if seg_len < 1e-12:
        dists = np.linalg.norm(arr - start, axis=1)
    else:
        seg_unit = seg / seg_len
        vecs = arr - start
        projs = vecs @ seg_unit
        perps = vecs - np.outer(projs, seg_unit)
        dists = np.linalg.norm(perps, axis=1)
    idx = int(np.argmax(dists))
    if dists[idx] <= tol:
        return [pts[0], pts[-1]]
    left = _rdp(pts[: idx + 1], tol)
    right = _rdp(pts[idx:], tol)
    return left[:-1] + right


def simplify_contours(contours: list[Poly], tolerance: float = 1.0) -> list[Poly]:
    """Ramer-Douglas-Peucker simplification."""
    result = []
    for pts in contours:
        simplified = _rdp(pts, tolerance)
        if len(simplified) >= 3:
            result.append(simplified)
    return result


# ---------------------------------------------------------------------------
# Step 5 — area filtering
# ---------------------------------------------------------------------------


def _shoelace_area(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    if n < 3:
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    area = sum(xs[i] * ys[(i + 1) % n] - xs[(i + 1) % n] * ys[i] for i in range(n))
    return abs(area) / 2.0


def filter_contours(
    contours: list[Poly],
    min_area_px: float = 100.0,
    max_area_px: float | None = None,
) -> list[Poly]:
    """Filter contours by pixel-space area."""
    result = []
    for c in contours:
        a = _shoelace_area(c)
        if a < min_area_px:
            continue
        if max_area_px is not None and a > max_area_px:
            continue
        result.append(c)
    return result


# ---------------------------------------------------------------------------
# Step 6 — scale to mm
# ---------------------------------------------------------------------------


def scale_to_mm(
    contours: list[Poly],
    px_per_mm: float,
    img_height_px: int,
) -> list[Poly]:
    """Convert pixel-space (x, y) coordinates to millimetres."""
    if px_per_mm <= 0:
        return contours
    return [[(x / px_per_mm, y / px_per_mm) for x, y in poly] for poly in contours]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def image_to_outlines(
    path: str,
    *,
    blur_radius: float = 1.5,
    threshold: int | None = 128,
    invert: bool = False,
    close_radius: int = 1,
    simplify_tol: float = 2.0,
    min_area_px: float = 100.0,
    max_area_px: float | None = None,
    width_mm: float = 50.0,
    max_px: int = 1200,
) -> tuple[Image.Image, list[Poly], int, int]:
    """
    Run the full pipeline.

    Returns ``(display_image, mm_polylines, img_w_px, img_h_px)``.

    ``img_w_px`` / ``img_h_px`` are the *processed* (possibly downscaled)
    image dimensions — useful for computing the actual mm size of the image.
    """
    display_img, gray = _load_image(path, max_px)
    img_w_px = gray.shape[1]
    img_h_px = gray.shape[0]

    mask = _threshold_mask(gray, blur_radius, threshold, invert)
    if close_radius > 0:
        mask = _morph_close(mask, close_radius)
    contours = _marching_squares(mask)

    contours = simplify_contours(contours, simplify_tol)
    contours = filter_contours(contours, min_area_px, max_area_px)

    px_per_mm = img_w_px / max(width_mm, 0.001)
    return display_img, scale_to_mm(contours, px_per_mm, img_h_px), img_w_px, img_h_px
