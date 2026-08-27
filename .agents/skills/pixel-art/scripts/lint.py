"""The craft linter.

Every rule here encodes something a pixel artist would say in a critique but
that a language model cannot reliably see by looking at a 32x32 image. Rules
are advisory by design: real artwork breaks them on purpose. Read the finding,
decide, and either fix it or write it off in the notes.
"""

import pxa
import anim

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


class Finding(object):
    def __init__(self, rule, severity, message, frame=None, at=None, hint=""):
        self.rule = rule
        self.severity = severity
        self.message = message
        self.frame = frame
        self.at = at or []
        self.hint = hint

    def as_dict(self):
        return {"rule": self.rule, "severity": self.severity, "message": self.message,
                "frame": self.frame, "at": self.at[:24], "hint": self.hint}


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------

def _mask(doc, frame):
    t = doc.transparent_key()
    return [[frame.rows[y][x] != t for x in range(frame.width)] for y in range(frame.height)]


def _components(frame, keys=None, diagonal=False, transparent="."):
    """Connected components of equal-character pixels."""
    w, h = frame.width, frame.height
    seen = [[False] * w for _ in range(h)]
    nbrs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        nbrs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    out = []
    for y in range(h):
        for x in range(w):
            if seen[y][x]:
                continue
            ch = frame.rows[y][x]
            if ch == transparent or (keys and ch not in keys):
                seen[y][x] = True
                continue
            stack, cells = [(x, y)], []
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for dx, dy in nbrs:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] \
                            and frame.rows[ny][nx] == ch:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            out.append((ch, cells))
    return out


def _distance_to_edge(mask):
    """Chessboard distance from each solid pixel to the nearest hole/outside."""
    h = len(mask); w = len(mask[0]) if h else 0
    INF = 10 ** 6
    d = [[0 if not mask[y][x] else INF for x in range(w)] for y in range(h)]
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            best = INF
            for dy in (-1, 0):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 1:
                        continue
                    ny, nx = y + dy, x + dx
                    v = d[ny][nx] if (0 <= ny < h and 0 <= nx < w) else 0
                    best = min(best, v + 1)
            d[y][x] = best
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            if not mask[y][x]:
                continue
            best = d[y][x]
            for dy in (1, 0):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == -1:
                        continue
                    ny, nx = y + dy, x + dx
                    v = d[ny][nx] if (0 <= ny < h and 0 <= nx < w) else 0
                    best = min(best, v + 1)
            d[y][x] = best
    return d


def _edge_runs(mask, side):
    """Walk one silhouette edge and return (x_or_y, run_length) steps.
    side: 'top' | 'bottom' | 'left' | 'right'."""
    h = len(mask); w = len(mask[0]) if h else 0
    profile = []
    if side in ("top", "bottom"):
        rng = range(h) if side == "top" else range(h - 1, -1, -1)
        for x in range(w):
            v = None
            for y in rng:
                if mask[y][x]:
                    v = y; break
            profile.append(v)
    else:
        rng = range(w) if side == "left" else range(w - 1, -1, -1)
        for y in range(h):
            v = None
            for x in rng:
                if mask[y][x]:
                    v = x; break
            profile.append(v)
    runs, start = [], None
    for i, v in enumerate(profile):
        if v is None:
            if start is not None:
                runs.append((profile[start], start, i - start))
                start = None
            continue
        if start is None:
            start = i
        elif profile[start] != v:
            runs.append((profile[start], start, i - start))
            start = i
    if start is not None:
        runs.append((profile[start], start, len(profile) - start))
    return runs


def _median(vals):
    if not vals:
        return 0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def rule_structure(doc, frame, cfg, out):
    for msg in doc.validate():
        out.append(Finding("invalid-document", "error", msg, frame.name,
                           hint="fix the grid or the @palette block before anything else"))


def rule_orphans(doc, frame, cfg, out):
    t = doc.transparent_key()
    limit = cfg.get("min_cluster", 1)
    spots = []
    for ch, cells in _components(frame, diagonal=False, transparent=t):
        if len(cells) <= limit:
            sw = doc.swatch(ch)
            if sw and "glint" in (sw.name or "").lower():
                continue
            spots.extend(cells)
    if spots:
        out.append(Finding(
            "orphan-pixel", "warn",
            "%d single-pixel island(s) of colour -- these read as noise unless they "
            "are deliberate highlights or sparks" % len(spots),
            frame.name, spots,
            hint="absorb them into a neighbouring cluster, or grow them to 2-3 px "
                 "(`px fix orphans FILE` does the mechanical version)"))


