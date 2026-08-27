"""Editing operations on .pxa documents.

These are deliberately *coarse* (shapes, regions, whole-image transforms) --
fine work is done by editing the grid text directly, which is what makes the
format worth having. Use these for the mechanical parts a human artist would
also do with a tool rather than by hand.
"""

import pxa


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

def put(frame, x, y, key):
    return frame.set(x, y, key)


def rect(frame, x0, y0, x1, y1, key, fill=False):
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if fill or y in (y0, y1) or x in (x0, x1):
                frame.set(x, y, key)
    return frame


def line(frame, x0, y0, x1, y1, key):
    """Bresenham. Note: for anything you care about artistically, hand-place the
    segment lengths instead -- Bresenham produces jaggies at shallow angles."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        frame.set(x0, y0, key)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy; x0 += sx
        if e2 < dx:
            err += dx; y0 += sy
    return frame


def ellipse(frame, cx, cy, rx, ry, key, fill=False):
    for y in range(cy - ry, cy + ry + 1):
        for x in range(cx - rx, cx + rx + 1):
            dx = (x - cx) / float(rx or 1)
            dy = (y - cy) / float(ry or 1)
            d = dx * dx + dy * dy
            if d <= 1.0:
                if fill:
                    frame.set(x, y, key)
                else:
                    inner = ((abs(x - cx) - 1) / float(rx or 1)) ** 2 + \
                            ((abs(y - cy) - 1) / float(ry or 1)) ** 2
                    if inner > 1.0:
                        frame.set(x, y, key)
    return frame


def flood_fill(frame, x, y, key, diagonal=False):
    target = frame.get(x, y)
    if target is None or target == key:
        return frame
    stack, seen = [(x, y)], set()
    nbrs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        nbrs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    while stack:
        cx, cy = stack.pop()
        if (cx, cy) in seen or frame.get(cx, cy) != target:
            continue
        seen.add((cx, cy))
        frame.set(cx, cy, key)
        for dx, dy in nbrs:
            stack.append((cx + dx, cy + dy))
    return frame


def replace(frame, old, new):
    frame.rows = [row.replace(old, new) for row in frame.rows]
    return frame


def patch(frame, x, y, rows, transparent_passthrough=None):
    """Stamp a small sub-grid at (x, y). Characters equal to
    `transparent_passthrough` (e.g. '~') leave the target untouched."""
    for j, r in enumerate(rows):
        for i, ch in enumerate(r):
            if transparent_passthrough and ch == transparent_passthrough:
                continue
            frame.set(x + i, y + j, ch)
    return frame


# --------------------------------------------------------------------------
# whole-frame transforms
# --------------------------------------------------------------------------

def shift(frame, dx, dy, empty="."):
    w, h = frame.width, frame.height
    rows = []
    for y in range(h):
        sy = y - dy
        if not (0 <= sy < h):
            rows.append(empty * w); continue
        src = frame.rows[sy]
        if dx >= 0:
            rows.append((empty * dx + src)[:w])
        else:
            rows.append((src[-dx:] + empty * (-dx))[:w])
    frame.rows = rows
    return frame


def flip_h(frame):
    frame.rows = [r[::-1] for r in frame.rows]
    return frame


def flip_v(frame):
    frame.rows = list(reversed(frame.rows))
    return frame


def mirror(frame, axis="x", source="left"):
    """Mirror one half onto the other -- the standard way to block in a
    symmetric character before breaking symmetry on purpose."""
    w, h = frame.width, frame.height
    if axis == "x":
        mid = w // 2
        rows = []
        for r in frame.rows:
            if source == "left":
                left = r[:mid]
                rows.append(left + (r[mid:w - mid] if w % 2 else "") + left[::-1])
            else:
                right = r[w - mid:]
                rows.append(right[::-1] + (r[mid:w - mid] if w % 2 else "") + right)
        frame.rows = rows
    else:
        mid = h // 2
        top = frame.rows[:mid]
        middle = frame.rows[mid:h - mid] if h % 2 else []
        frame.rows = top + middle + list(reversed(top))
    return frame


def crop_to_content(doc, frame, margin=0):
    t = doc.transparent_key()
    xs, ys = [], []
    for y, row in enumerate(frame.rows):
        for x, ch in enumerate(row):
            if ch != t:
                xs.append(x); ys.append(y)
    if not xs:
        return frame
    x0, x1 = max(0, min(xs) - margin), min(frame.width - 1, max(xs) + margin)
    y0, y1 = max(0, min(ys) - margin), min(frame.height - 1, max(ys) + margin)
    frame.rows = [r[x0:x1 + 1] for r in frame.rows[y0:y1 + 1]]
    return frame


def resize_canvas(doc, frame, w, h, anchor="center", empty=None):
    empty = empty or doc.transparent_key()
    ow, oh = frame.width, frame.height
    if anchor == "center":
        ox, oy = (w - ow) // 2, (h - oh) // 2
    elif anchor == "topleft":
        ox, oy = 0, 0
    elif anchor == "bottom":
        ox, oy = (w - ow) // 2, h - oh
    else:
        ox, oy = 0, 0
    rows = [empty * w for _ in range(h)]
    frame2 = pxa.Frame(frame.name, rows)
    for y in range(oh):
        for x in range(ow):
            frame2.set(x + ox, y + oy, frame.rows[y][x])
    frame.rows = frame2.rows
    return frame


def scale_up(frame, factor):
    """Integer nearest-neighbour scale of the *grid* (not the render).
    Only ever use whole numbers -- non-integer scaling destroys pixel art."""
    f = int(factor)
    rows = []
    for r in frame.rows:
        big = "".join(ch * f for ch in r)
        for _ in range(f):
            rows.append(big)
    frame.rows = rows
    return frame


# --------------------------------------------------------------------------
# craft helpers
# --------------------------------------------------------------------------

def silhouette(doc, frame, key=None):
    """Collapse everything opaque to one colour -- the readability test."""
    t = doc.transparent_key()
    key = key or (doc.opaque_swatches()[0].key if doc.opaque_swatches() else "K")
    frame.rows = ["".join(t if ch == t else key for ch in row) for row in frame.rows]
    return frame


def outline(doc, frame, key, mode="outside", diagonal=False, only_keys=None):
    """Add an outline around opaque content.

    mode=outside grows the shape by one pixel; mode=inside recolours the border
    pixels of the shape itself (selective outlining is usually better art --
    outline only where the form meets a light background)."""
    t = doc.transparent_key()
    w, h = frame.width, frame.height
    nbrs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        nbrs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    targets = []
    for y in range(h):
        for x in range(w):
            ch = frame.get(x, y)
            solid = ch != t
            if only_keys and solid and ch not in only_keys:
                continue
            if mode == "outside" and solid:
                continue
            if mode == "inside" and not solid:
                continue
            hit = False
            for dx, dy in nbrs:
                n = frame.get(x + dx, y + dy)
                if mode == "outside":
                    if n is not None and n != t and n != key:
                        hit = True; break
                else:
                    if n is None or n == t:
                        hit = True; break
            if hit:
                targets.append((x, y))
    for x, y in targets:
        frame.set(x, y, key)
    return frame


def selective_outline(doc, frame, dark_key, light_key=None, light_dir=(-1, -1)):
    """Outline that thins toward the light source: full dark outline in shadow,
    lighter (or absent) outline on the lit side. Reads far better than a
    uniform black keyline."""
    outline(doc, frame, dark_key, mode="inside")
    if light_key:
        t = doc.transparent_key()
        dx, dy = light_dir
        for y in range(frame.height):
            for x in range(frame.width):
                if frame.get(x, y) != dark_key:
                    continue
                if frame.get(x - dx, y - dy) in (t, None):
                    frame.set(x, y, light_key)
    return frame


def clean_orphans(doc, frame, min_cluster=1):
    """Remove single-pixel islands of a colour by absorbing them into the most
    common neighbouring colour. Use sparingly: some orphans are intentional
    (eye glints, sparks)."""
    t = doc.transparent_key()
    w, h = frame.width, frame.height
    fixed = 0
    for y in range(h):
        for x in range(w):
            ch = frame.get(x, y)
            if ch == t:
                continue
            same = 0
            counts = {}
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = frame.get(x + dx, y + dy)
                if n is None:
                    continue
                if n == ch:
                    same += 1
                elif n != t:
                    counts[n] = counts.get(n, 0) + 1
            if same <= min_cluster - 1 and counts:
                best = max(counts.items(), key=lambda kv: kv[1])[0]
                frame.set(x, y, best)
                fixed += 1
    return fixed
