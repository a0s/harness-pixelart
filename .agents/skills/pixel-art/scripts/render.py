"""Rendering and review sheets.

The point of this module is not export -- it is *seeing*. A 32x32 sprite is
invisible to a model reading a PNG; a 32x32 sprite blown up 12x with a grid and
a coordinate ruler is editable. Every stage of the workflow ends by rendering a
review sheet and actually looking at it.
"""

import pxa
import imaging
import anim
import font3x5 as f35

BG = (34, 36, 44, 255)
PANEL = (26, 28, 34, 255)
INK = (226, 230, 240, 255)
DIM = (120, 128, 145, 255)
ACCENT = (255, 196, 88, 255)
GRID_MINOR = (255, 255, 255, 26)
GRID_MAJOR = (255, 255, 255, 60)
CHECK_A = (58, 60, 70, 255)
CHECK_B = (48, 50, 60, 255)


# --------------------------------------------------------------------------
# basic rendering
# --------------------------------------------------------------------------

def frame_pixels(doc, frame):
    return pxa.frame_to_pixels(doc, frame)


def render_frame(doc, frame, scale=1, background=None, checker=0):
    """-> rgba grid at `scale`x. background=None keeps real transparency;
    checker>0 paints a transparency checkerboard of that cell size."""
    src = frame_pixels(doc, frame)
    w, h = frame.width, frame.height
    out = imaging.new_image(w * scale, h * scale, (0, 0, 0, 0))
    for y in range(h * scale):
        for x in range(w * scale):
            px = src[y // scale][x // scale]
            if px[3] == 0:
                if checker:
                    px = CHECK_A if ((x // checker) + (y // checker)) % 2 else CHECK_B
                elif background:
                    px = background
            elif px[3] < 255 and (background or checker):
                base = background or (CHECK_A if ((x // (checker or 1)) + (y // (checker or 1))) % 2 else CHECK_B)
                a = px[3] / 255.0
                px = tuple(int(px[i] * a + base[i] * (1 - a)) for i in range(3)) + (255,)
            out[y][x] = px
    return out


def draw_grid(img, cell, major=8, minor=GRID_MINOR, major_color=GRID_MAJOR, offset=(0, 0)):
    h = len(img); w = len(img[0]) if h else 0
    ox, oy = offset
    for y in range(h):
        for x in range(w):
            gx = (x - ox) % cell == 0
            gy = (y - oy) % cell == 0
            if not (gx or gy):
                continue
            is_major = (((x - ox) // cell) % major == 0 and gx) or \
                       (((y - oy) // cell) % major == 0 and gy)
            c = major_color if is_major else minor
            b = img[y][x]
            a = c[3] / 255.0
            img[y][x] = tuple(int(c[i] * a + b[i] * (1 - a)) for i in range(3)) + (255,)
    return img


def value_view(doc, frame, scale=1):
    """Greyscale render: the fastest way to check that shading reads by value
    alone rather than leaning on hue."""
    src = frame_pixels(doc, frame)
    w, h = frame.width, frame.height
    out = imaging.new_image(w * scale, h * scale, PANEL)
    for y in range(h * scale):
        for x in range(w * scale):
            px = src[y // scale][x // scale]
            if px[3] == 0:
                continue
            v = int(round(pxa.luminance(px) * 2.55))
            out[y][x] = (v, v, v, 255)
    return out


def silhouette_view(doc, frame, scale=1, fg=(240, 240, 245, 255)):
    src = frame_pixels(doc, frame)
    w, h = frame.width, frame.height
    out = imaging.new_image(w * scale, h * scale, (20, 20, 26, 255))
    for y in range(h * scale):
        for x in range(w * scale):
            if src[y // scale][x // scale][3] > 0:
                out[y][x] = fg
    return out


# --------------------------------------------------------------------------
# composition helpers
# --------------------------------------------------------------------------

def _panel(img, x, y, w, h, color=PANEL):
    for j in range(y, min(y + h, len(img))):
        for i in range(x, min(x + w, len(img[0]))):
            if i >= 0 and j >= 0:
                img[j][i] = color
    return img


def _border(img, x, y, w, h, color=(70, 74, 88, 255)):
    ih = len(img); iw = len(img[0]) if ih else 0
    for i in range(x, x + w):
        for j in (y, y + h - 1):
            if 0 <= i < iw and 0 <= j < ih:
                img[j][i] = color
    for j in range(y, y + h):
        for i in (x, x + w - 1):
            if 0 <= i < iw and 0 <= j < ih:
                img[j][i] = color
    return img


def _ruler(img, x, y, count, cell, step=None, color=DIM, axis="x"):
    """Coordinate numbers along an axis so findings can be quoted as (x, y)."""
    step = step or (5 if cell >= 8 else 10)
    for i in range(0, count, step):
        label = str(i)
        if axis == "x":
            f35.draw_text(img, x + i * cell + 1, y, label, color)
        else:
            f35.draw_text(img, x, y + i * cell + (cell - f35.H) // 2, label, color)
    return img


def palette_strip(doc, frame=None, cell=14, cols=None, width=None):
    """Swatch grid with keys, hex and (optionally) usage counts."""
    sw = doc.swatches
    counts = frame.counts() if frame else {}
    cols = cols or (width // (cell + 26) if width else 6)
    cols = max(1, cols)
    rows = (len(sw) + cols - 1) // cols
    colw = cell + 26
    img = imaging.new_image(cols * colw + 4, rows * (cell + 3) + 4, PANEL)
    for i, s in enumerate(sw):
        cx = 2 + (i % cols) * colw
        cy = 2 + (i // cols) * (cell + 3)
        if s.is_transparent:
            for j in range(cell):
                for k in range(cell):
                    img[cy + j][cx + k] = CHECK_A if ((j // 3) + (k // 3)) % 2 else CHECK_B
        else:
            _panel(img, cx, cy, cell, cell, s.rgba)
        _border(img, cx, cy, cell, cell, (12, 12, 16, 255))
        f35.draw_text(img, cx + cell + 3, cy + 1, s.key, INK)
        n = counts.get(s.key, 0)
        if counts:
            f35.draw_text(img, cx + cell + 3, cy + 8, str(n) if n < 1000 else "%dK" % (n // 1000), DIM)
    return img


def review_sheet(doc, frame_name=None, scale=None, target=560, grid=True,
                 notes=None, show_value=True, show_silhouette=True):
    """The image a model should actually look at after every editing pass."""
    frame = doc.frame(frame_name)
    w, h = frame.width, frame.height
    scale = scale or max(3, min(20, target // max(w, h)))
    small = max(2, scale // 3)

    main = render_frame(doc, frame, scale, checker=max(2, scale // 2))
    if grid:
        draw_grid(main, scale, major=8)
    mw, mh = imaging.size_of(main)

    side_panels = [("1X ACTUAL", render_frame(doc, frame, 1, checker=1)),
                   ("%dX" % small, render_frame(doc, frame, small, checker=max(1, small // 2)))]
    if show_silhouette:
        side_panels.append(("SILHOUETTE", silhouette_view(doc, frame, max(1, small))))
    if show_value:
        side_panels.append(("VALUE", value_view(doc, frame, max(1, small))))

    pad, top = 12, 16
    ruler_x, ruler_y = 16, 12
    side_w = max([imaging.size_of(p)[0] for _, p in side_panels] + [110]) + 8
    side_h = sum(imaging.size_of(p)[1] + 16 for _, p in side_panels)
    body_h = max(mh, side_h)
    note_h = (len(notes) * 8 + 6) if notes else 0

    pal = palette_strip(doc, frame, cell=12,
                        cols=max(2, (ruler_x + mw + pad + side_w) // 44))
    pw, ph = imaging.size_of(pal)

    W = max(ruler_x + mw + pad + side_w + pad, pw + 2 * pad)
    H = top + ruler_y + body_h + pad + 10 + ph + pad + note_h

    img = imaging.new_image(W, H, BG)

    title = "%s  %s  %dX%d  X%d" % (doc.meta.get("name", "sprite").upper(),
                                    frame.name.upper(), w, h, scale)
    if doc.meta.get("stage"):
        title += "  STAGE:%s" % doc.meta["stage"].upper()
    if len(doc.frames) > 1:
        title += "  FRAME %d/%d" % (doc.frames.index(frame) + 1, len(doc.frames))
    f35.draw_text(img, pad, 5, title, ACCENT)

    ox, oy = ruler_x, top + ruler_y
    _ruler(img, ox, top + 4, w, scale, axis="x")
    _ruler(img, 1, oy, h, scale, axis="y")
    imaging.paste(img, main, ox, oy, blend=False)
    _border(img, ox - 1, oy - 1, mw + 2, mh + 2)

    sx, sy = ox + mw + pad, oy
    for label, panel in side_panels:
        f35.draw_text(img, sx, sy, label, DIM)
        imaging.paste(img, panel, sx, sy + 7, blend=False)
        pw2, ph2 = imaging.size_of(panel)
        _border(img, sx - 1, sy + 6, pw2 + 2, ph2 + 2)
        sy += ph2 + 16

    py = top + ruler_y + body_h + pad
    f35.draw_text(img, pad, py - 8, "PALETTE  KEY / PIXELS", DIM)
    imaging.paste(img, pal, pad, py, blend=False)

    if notes:
        ny = py + ph + 8
        for i, line in enumerate(notes):
            f35.draw_text(img, pad, ny + i * 8, line[:110], INK if i == 0 else DIM)
    return img


def filmstrip(doc, scale=None, target=110, columns=None, onion_index=None, labels=True):
    """All frames side by side with numbers -- the animation equivalent of the
    review sheet. Look at this before deciding a loop works."""
    n = len(doc.frames)
    w, h = doc.width, doc.height
    scale = scale or max(2, min(14, target // max(w, h)))
    cols = columns or min(n, max(1, 1400 // (w * scale + 10)))
    rows = (n + cols - 1) // cols
    cw, ch = w * scale + 10, h * scale + 10 + (9 if labels else 0)
    img = imaging.new_image(cols * cw + 8, rows * ch + 22, BG)
    f35.draw_text(img, 6, 5, "%s  %d FRAMES  %s" % (doc.meta.get("name", "anim").upper(), n,
                  ("%d MS" % anim.timing(doc)[0]) if n else ""), ACCENT)
    for i, fr in enumerate(doc.frames):
        cx = 4 + (i % cols) * cw
        cy = 18 + (i // cols) * ch
        panel = render_frame(doc, fr, scale, checker=max(1, scale // 2))
        imaging.paste(img, panel, cx + 5, cy + 5, blend=False)
        _border(img, cx + 4, cy + 4, w * scale + 2, h * scale + 2,
                ACCENT if i == onion_index else (70, 74, 88, 255))
        if labels:
            f35.draw_text(img, cx + 5, cy + h * scale + 8, "%d %s" % (i, fr.name[:10]), DIM)
    return img


def onion_sheet(doc, index=0, scale=None, target=420, prev=1, next=1):
    frame = doc.frames[index]
    w, h = frame.width, frame.height
    scale = scale or max(3, min(16, target // max(w, h)))
    base = anim.onion(doc, index, prev=prev, next=next)
    big = imaging.new_image(w * scale, h * scale, BG)
    for y in range(h * scale):
        for x in range(w * scale):
            big[y][x] = base[y // scale][x // scale]
    draw_grid(big, scale, major=8)
    img = imaging.new_image(w * scale + 16, h * scale + 30, BG)
    f35.draw_text(img, 6, 5, "ONION %s  BLUE=PREV  RED=NEXT" % frame.name.upper(), ACCENT)
    imaging.paste(img, big, 8, 16, blend=False)
    _border(img, 7, 15, w * scale + 2, h * scale + 2)
    return img


def compare_sheet(panels, labels=None, scale=6, gap=10, title=""):
    """Side-by-side of several rgba grids (e.g. reference vs result)."""
    labels = labels or [""] * len(panels)
    scaled = []
    for p in panels:
        w, h = imaging.size_of(p)
        big = imaging.new_image(w * scale, h * scale, BG)
        for y in range(h * scale):
            for x in range(w * scale):
                px = p[y // scale][x // scale]
                big[y][x] = px if px[3] else (CHECK_A if ((x // 4) + (y // 4)) % 2 else CHECK_B)
        scaled.append(big)
    tw = sum(imaging.size_of(s)[0] for s in scaled) + gap * (len(scaled) + 1)
    th = max(imaging.size_of(s)[1] for s in scaled) + 34
    img = imaging.new_image(tw, th, BG)
    if title:
        f35.draw_text(img, gap, 5, title.upper(), ACCENT)
    x = gap
    for s, lab in zip(scaled, labels):
        sw, sh = imaging.size_of(s)
        imaging.paste(img, s, x, 20, blend=False)
        _border(img, x - 1, 19, sw + 2, sh + 2)
        f35.draw_text(img, x, 20 + sh + 4, lab.upper(), DIM)
        x += sw + gap
    return img
