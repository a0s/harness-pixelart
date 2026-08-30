"""Raster I/O and resampling.

Pillow is used when available (any format, best quality); otherwise the module
falls back to the stdlib PNG reader in pxa.py so the core pipeline never breaks.
"""

import os
import pxa

try:
    from PIL import Image  # noqa
    HAVE_PIL = True
except Exception:
    Image = None
    HAVE_PIL = False


def load_image(path):
    """-> (pixels, w, h) where pixels is a list of rows of (r,g,b,a)."""
    if not os.path.exists(path):
        raise pxa.PxaError("no such image: %s" % path)
    if HAVE_PIL:
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        data = list(im.getdata())
        return [[data[y * w + x] for x in range(w)] for y in range(h)], w, h
    if path.lower().endswith(".png"):
        rows = pxa.read_png(path)
        return rows, (len(rows[0]) if rows else 0), len(rows)
    raise pxa.PxaError(
        "reading %s needs Pillow -- run `px doctor --install`" % os.path.basename(path))


def save_image(path, pixels, upscale=1):
    return pxa.write_png(path, pixels, upscale)


def size_of(pixels):
    h = len(pixels)
    return ((len(pixels[0]) if h else 0), h)


def crop(pixels, x, y, w, h):
    return [[pixels[y + j][x + i] for i in range(w)] for j in range(h)]


def paste(dst, src, x, y, blend=True):
    """In-place alpha-composite of src onto dst at (x, y)."""
    dh = len(dst); dw = len(dst[0]) if dh else 0
    for j, row in enumerate(src):
        ty = y + j
        if not (0 <= ty < dh):
            continue
        for i, px in enumerate(row):
            tx = x + i
            if not (0 <= tx < dw):
                continue
            if not blend or px[3] == 255:
                dst[ty][tx] = px
            elif px[3] == 0:
                continue
            else:
                a = px[3] / 255.0
                b = dst[ty][tx]
                dst[ty][tx] = (int(px[0] * a + b[0] * (1 - a)),
                               int(px[1] * a + b[1] * (1 - a)),
                               int(px[2] * a + b[2] * (1 - a)),
                               max(px[3], b[3]))
    return dst


def new_image(w, h, color=(0, 0, 0, 0)):
    return [[color for _ in range(w)] for _ in range(h)]


