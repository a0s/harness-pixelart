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


def detect_pixel_scale(pixels, max_scale=32, tolerance=0.985):
    """Guess the size of the 'logical pixel' in an image that was upscaled from
    real pixel art (or rendered by a model at 512px).

    A candidate scale is valid when almost every s-by-s block is a single flat
    colour. The largest valid candidate is the true block size -- smaller
    divisors of it are also valid, and larger multiples straddle two original
    pixels and fail. Returns 1 when the image is not scaled-up pixel art."""
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
