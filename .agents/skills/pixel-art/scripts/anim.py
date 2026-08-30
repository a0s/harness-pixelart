"""Animation: frame management, drift analysis, onion skin, filmstrip, GIF.

The known failure mode of language models animating pixel art is losing volume
and proportion between frames (a swordsman whose head grows by two pixels on
frame 3). Everything here exists to make that failure *measurable* instead of
something the model has to notice by eye.
"""

import pxa
import imaging
import gifwrite


# --------------------------------------------------------------------------
# frame management
# --------------------------------------------------------------------------

def add_frame(doc, name, source=None, after=None):
    base = doc.frame(source) if source is not None else None
    if base is not None:
        f = base.copy(name)
    else:
        t = doc.transparent_key()
        f = pxa.Frame(name, [t * doc.width for _ in range(doc.height)])
    if after is None:
        doc.frames.append(f)
    else:
        idx = doc.frames.index(doc.frame(after))
        doc.frames.insert(idx + 1, f)
    return f


def reorder(doc, names):
    lookup = dict((f.name, f) for f in doc.frames)
    missing = [n for n in names if n not in lookup]
    if missing:
        raise pxa.PxaError("unknown frames: %s" % ", ".join(missing))
    rest = [f for f in doc.frames if f.name not in names]
    doc.frames = [lookup[n] for n in names] + rest
    return doc


def remove_frame(doc, name):
    f = doc.frame(name)
    doc.frames.remove(f)
    return doc


def timing(doc):
    """Per-frame duration in ms. `fps: 8` or `timing: 120,90,120,90` in @meta."""
    n = len(doc.frames)
    raw = doc.meta.get("timing")
    if raw:
        vals = [int(v) for v in raw.replace(" ", "").split(",") if v]
        return (vals + [vals[-1]] * n)[:n]
    fps = float(doc.meta.get("fps", 8) or 8)
    return [int(round(1000.0 / max(0.5, fps)))] * n


def timing_conflict(doc, fps):
    """-> the doc's raw `timing:` values (list[int]) when `fps` is truthy and
    they carry more than one distinct value, else None.

    A GIF export takes an explicit `--fps` as an instruction to flatten the
    animation's timing -- but doing that silently throws away a hand-tuned
    rhythm (held holds, quick snaps) with no trace. This is the check callers
    use to decide whether that would happen, so they can warn about it (and
    keep the original timing) instead of overriding it without comment. A
    uniform or absent timing has nothing to lose, so this reads None then."""
    if not fps:
        return None
    raw = doc.meta.get("timing")
    if not raw:
        return None
    vals = [int(v) for v in raw.replace(" ", "").split(",") if v]
    return vals if len(set(vals)) > 1 else None


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def bbox(doc, frame):
    t = doc.transparent_key()
    xs, ys = [], []
    for y, row in enumerate(frame.rows):
        for x, ch in enumerate(row):
            if ch != t:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def stats(doc, frame):
    t = doc.transparent_key()
    counts = frame.counts()
    area = sum(v for k, v in counts.items() if k != t)
    bb = bbox(doc, frame)
    # centre of mass -- the anchor an animator actually watches
    sx = sy = n = 0
    for y, row in enumerate(frame.rows):
        for x, ch in enumerate(row):
            if ch != t:
                sx += x; sy += y; n += 1
    com = (round(sx / float(n), 2), round(sy / float(n), 2)) if n else None
    return {
        "name": frame.name,
        "area": area,
        "bbox": bb,
        "width": (bb[2] - bb[0] + 1) if bb else 0,
        "height": (bb[3] - bb[1] + 1) if bb else 0,
        "com": com,
        "colors": dict((k, v) for k, v in counts.items() if k != t),
    }