def nearest_resize(pixels, w, h):
    sw, sh = size_of(pixels)
    if sw == w and sh == h:
        return [list(r) for r in pixels]
    return [[pixels[min(sh - 1, y * sh // h)][min(sw - 1, x * sw // w)]
             for x in range(w)] for y in range(h)]


def box_resize(pixels, w, h):
    """Area-average downscale -- the correct first step when turning a photo or
    an AI render into pixel art (nearest-neighbour would alias badly)."""
    sw, sh = size_of(pixels)
    if sw == w and sh == h:
        return [list(r) for r in pixels]
    if HAVE_PIL:
        im = Image.new("RGBA", (sw, sh))
        im.putdata([px for row in pixels for px in row])
        im = im.resize((w, h), Image.BOX if sw >= w else Image.LANCZOS)
        data = list(im.getdata())
        return [[data[y * w + x] for x in range(w)] for y in range(h)]
    out = []
    for y in range(h):
        y0, y1 = y * sh // h, max(y * sh // h + 1, (y + 1) * sh // h)
        row = []
        for x in range(w):
            x0, x1 = x * sw // w, max(x * sw // w + 1, (x + 1) * sw // w)
            r = g = b = a = n = 0
            for yy in range(y0, min(y1, sh)):
                for xx in range(x0, min(x1, sw)):
                    p = pixels[yy][xx]
                    wgt = p[3] / 255.0
                    r += p[0] * wgt; g += p[1] * wgt; b += p[2] * wgt
                    a += p[3]; n += wgt
            cnt = max(1, (min(y1, sh) - y0) * (min(x1, sw) - x0))
            if n <= 0:
                row.append((0, 0, 0, 0))
            else:
                row.append((int(r / n), int(g / n), int(b / n), int(a / cnt)))
        out.append(row)
    return out


def _exact_block_scale(pixels, max_scale=32, tolerance=0.985):
    """Strict pass: a candidate scale is valid when almost every s-by-s block
    is a single flat colour. The largest valid candidate is the true block
    size -- smaller divisors of it are also valid, and larger multiples
    straddle two original pixels and fail. Returns 1 when no candidate holds."""
    w, h = size_of(pixels)
    if w < 4 or h < 4:
        return 1
    best = 1
    for s in range(2, min(max_scale, w, h) + 1):
        if w % s or h % s:
            continue
        blocks = uniform = 0
        step = max(1, (w // s) // 24)          # sample columns of blocks on big images
        for by in range(0, h // s, max(1, (h // s) // 24)):
            for bx in range(0, w // s, step):
                blocks += 1
                ref = pixels[by * s][bx * s]
                flat = True
                for y in range(by * s, by * s + s):
                    row = pixels[y]
                    for x in range(bx * s, bx * s + s):
                        if row[x] != ref:
                            flat = False
                            break
                    if not flat:
                        break
                if flat:
                    uniform += 1
        if blocks and uniform / float(blocks) >= tolerance:
            best = s
    return best


def _gray_value(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def _edge_profiles(pixels, w, h, cap=600):
    """Summed absolute horizontal/vertical luminance-difference profiles, one
    value per column boundary (gx) and per row boundary (gy). The axis being
    profiled is kept at full resolution; the *other* axis is subsampled on
    big images so this stays fast without hurting period detection."""
    row_step = max(1, h // cap) if h > cap else 1
    col_step = max(1, w // cap) if w > cap else 1
    gx = [0.0] * max(0, w - 1)
    for y in range(0, h, row_step):
        row = pixels[y]
        prev = _gray_value(row[0])
        for x in range(1, w):
            g = _gray_value(row[x])
            gx[x - 1] += abs(g - prev)
            prev = g
    gy = [0.0] * max(0, h - 1)
    for x in range(0, w, col_step):
        prev = _gray_value(pixels[0][x])
        for y in range(1, h):
            g = _gray_value(pixels[y][x])
            gy[y - 1] += abs(g - prev)
            prev = g
    return gx, gy


def _phase_concentration(profile, s):
    """Best fraction of the total edge energy in `profile` that lands on any
    single residue class modulo s (tries every phase, keeps the best)."""
    total = sum(profile)
    if total <= 0:
        return 0.0
    best = 0.0
    for phase in range(s):
        e = sum(profile[i] for i in range(phase, len(profile), s))
        frac = e / total
        if frac > best:
            best = frac
    return best


def detect_pixel_scale_report(pixels, max_scale=32, tolerance=0.985,
                              min_side=64, concentration_ratio=1.6):
    """Guess the size of the 'logical pixel' in an image that was upscaled from
    real pixel art (or a JPEG re-encode of one), and report how confident the
    guess is.

    First pass: the strict block test (see `_exact_block_scale`). It fails on
    JPEG references because re-encoding blurs block edges, so a second,
    tolerant pass runs when it reports 1 and the image is big enough: on the
    luminance image, sum the absolute column-to-column and row-to-row
    difference to get an edge-energy profile per axis, then test candidate
    scales 2..12 by how much of that energy concentrates on columns/rows that
    share one phase modulo s. A true block size makes that concentration much
    higher than the 1/s a uniform image would give; both axes must agree, and
    the smallest passing scale wins (its multiples pass too, for the same
    reason a divisor of the true block size passes the strict test)."""
    w, h = size_of(pixels)
    if w < 4 or h < 4:
        return {"scale": 1, "method": "none", "confidence": 1.0, "hint_scale": None}
    exact = _exact_block_scale(pixels, max_scale, tolerance)
    if exact > 1:
        return {"scale": exact, "method": "exact", "confidence": 1.0, "hint_scale": None}
    if w < min_side or h < min_side:
        return {"scale": 1, "method": "none", "confidence": 1.0, "hint_scale": None}
    gx, gy = _edge_profiles(pixels, w, h)
    best_hint, best_hint_ratio = None, 1.05     # a floor so pure noise never hints
    for s in range(2, 13):
        if len(gx) < s or len(gy) < s:
            continue
        cx = _phase_concentration(gx, s)
        cy = _phase_concentration(gy, s)
        ratio = min(cx, cy) * s
        # s=8 (and its multiple 16) are JPEG's own 8x8 DCT macroblock grid --
        # they show up as a periodicity in *every* moderately-compressed JPEG
        # regardless of content, so they are excluded as hint candidates
        # even though the acceptance loop below still tests them honestly.
        if ratio > best_hint_ratio and s not in (8, 16):
            best_hint, best_hint_ratio = s, ratio
        if cx * s >= concentration_ratio and cy * s >= concentration_ratio:
            return {"scale": s, "method": "edge-period",
                    "confidence": round((cx + cy) / 2.0, 3), "hint_scale": None}
    # nothing crossed the acceptance bar -- but the best-scoring candidate is
    # still worth a hint for the model to retry with `--scale N` explicitly.
    return {"scale": 1, "method": "none", "confidence": 0.0, "hint_scale": best_hint}


def detect_pixel_scale(pixels, max_scale=32, tolerance=0.985):
    """-> the detected pixel scale as a plain int. See `detect_pixel_scale_report`
    for the method used and a confidence score."""
    return detect_pixel_scale_report(pixels, max_scale, tolerance)["scale"]