def rule_edge_rhythm(doc, frame, cfg, out):
    """Jaggies and doubles: broken rhythm in a staircase edge."""
    mask = _mask(doc, frame)
    hits = []
    for side in ("top", "bottom", "left", "right"):
        runs = _edge_runs(mask, side)
        for i in range(1, len(runs) - 1):
            prev_len, cur_len, next_len = runs[i - 1][2], runs[i][2], runs[i + 1][2]
            # only look at monotone stretches: a real staircase, not a corner
            if not (runs[i - 1][0] != runs[i][0] != runs[i + 1][0]):
                continue
            dir1 = runs[i][0] - runs[i - 1][0]
            dir2 = runs[i + 1][0] - runs[i][0]
            if dir1 == 0 or dir2 == 0 or (dir1 > 0) != (dir2 > 0):
                continue
            if abs(dir1) > 2 or abs(dir2) > 2:
                continue
            neighbours = _median([prev_len, next_len])
            pos = runs[i][1]
            coord = (pos, runs[i][0]) if side in ("top", "bottom") else (runs[i][0], pos)
            if neighbours >= 3 and cur_len == 1:
                hits.append(("jaggy", coord, cur_len, neighbours, side))
            elif neighbours == 1 and cur_len == 2:
                hits.append(("double", coord, cur_len, neighbours, side))
            elif neighbours >= 2 and cur_len >= neighbours * 3:
                hits.append(("stall", coord, cur_len, neighbours, side))
    if hits:
        jag = [h for h in hits if h[0] == "jaggy"]
        dbl = [h for h in hits if h[0] == "double"]
        if jag:
            out.append(Finding(
                "jaggies", "warn",
                "%d place(s) where a staircase drops to a 1-px step between longer "
                "steps -- the eye reads this as a dent in the line" % len(jag),
                frame.name, [h[1] for h in jag],
                hint="make the run lengths a smooth sequence (4-3-2-1 or 3-3-3), never 3-1-3"))
        if dbl:
            out.append(Finding(
                "doubles", "warn",
                "%d doubled step(s) in an otherwise 1:1 diagonal -- the slope stutters"
                % len(dbl),
                frame.name, [h[1] for h in dbl],
                hint="keep a 45-degree edge exactly one pixel per step, or commit to a "
                     "different consistent slope (2:1, 3:1)"))


