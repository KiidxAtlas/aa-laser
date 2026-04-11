"""Image-to-outline tracing — converts a raster image to polyline lists.

Dependencies: Pillow (already required), numpy (shapely transitive dep).

Modes
-----
``"edges"``     Canny-style gradient edge detection.  Best for photographs.
``"threshold"`` Hard threshold on grayscale value.  Best for clean silhouettes.

Pipeline (threshold mode)
--------------------------
1. _load_image        — load, composite on white, downscale, return gray array
2. _threshold_mask    — threshold → filled binary mask (dark objects by default)
3. _morph_close       — optional PIL-based morphological closing to fill gaps
4. _marching_squares  — ISO-contour extraction → clean closed polygons
5. simplify_contours  — Ramer-Douglas-Peucker
6. filter_contours    — drop by area (min / optional max)
7. scale_to_mm        — pixel coords → millimetres

Pipeline (edges mode)
----------------------
Steps 1–4 differ: Canny gradient edges → component labeling → greedy chain trace.
Same simplify/filter/scale pipeline follows.
"""

from __future__ import annotations

import math
from collections import deque

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
# Step 2a — Canny-style edge detection
# ---------------------------------------------------------------------------


def _sobel_gradients(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized Sobel: returns (gx, gy, magnitude)."""
    p = np.pad(arr.astype(float), 1, mode="reflect")
    gx = (
        -p[:-2, :-2]
        + p[:-2, 2:]
        - 2 * p[1:-1, :-2]
        + 2 * p[1:-1, 2:]
        - p[2:, :-2]
        + p[2:, 2:]
    )
    gy = (
        -p[:-2, :-2]
        - 2 * p[:-2, 1:-1]
        - p[:-2, 2:]
        + p[2:, :-2]
        + 2 * p[2:, 1:-1]
        + p[2:, 2:]
    )
    return gx, gy, np.hypot(gx, gy)


def _nms(mag: np.ndarray, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    """Vectorised non-maximum suppression — thins edges to 1 pixel width."""
    angle = np.arctan2(gy, gx) * 180.0 / np.pi % 180.0
    qa = ((angle + 22.5) / 45.0).astype(int) % 4
    pm = np.pad(mag, 1, mode="constant")
    n1 = np.zeros_like(mag)
    n2 = np.zeros_like(mag)
    m0 = qa == 0
    n1[m0] = pm[1:-1, 2:][m0]
    n2[m0] = pm[1:-1, :-2][m0]
    m1 = qa == 1
    n1[m1] = pm[:-2, 2:][m1]
    n2[m1] = pm[2:, :-2][m1]
    m2 = qa == 2
    n1[m2] = pm[:-2, 1:-1][m2]
    n2[m2] = pm[2:, 1:-1][m2]
    m3 = qa == 3
    n1[m3] = pm[:-2, :-2][m3]
    n2[m3] = pm[2:, 2:][m3]
    return np.where((mag >= n1) & (mag >= n2), mag, 0.0)


def _canny_binary(
    gray: np.ndarray,
    sigma: float = 1.5,
    lo_pct: float = 0.5,
    hi_pct: float = 0.8,
) -> np.ndarray:
    """
    Canny-style edge detection → binary (0/1) edge mask.

    lo_pct / hi_pct are percentiles of the non-zero NMS magnitude.
    hi_pct=0.8 keeps the top 20 % as strong edges; lo_pct=0.5 allows the
    top 50 % to be included as weak (hysteresis-connected) edges.
    """
    blurred = Image.fromarray(gray)
    if sigma > 0:
        blurred = blurred.filter(ImageFilter.GaussianBlur(radius=sigma))
    arr = np.array(blurred, dtype=float)

    gx, gy, mag = _sobel_gradients(arr)
    thin = _nms(mag, gx, gy)

    nz = thin[thin > 0]
    if nz.size == 0:
        return np.zeros_like(thin, dtype=np.uint8)

    lo_val = float(np.percentile(nz, lo_pct * 100))
    hi_val = float(np.percentile(nz, hi_pct * 100))

    strong = (thin >= hi_val).astype(np.uint8)
    weak = ((thin >= lo_val) & (thin < hi_val)).astype(np.uint8)

    # Hysteresis: grow strong regions to include touching weak pixels
    strong_img = Image.fromarray(strong * 255)
    dilated = np.array(strong_img.filter(ImageFilter.MaxFilter(3))) > 0
    return ((strong > 0) | (weak.astype(bool) & dilated)).astype(np.uint8)


# ---------------------------------------------------------------------------
# Step 2b — hard-threshold binary (filled mask)
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
# Step 4 — connected-component labeling (BFS, 8-connected)
# ---------------------------------------------------------------------------


def _label_components(binary: np.ndarray) -> tuple[np.ndarray, int]:
    """BFS 8-connected labeling.  Returns (label_array, n_labels)."""
    h, w = binary.shape
    labels = np.zeros((h, w), dtype=np.int32)
    N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    curr = 0
    rows, cols = np.where(binary > 0)
    for r0, c0 in zip(rows.tolist(), cols.tolist()):
        if labels[r0, c0]:
            continue
        curr += 1
        q: deque[tuple[int, int]] = deque([(r0, c0)])
        labels[r0, c0] = curr
        while q:
            r, c = q.popleft()
            for dr, dc in N8:
                nr, nc = r + dr, c + dc
                if (
                    0 <= nr < h
                    and 0 <= nc < w
                    and binary[nr, nc]
                    and not labels[nr, nc]
                ):
                    labels[nr, nc] = curr
                    q.append((nr, nc))
    return labels, curr


# ---------------------------------------------------------------------------
# Step 5 — per-component greedy chain trace
# ---------------------------------------------------------------------------

# Clockwise 8-neighbourhood starting from East
_CW8 = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
_CW8_IDX = {d: i for i, d in enumerate(_CW8)}


def _trace_component(
    remaining: np.ndarray,
    start: tuple[int, int],
    h: int,
    w: int,
) -> list[tuple[int, int]]:
    """
    Greedy 8-connected walk of one connected component.

    Prefers continuing in the same direction first; never immediately
    reverses, which keeps the output polyline smooth.
    """
    chain = [start]
    remaining[start] = False
    pos = start
    entry: tuple[int, int] | None = None

    while True:
        r, c = pos
        if entry is None:
            order = _CW8
        else:
            rev = (-entry[0], -entry[1])
            si = _CW8_IDX.get(entry, 0)
            order = [_CW8[(si + i) % 8] for i in range(8) if _CW8[(si + i) % 8] != rev]

        moved = False
        for dr, dc in order:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and remaining[nr, nc]:
                chain.append((nr, nc))
                remaining[nr, nc] = False
                pos = (nr, nc)
                entry = (dr, dc)
                moved = True
                break

        if not moved:
            break

    return chain


def _extract_contours(binary: np.ndarray) -> list[Poly]:
    """Label connected components and trace each one independently."""
    labels, n = _label_components(binary)
    h, w = binary.shape
    contours: list[Poly] = []

    for lab in range(1, n + 1):
        mask = labels == lab
        rows, cols = np.where(mask)
        if len(rows) < 6:
            continue

        remaining = mask.copy()
        start = (int(rows[0]), int(cols[0]))  # topmost-leftmost pixel
        chain = _trace_component(remaining, start, h, w)
        if len(chain) < 6:
            continue

        # Close the loop if endpoints are spatially close
        r0, c0 = chain[0]
        rl, cl = chain[-1]
        if abs(r0 - rl) <= 2 and abs(c0 - cl) <= 2:
            chain.append((r0, c0))

        # (row, col) → (x, y) with y pointing upward
        contours.append([(float(c), float(h - r)) for r, c in chain])

    return contours


# ---------------------------------------------------------------------------
# Step 6 — Ramer-Douglas-Peucker simplification
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
# Step 7 — area filtering
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
# Step 8 — scale to mm
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
    mode: str = "edges",
    # threshold-mode params
    blur_radius: float = 1.5,
    threshold: int | None = 128,
    invert: bool = False,
    # edges-mode params
    sigma: float = 1.5,
    canny_lo: float = 0.5,
    canny_hi: float = 0.8,
    # shared
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

    if mode == "edges":
        binary = _canny_binary(gray, sigma, canny_lo, canny_hi)
        if close_radius > 0:
            binary = _morph_close(binary, close_radius)
        contours = _extract_contours(binary)
    else:
        mask = _threshold_mask(gray, blur_radius, threshold, invert)
        if close_radius > 0:
            mask = _morph_close(mask, close_radius)
        contours = _marching_squares(mask)

    contours = simplify_contours(contours, simplify_tol)
    contours = filter_contours(contours, min_area_px, max_area_px)

    px_per_mm = img_w_px / max(width_mm, 0.001)
    return display_img, scale_to_mm(contours, px_per_mm, img_h_px), img_w_px, img_h_px