def drift(doc, area_tol=0.12, size_tol=2, anchor="bottom"):
    """Compare every frame against the first. Returns a list of findings.

    anchor: which edge is expected to stay put ('bottom' for a standing
    character, 'center' for a spinning coin, 'none' to skip)."""
    if len(doc.frames) < 2:
        return []
    base = stats(doc, doc.frames[0])
    findings = []
    if base["area"] == 0:
        return [{"frame": doc.frames[0].name, "rule": "empty-frame",
                 "message": "first frame is empty"}]
    for f in doc.frames[1:]:
        s = stats(doc, f)
        if s["area"] == 0:
            findings.append({"frame": f.name, "rule": "empty-frame",
                             "message": "frame is empty"})
            continue
        da = (s["area"] - base["area"]) / float(base["area"])
        if abs(da) > area_tol:
            findings.append({
                "frame": f.name, "rule": "volume-drift",
                "message": "filled area is %+.0f%% vs first frame (%d -> %d px); "
                           "the character is gaining or losing mass"
                           % (da * 100, base["area"], s["area"])})
        if abs(s["height"] - base["height"]) > size_tol:
            findings.append({
                "frame": f.name, "rule": "height-drift",
                "message": "height %d vs %d on the first frame -- squash and stretch "
                           "should be deliberate, not accidental"
                           % (s["height"], base["height"])})
        if abs(s["width"] - base["width"]) > size_tol + 1:
            findings.append({
                "frame": f.name, "rule": "width-drift",
                "message": "width %d vs %d on the first frame" % (s["width"], base["width"])})
        if anchor == "bottom" and base["bbox"] and s["bbox"]:
            if abs(s["bbox"][3] - base["bbox"][3]) > 1:
                findings.append({
                    "frame": f.name, "rule": "anchor-drift",
                    "message": "feet line moved from y=%d to y=%d -- a standing "
                               "character should keep its ground contact"
                               % (base["bbox"][3], s["bbox"][3])})
        if anchor == "center" and base["com"] and s["com"]:
            dx = abs(s["com"][0] - base["com"][0]); dy = abs(s["com"][1] - base["com"][1])
            if max(dx, dy) > 2.5:
                findings.append({
                    "frame": f.name, "rule": "anchor-drift",
                    "message": "centre of mass moved by (%.1f, %.1f) px" % (dx, dy)})
        for key, cnt in base["colors"].items():
            if cnt >= 8 and key not in s["colors"]:
                sw = doc.swatch(key)
                findings.append({
                    "frame": f.name, "rule": "colour-dropped",
                    "message": "colour %r (%s) covers %d px on frame 1 but is absent here"
                               % (key, (sw.name if sw else "?"), cnt)})
    return findings


def changed_pixels(doc, a, b):
    fa, fb = doc.frame(a), doc.frame(b)
    n = 0
    for y in range(min(fa.height, fb.height)):
        for x in range(min(fa.width, fb.width)):
            if fa.rows[y][x] != fb.rows[y][x]:
                n += 1
    return n


def motion_report(doc):
    """How much actually moves between consecutive frames. Near-zero means a
    dead frame; near-everything means the frames are unrelated poses."""
    out = []
    total = doc.width * doc.height
    for i in range(len(doc.frames)):
        j = (i + 1) % len(doc.frames)
        if len(doc.frames) < 2:
            break
        n = changed_pixels(doc, doc.frames[i].name, doc.frames[j].name)
        out.append({"from": doc.frames[i].name, "to": doc.frames[j].name,
                    "changed": n, "ratio": round(n / float(total or 1), 4)})
    return out


# --------------------------------------------------------------------------
# rendering helpers
# --------------------------------------------------------------------------

def onion(doc, index, prev=1, next=0, ghost=0.34, bg=(30, 32, 40, 255)):
    """Render one frame over ghosted neighbours -- exactly what an animator has
    on screen while inbetweening."""
    cur = doc.frames[index]
    w, h = cur.width, cur.height
    img = imaging.new_image(w, h, bg)
    order = []
    for k in range(prev, 0, -1):
        order.append(((index - k) % len(doc.frames), ghost * (1.0 - 0.2 * (k - 1)), (90, 150, 255)))
    for k in range(1, next + 1):
        order.append(((index + k) % len(doc.frames), ghost * (1.0 - 0.2 * (k - 1)), (255, 120, 90)))
    t = doc.transparent_key()
    for idx, alpha, tint in order:
        f = doc.frames[idx]
        for y in range(h):
            for x in range(w):
                ch = f.rows[y][x]
                if ch == t:
                    continue
                c = doc.rgba(ch)
                mix = tuple(int(c[i] * 0.35 + tint[i] * 0.65) for i in range(3))
                b = img[y][x]
                img[y][x] = tuple(int(mix[i] * alpha + b[i] * (1 - alpha)) for i in range(3)) + (255,)
    for y in range(h):
        for x in range(w):
            ch = cur.rows[y][x]
            if ch == t:
                continue
            img[y][x] = doc.rgba(ch)
    return img


def to_gif(doc, path, scale=6, fps=None, loop=0, bg=None, force_fps=False):
    """`fps`, when given, is only honoured over an existing varied `timing:`
    if `force_fps` is also set -- see `timing_conflict`. Callers that already
    warned about (or don't care about) the conflict pass `force_fps=True`;
    everyone else gets the sprite's own rhythm back instead of a silent
    flattening."""
    keys = [s.key for s in doc.swatches]
    t = doc.transparent_key()
    order = [t] + [k for k in keys if k != t]
    index_of = dict((k, i) for i, k in enumerate(order))
    palette = []
    for k in order:
        c = doc.rgba(k)
        palette.append((c[0], c[1], c[2]) if k != t else (bg or (0, 0, 0)))
    grids = [[[index_of.get(ch, 0) for ch in row] for row in f.rows] for f in doc.frames]
    use_fps = fps and (force_fps or not timing_conflict(doc, fps))
    if use_fps:
        delays = [max(2, int(round(100.0 / float(fps))))] * len(doc.frames)
    else:
        delays = [max(2, int(round(ms / 10.0))) for ms in timing(doc)]
    return gifwrite.write_gif(path, grids, palette, doc.width, doc.height,
                              delays_cs=delays, transparent_index=0, loop=loop, scale=scale)