def rule_pillow_shading(doc, frame, cfg, out):
    """Shading that follows the silhouette inward instead of a light direction."""
    t = doc.transparent_key()
    mask = _mask(doc, frame)
    cells = [(x, y, frame.rows[y][x]) for y in range(frame.height)
             for x in range(frame.width) if mask[y][x]]
    if len(cells) < 40:
        return
    lums = {}
    for s in doc.swatches:
        lums[s.key] = pxa.luminance(s.rgba)
    vals = sorted(set(lums[c[2]] for c in cells if c[2] in lums))
    if len(vals) < 3:
        return
    lo_cut, hi_cut = vals[max(0, len(vals) // 4 - 1)], vals[min(len(vals) - 1, (3 * len(vals)) // 4)]
    dark = [(x, y) for x, y, ch in cells if lums.get(ch, 0) <= lo_cut]
    light = [(x, y) for x, y, ch in cells if lums.get(ch, 0) >= hi_cut]
    if len(dark) < 6 or len(light) < 6:
        return
    def centroid(pts):
        return (sum(p[0] for p in pts) / float(len(pts)), sum(p[1] for p in pts) / float(len(pts)))
    cd, cl = centroid(dark), centroid(light)
    bb = anim.bbox(doc, frame)
    span = max(bb[2] - bb[0] + 1, bb[3] - bb[1] + 1) if bb else 1
    sep = ((cl[0] - cd[0]) ** 2 + (cl[1] - cd[1]) ** 2) ** 0.5 / float(span)

    dist = _distance_to_edge(mask)
    pairs = [(dist[y][x], lums.get(ch, 0)) for x, y, ch in cells if ch in lums]
    n = len(pairs)
    mx = sum(p[0] for p in pairs) / float(n)
    my = sum(p[1] for p in pairs) / float(n)
    cov = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    vx = sum((p[0] - mx) ** 2 for p in pairs) ** 0.5
    vy = sum((p[1] - my) ** 2 for p in pairs) ** 0.5
    corr = cov / (vx * vy) if vx and vy else 0.0

    if sep < 0.14 and corr > 0.45:
        out.append(Finding(
            "pillow-shading", "warn",
            "light and shadow are distributed concentrically (light/dark centroids are "
            "%.0f%% of the sprite apart, brightness tracks distance-from-edge at r=%.2f) "
            "-- the form looks inflated rather than lit" % (sep * 100, corr),
            frame.name,
            hint="pick one light direction, keep it in @meta light:, and let one side of "
                 "every form stay dark all the way to the silhouette"))
    elif sep >= 0.14:
        ang = "%+.1f,%+.1f" % (cl[0] - cd[0], cl[1] - cd[1])
        out.append(Finding("light-direction", "info",
                           "light reads as coming from (%s) in pixel coords" % ang,
                           frame.name))


def rule_banding(doc, frame, cfg, out):
    """Two ramp steps running parallel for a long stretch -- reads as a stripe
    rather than a form turning away from the light."""
    import palettes
    ramps = palettes.ramps_of([s.rgba for s in doc.opaque_swatches()])
    neighbour = set()
    key_of = dict((s.rgba, s.key) for s in doc.swatches)
    for r in ramps:
        for i in range(len(r) - 1):
            a, b = key_of.get(r[i]), key_of.get(r[i + 1])
            if a and b:
                neighbour.add((a, b)); neighbour.add((b, a))
    hits = []
    for y in range(frame.height - 1):
        x = 0
        while x < frame.width:
            ch = frame.rows[y][x]
            below = frame.rows[y + 1][x]
            if (ch, below) not in neighbour:
                x += 1; continue
            run = 0
            while x + run < frame.width and frame.rows[y][x + run] == ch \
                    and frame.rows[y + 1][x + run] == below:
                run += 1
            if run >= max(5, frame.width // 5):
                hits.append((x, y))
            x += max(1, run)
    if hits:
        out.append(Finding(
            "banding", "warn",
            "%d long stretch(es) where two neighbouring ramp steps run parallel for "
            "5+ pixels" % len(hits), frame.name, hits,
            hint="break the boundary up: stagger it, or let the two values interlock "
                 "with a short dither run instead of a clean stripe"))


def rule_palette_health(doc, frame, cfg, out):
    counts = frame.counts()
    t = doc.transparent_key()
    opaque = doc.opaque_swatches()
    unused = [s.key for s in opaque if counts.get(s.key, 0) == 0]
    if unused:
        out.append(Finding("unused-colour", "info",
                           "palette entries never used in this frame: %s" % ", ".join(unused),
                           frame.name,
                           hint="drop them, or use them -- an unused swatch usually means "
                                "a plan you abandoned halfway"))
    stray = [(s.key, counts.get(s.key, 0)) for s in opaque
             if 0 < counts.get(s.key, 0) <= cfg.get("stray_threshold", 2)]
    if len(stray) >= 2:
        out.append(Finding("stray-colour", "warn",
                           "%d colour(s) appear on 2 pixels or fewer: %s"
                           % (len(stray), ", ".join("%s(%d)" % s for s in stray)),
                           frame.name,
                           hint="a colour that earns a palette slot should carry a shape, "
                                "not a speck"))
    for i, a in enumerate(opaque):
        for b in opaque[i + 1:]:
            d = pxa.color_distance(a.rgba, b.rgba)
            if d < cfg.get("min_color_distance", 7.0):
                out.append(Finding(
                    "redundant-colour", "warn",
                    "%r (%s) and %r (%s) are perceptually the same colour (dE=%.1f)"
                    % (a.key, pxa.format_hex(a.rgba), b.key, pxa.format_hex(b.rgba), d),
                    frame.name,
                    hint="merge them; a tight palette is what makes pixel art read"))
    total = sum(v for k, v in counts.items() if k != t)
    used = len([s for s in opaque if counts.get(s.key, 0) > 0])
    budget = cfg.get("max_colors")
    if budget and used > budget:
        out.append(Finding("palette-budget", "warn",
                           "%d colours used, budget is %d" % (used, budget), frame.name))
    if total and used > max(4, total // 12):
        out.append(Finding("colour-density", "info",
                           "%d colours across %d filled pixels -- that is a lot of colour "
                           "for this canvas" % (used, total), frame.name))


def rule_ramp_quality(doc, frame, cfg, out):
    import palettes
    opaque = doc.opaque_swatches()
    if len(opaque) < 3:
        return
    ramps = palettes.ramps_of([s.rgba for s in opaque])
    flat = []
    for r in ramps:
        if len(r) < 3:
            continue
        hues = [pxa.rgb_to_hsl(c)[0] for c in r]
        sats = [pxa.rgb_to_hsl(c)[1] for c in r]
        if max(sats) < 6:
            continue                                   # a grey ramp is allowed to be grey
        spread = max((max(hues) - min(hues)), 0)
        if spread > 180:
            spread = 360 - spread
        if spread < 6:
            flat.append(pxa.format_hex(r[0]))
    if flat:
        out.append(Finding(
            "flat-ramp", "info",
            "%d ramp(s) change value without changing hue (%s) -- pure "
            "lighten/darken looks plastic" % (len(flat), ", ".join(flat[:4])),
            frame.name,
            hint="rotate shadows toward the cool end and highlights toward the warm end; "
                 "`px palette ramp '#hex' --steps 5` generates a hue-shifted ramp"))
    lums = sorted(pxa.luminance(s.rgba) for s in opaque)
    if lums and (lums[-1] - lums[0]) < 35:
        out.append(Finding("low-value-range", "warn",
                           "total value range is only %.0f/100 -- the sprite will read as "
                           "a flat blob at real size" % (lums[-1] - lums[0]), frame.name,
                           hint="push the darkest dark down and the lightest light up"))


def rule_readability(doc, frame, cfg, out):
    """Squint test, done numerically: does the silhouette hold together?"""
    t = doc.transparent_key()
    mask = _mask(doc, frame)
    solid = sum(1 for row in mask for v in row if v)
    if not solid:
        out.append(Finding("empty-frame", "error", "frame is empty", frame.name))
        return
    comps = []
    w, h = frame.width, frame.height
    seen = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if not mask[y][x] or seen[y][x]:
                continue
            stack, size = [(x, y)], 0
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop(); size += 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True; stack.append((nx, ny))
            comps.append(size)
    detached = [c for c in comps if c < solid * 0.15]
    if len(comps) > 1 and detached:
        out.append(Finding("detached-piece", "info",
                           "silhouette is in %d pieces (%d small) -- fine for a floating "
                           "sword, a problem for a body" % (len(comps), len(detached)),
                           frame.name))
    bb = anim.bbox(doc, frame)
    if bb:
        fill = solid / float((bb[2] - bb[0] + 1) * (bb[3] - bb[1] + 1))
        if fill > 0.92:
            out.append(Finding("blocky-silhouette", "warn",
                               "the shape fills %.0f%% of its bounding box -- it is close "
                               "to a rectangle and will not read as a character"
                               % (fill * 100), frame.name,
                               hint="cut into the silhouette: negative space between arm and "
                                    "torso, between legs, around the weapon"))
        margin = min(bb[0], bb[1], frame.width - 1 - bb[2], frame.height - 1 - bb[3])
        if margin > max(2, min(frame.width, frame.height) // 4):
            out.append(Finding("wasted-canvas", "info",
                               "%d px of empty margin on every side -- the subject is small "
                               "for this canvas" % margin, frame.name))


def rule_aa_hygiene(doc, frame, cfg, out):
    """Anti-aliasing pixels that touch transparency: on a sprite these show up
    as a dirty fringe over whatever background it lands on."""
    t = doc.transparent_key()
    lums = dict((s.key, pxa.luminance(s.rgba)) for s in doc.swatches)
    opaque = doc.opaque_swatches()
    if len(opaque) < 3:
        return
    ordered = sorted(opaque, key=lambda s: lums[s.key])
    mid_keys = set(s.key for s in ordered[1:-1])
    hits = []
    for y in range(frame.height):
        for x in range(frame.width):
            ch = frame.rows[y][x]
            if ch == t or ch not in mid_keys:
                continue
            edge = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                       if frame.get(x + dx, y + dy) in (t, None))
            if edge >= 2:
                same = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                           if frame.get(x + dx, y + dy) == ch)
                if same == 0:
                    hits.append((x, y))
    if len(hits) > max(3, frame.width // 8):
        out.append(Finding(
            "outer-aa", "info",
            "%d isolated mid-tone pixel(s) sit on the outer silhouette" % len(hits),
            frame.name, hits,
            hint="anti-aliasing against transparency only works if you know the background; "
                 "for a game sprite keep the outer edge hard")) 


def rule_dither_hygiene(doc, frame, cfg, out):
    """50% checkerboard sprayed over large areas is the classic tell of an
    automatic conversion rather than a decision."""
    w, h = frame.width, frame.height
    checker = 0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            c = frame.rows[y][x]
            if c == doc.transparent_key():
                continue
            if frame.rows[y][x - 1] == frame.rows[y][x + 1] != c and \
               frame.rows[y - 1][x] == frame.rows[y + 1][x] != c:
                checker += 1
    solid = sum(1 for row in frame.rows for ch in row if ch != doc.transparent_key())
    if solid and checker / float(solid) > 0.18:
        out.append(Finding(
            "dither-spray", "warn",
            "%.0f%% of the sprite is a 50%% checkerboard" % (100.0 * checker / solid),
            frame.name,
            hint="dither where a surface turns away from the light, in a gradient of "
                 "density; never as a uniform texture over the whole form"))


STATIC_RULES = [rule_structure, rule_orphans, rule_edge_rhythm, rule_pillow_shading,
                rule_banding, rule_palette_health, rule_ramp_quality, rule_readability,
                rule_aa_hygiene, rule_dither_hygiene]


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def run(doc, cfg=None, frames=None, animation=True):
    cfg = dict(cfg or {})
    out = []
    targets = [doc.frame(f) for f in frames] if frames else doc.frames
    for f in targets:
        for rule in STATIC_RULES:
            try:
                rule(doc, f, cfg, out)
            except Exception as exc:                      # a broken rule must not block work
                out.append(Finding("rule-crashed", "info",
                                   "%s failed: %s" % (rule.__name__, exc), f.name))
    if animation and len(doc.frames) > 1:
        anchor = doc.meta.get("anchor", "bottom")
        for d in anim.drift(doc, anchor=anchor):
            out.append(Finding(d["rule"], "warn", d["message"], d["frame"],
                               hint="hold the anchor and the volume; move parts, not the "
                                    "whole body, unless the motion calls for it"))
        for m in anim.motion_report(doc):
            if m["ratio"] < 0.004:
                out.append(Finding("dead-frame", "warn",
                                   "only %d pixel(s) change between %s and %s"
                                   % (m["changed"], m["from"], m["to"]), m["to"],
                                   hint="every frame must earn its slot -- shift a shoulder, "
                                        "a hem, a hair strand, or delete the frame"))
            elif m["ratio"] > 0.42:
                out.append(Finding("pose-jump", "info",
                                   "%.0f%% of the canvas changes between %s and %s"
                                   % (m["ratio"] * 100, m["from"], m["to"]), m["to"],
                                   hint="fine for a cut, jarring for a loop -- consider a "
                                        "breakdown frame in between"))
    out.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 3), f.rule))
    return out


def format_text(findings, verbose=False):
    if not findings:
        return "clean -- no findings"
    icons = {"error": "!!", "warn": " *", "info": " -"}
    lines = []
    for f in findings:
        head = "%s [%s]%s %s" % (icons.get(f.severity, "  "), f.rule,
                                 (" (%s)" % f.frame) if f.frame else "", f.message)
        lines.append(head)
        if f.at:
            pts = " ".join("%d,%d" % p for p in f.at[:14])
            more = " ...+%d" % (len(f.at) - 14) if len(f.at) > 14 else ""
            lines.append("      at: %s%s" % (pts, more))
        if f.hint and (verbose or f.severity != "info"):
            lines.append("      fix: %s" % f.hint)
    counts = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    lines.append("")
    lines.append("%d finding(s): %s" % (len(findings),
                 ", ".join("%d %s" % (v, k) for k, v in sorted(counts.items()))))
    return "\n".join(lines)
