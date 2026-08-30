"""The craft linter.

Every rule here encodes something a pixel artist would say in a critique but
that a language model cannot reliably see by looking at a 32x32 image. Rules
are advisory by design: real artwork breaks them on purpose. Read the finding,
decide, and either fix it or write it off in the notes.
"""

import os
import math

import pxa
import anim
import scene as scenemod

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
# structure geometry helpers (massing comparison, shared by STRUCTURE_RULES)
# --------------------------------------------------------------------------

_TONE_ORDER = ["light", "base", "shadow", "dark"]


def _tone_rank(tone):
    """Lower is lighter. Unknown tones (a future one we don't know about yet)
    sort last rather than crashing the comparison."""
    try:
        return _TONE_ORDER.index(tone)
    except ValueError:
        return len(_TONE_ORDER)


def _largest_component_bbox(mask):
    """Bounding box of the largest 8-connected True region of a boolean grid,
    by reusing `_components` on a synthetic '#'/'.' frame."""
    h = len(mask); w = len(mask[0]) if h else 0
    if not w or not h:
        return None
    rows = ["".join("#" if mask[y][x] else "." for x in range(w)) for y in range(h)]
    fake = pxa.Frame("mask", rows)
    solids = [cells for ch, cells in _components(fake, diagonal=True, transparent=".")
              if ch == "#"]
    if not solids:
        return None
    largest = max(solids, key=len)
    xs = [c[0] for c in largest]; ys = [c[1] for c in largest]
    return (min(xs), min(ys), max(xs), max(ys))


def _has_iso_slope(sc):
    """True when the scene's projected screen axes include a horizontal axis
    with a clean 2:1 (dy/dx = 0.5) slope -- the classic pixel-art isometric
    stair, however the scene arrived at it (`view: iso`, `view: camera
    pitch=26.57 yaw=45`, or a hand-written `axes:`)."""
    try:
        axes = scenemod._axes(sc)
    except Exception:
        return False
    if not axes:
        return False
    for ax in axes[:2]:                      # X, Y -- axes[2] (Z) is vertical
        dx, dy = ax
        if abs(dx) < 1e-9:
            continue
        if abs(abs(dy / dx) - 0.5) <= 0.02:
            return True
    return False


def _angle_distance(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _face_screen_tangents(axes, normal):
    """Screen-projected (e1, e2) tangent directions for a face with this
    normal -- e1 'along' the face, e2 'down' it. Replicates scene.py's
    `_uv_basis` (not exposed on a rendered Result) from the normal alone, via
    the scene's own private vector helpers -- fine, since this stays inside
    the pixel-art package and the maths is tiny and stable."""
    e1 = scenemod._cross((0.0, 0.0, 1.0), normal)
    if scenemod._dot(e1, e1) < 1e-9:
        e1 = (1.0, 0.0, 0.0)
    e1 = scenemod._normalize(e1)
    e2 = scenemod._normalize(scenemod._cross(normal, e1))
    if e2[2] > 1e-9:
        e2 = (-e2[0], -e2[1], -e2[2])
    return scenemod._proj_unit(axes, e1), scenemod._proj_unit(axes, e2)


def _screen_angle(vec):
    x, y = vec
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return math.degrees(math.atan2(y, x)) % 180.0


def _face_has_axis_tangent(axes, normal):
    """True when at least one of the face's own projected tangents is itself
    horizontal or vertical on screen -- any wall in a yaw=0 view, the front
    face at iso. Such a face's detail is exempt from plane-drift: the face
    genuinely has an axis-aligned direction to draw along."""
    for vec in _face_screen_tangents(axes, normal):
        deg = _screen_angle(vec)
        if deg is None:
            continue
        if _angle_distance(deg, 0.0) <= 5.0 or _angle_distance(deg, 90.0) <= 5.0:
            return True
    return False


def _ratio_desc(vec):
    x, y = vec
    ax, ay = abs(x), abs(y)
    if ax < 1e-9 or ay < 1e-9:
        return "flat"
    if ax >= ay:
        return "%.3g:1" % (ax / ay)
    return "1:%.3g" % (ay / ax)


def _interior_edge_points(frame, fid_grid, transparent_key):
    """Midpoints of colour-boundary segments that lie *inside* a single
    face's region -- both pixels opaque, differently keyed, and mapped to the
    same face id. A boundary between two faces (a real geometric edge) or
    between paint and transparency (the silhouette) is excluded; only a
    painted detail edge that sits on one face's own plane is a candidate.
    Each point is returned as (x, y, face_id)."""
    w, h = frame.width, frame.height
    t = transparent_key
    pts = []
    for y in range(h):
        row = frame.rows[y]
        for x in range(w):
            c = row[x]
            if x + 1 < w:
                c2 = row[x + 1]
                if c2 != c and t not in (c, c2):
                    fa, fb = fid_grid[y][x], fid_grid[y][x + 1]
                    if fa == fb and fa >= 0:
                        pts.append((x + 0.5, y, fa))
            if y + 1 < h:
                c2 = frame.rows[y + 1][x]
                if c2 != c and t not in (c, c2):
                    fa, fb = fid_grid[y][x], fid_grid[y + 1][x]
                    if fa == fb and fa >= 0:
                        pts.append((x, y + 0.5, fa))
    return pts


def _line_fit(cluster):
    """-> (angle_deg 0..180, length_px, straightness, start_point). straightness
    is the minor/major eigenvalue ratio of the point spread: near 0 means the
    points lie on a line, near 1 means they are a blob."""
    n = len(cluster)
    mx = sum(p[0] for p in cluster) / n
    my = sum(p[1] for p in cluster) / n
    sxx = sum((p[0] - mx) ** 2 for p in cluster)
    syy = sum((p[1] - my) ** 2 for p in cluster)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in cluster)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    common = math.sqrt(((sxx - syy) / 2.0) ** 2 + sxy ** 2)
    mean = (sxx + syy) / 2.0
    major, minor = mean + common, mean - common
    straightness = (minor / major) if major > 1e-9 else 0.0
    dxu, dyu = math.cos(theta), math.sin(theta)
    proj = [(p[0] - mx) * dxu + (p[1] - my) * dyu for p in cluster]
    length = max(proj) - min(proj) if proj else 0.0
    start = min(cluster, key=lambda p: (p[0] - mx) * dxu + (p[1] - my) * dyu)
    return math.degrees(theta) % 180.0, length, straightness, start


def _edge_chains(pts, local_radius=3, angle_tol=20.0, group=None):
    """Group boundary points into orientation-coherent chains -> list of
    (points, group_value) pairs (group_value is None when `group` isn't given).

    Plain spatial adjacency is not enough here: the outer silhouette of an
    object is one connected loop, so a naive flood-fill merges every edge of
    the building -- corners, roofline and a mistaken window line alike -- into
    one blob with no useful angle. Instead each point first gets a local
    orientation from a small neighbourhood (None where the neighbourhood is a
    corner/junction and has no single direction), and two adjacent points only
    join the same chain when their local orientations agree -- so the chain
    breaks exactly at the corners, leaving one straight run per edge.

    `group`, when given, is a parallel list of keys (e.g. a face id): two
    points only ever join the same neighbourhood or chain when their group
    matches, so a chain never bridges two different faces."""
    scaled = [(int(round(px * 2)), int(round(py * 2))) for px, py in pts]
    by_cell = {}
    for i, c in enumerate(scaled):
        by_cell.setdefault(c, []).append(i)

    r = int(local_radius * 2)
    orient = [None] * len(pts)
    for i in range(len(pts)):
        cx, cy = scaled[i]
        nb = [pts[j] for dx in range(-r, r + 1) for dy in range(-r, r + 1)
              for j in by_cell.get((cx + dx, cy + dy), ())
              if group is None or group[j] == group[i]]
        if len(nb) < 4:
            continue
        deg, _len, straightness, _start = _line_fit(nb)
        if straightness <= 0.15:
            orient[i] = deg

    seen = [False] * len(pts)
    chains = []
    for i in range(len(pts)):
        if seen[i] or orient[i] is None:
            continue
        seen[i] = True
        stack, comp = [i], []
        while stack:
            k = stack.pop()
            comp.append(k)
            cx, cy = scaled[k]
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    for j in by_cell.get((cx + dx, cy + dy), ()):
                        if not seen[j] and orient[j] is not None \
                                and (group is None or group[j] == group[k]) \
                                and _angle_distance(orient[k], orient[j]) <= angle_tol:
                            seen[j] = True
                            stack.append(j)
        chains.append(([pts[k] for k in comp], group[comp[0]] if group is not None else None))
    return chains


def _resolve_scene(doc, path):
    """-> (Scene, scene.Result) for a painted .pxa's `scene:` meta, resolved
    relative to the .pxa's own directory. -> 'error' when the meta is present
    but the file is missing or fails to parse/render. -> None when there is
    nothing to resolve (no `scene:` meta, or no `path` to resolve it against --
    the structure rules simply do not run in that case, same as a character
    sprite). Never raises."""
    scene_name = doc.meta.get("scene")
    if not scene_name or not path:
        return None
    scene_path = os.path.join(os.path.dirname(os.path.abspath(path)), scene_name)
    try:
        sc = scenemod.load(scene_path)
        frame = doc.frame()
        result = scenemod.render_maps(sc, width=frame.width, height=frame.height)
    except Exception:
        return "error"
    return sc, result


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
        # a structure render legitimately fills its bounding box (a full-bleed
        # ground plane, a wall running edge to edge) -- this rule is about a
        # character's silhouette, so it skips a doc whose `@meta` resolves
        # against a `.scene` (a structure/scene render) or that is still at a
        # machine-rendered stage.
        is_structure = bool(doc.meta.get("scene")) or doc.meta.get("stage") in MACHINE_STAGES
        if fill > 0.92 and not is_structure:
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
# stage-aware severity: on a machine-rendered stage (massing/surfaces) the
# hand-craft rules are judging a construction, not a drawing -- the "orphans"
# are the stepped edges of the projection and the "AA" is the shading of a
# single-pixel sliver of a face. Downgrading them to info keeps the findings
# that actually matter (structure, palette/value) from being buried, and
# stops the model from "fixing" the massing instead of painting over it.
# --------------------------------------------------------------------------

MACHINE_STAGES = ("massing", "surfaces")

# the rule names of STATIC_RULES findings that judge hand-drawn craft, as
# opposed to structure (form-*, iso-slope, plane-drift) or palette/value
# rules (unused-colour, stray-colour, redundant-colour, palette-budget,
# colour-density, flat-ramp, low-value-range, blocky-silhouette, ...), which
# keep their normal severity at every stage.
CRAFT_RULE_NAMES = {"orphan-pixel", "jaggies", "doubles", "pillow-shading",
                    "banding", "outer-aa", "dither-spray"}

STAGE_DOWNGRADE_PREFIX = "(massing render -- expected until you paint) "


def stage_note(doc, strict=False):
    """-> the one-line advisory `px lint` should print above its findings when
    the doc is at a machine-rendered stage and the craft-rule downgrade is in
    effect, else None."""
    stage = doc.meta.get("stage")
    if strict or stage not in MACHINE_STAGES:
        return None
    return ("stage: %s -- craft rules are advisory here; they apply once you start painting"
           % stage)


# --------------------------------------------------------------------------
# structure rules -- a painted .pxa whose `@meta scene:` resolves to a .scene
# gets these on top of STATIC_RULES. They compare the painted grid against a
# fresh render of the massing rather than looking at the grid alone.
# --------------------------------------------------------------------------

def rule_form_value(doc, frame, sc, result, cfg, out):
    """Every object's faces must keep the rank order the massing gave their
    tones (light > base > shadow > dark) once painted -- texture and detail
    are allowed to vary the value, not invert which face reads lighter."""
    fid_grid = result.face_id
    if not fid_grid or len(fid_grid) != frame.height or len(fid_grid[0]) != frame.width:
        return
    t = doc.transparent_key()
    ink_rgba = sc.ink_rgba
    palette = doc.palette
    by_object = {}
    for f in result.faces:
        by_object.setdefault(f["object"], []).append(f)
    hits = []
    for obj, faces in by_object.items():
        if len(set(f["tone"] for f in faces)) < 2:
            continue
        measured = []
        for f in faces:
            fid, (x0, y0, x1, y1) = f["id"], f["bbox"]
            total, count = 0.0, 0
            for y in range(y0, y1 + 1):
                row_face, row_chars = fid_grid[y], frame.rows[y]
                for x in range(x0, x1 + 1):
                    if row_face[x] != fid:
                        continue
                    ch = row_chars[x]
                    if ch == t:
                        continue
                    rgba = palette.get(ch)
                    if rgba is None or rgba == ink_rgba:
                        continue
                    total += pxa.luminance(rgba)
                    count += 1
            if count >= 12:
                measured.append((f, total / count, count))
        # a pair is only compared once BOTH faces carry enough painted area to
        # mean something -- a 17-pixel sliver inverted by a single inked
        # keyline crease reads identically to a face genuinely textured away,
        # so the pair-comparison floor is raised well above the per-face
        # measurement floor above (which just decides whether a face is
        # measured at all).
        for i in range(len(measured)):
            fa, meana, ca = measured[i]
            for fb, meanb, cb in measured[i + 1:]:
                if fa["tone"] == fb["tone"]:
                    continue
                if ca < 64 or cb < 64:
                    continue
                ra, rb = _tone_rank(fa["tone"]), _tone_rank(fb["tone"])
                if ra < rb and meana < meanb - 0.5:
                    hits.append((obj, fa, meana, ca, fb, meanb, cb))
                elif rb < ra and meanb < meana - 0.5:
                    hits.append((obj, fb, meanb, cb, fa, meana, ca))
    if hits:
        # the pairs that matter -- the ones backed by the most painted area --
        # come first, instead of being buried among slivers.
        hits.sort(key=lambda h: -min(h[3], h[6]))
        parts, pts = [], []
        for obj, lighter, lm, lcount, darker, dm, dcount in hits:
            parts.append(
                "%s: face %s (%s) %d px reads darker than face %s (%s) %d px -- %.1f vs %.1f"
                % (obj, lighter["face"], lighter["tone"], lcount,
                   darker["face"], darker["tone"], dcount, lm, dm))
            bx0, by0, bx1, by1 = lighter["bbox"]
            pts.append(((bx0 + bx1) // 2, (by0 + by1) // 2))
        out.append(Finding(
            "form-value", "warn",
            "%d face pair(s) invert their massing tone order: %s" % (len(hits), "; ".join(parts[:4])),
            frame.name, pts,
            hint="a face's tone must stay the majority value of that face -- let texture sit "
                 "around the tone the massing gave it, not replace it"))


def rule_form_coverage(doc, frame, sc, result, cfg, out):
    """The painted opaque mask must still roughly match the massing's opaque
    mask -- holes left unpainted, or paint that has drifted outside the
    construction, both mean the painting no longer agrees with the volumes it
    was built from."""
    fid_grid = result.face_id
    if not fid_grid or len(fid_grid) != frame.height or len(fid_grid[0]) != frame.width:
        return
    w, h = frame.width, frame.height
    t = doc.transparent_key()
    painted = [[frame.rows[y][x] != t for x in range(w)] for y in range(h)]
    massing = [[fid_grid[y][x] >= 0 for x in range(w)] for y in range(h)]
    massing_total = sum(1 for row in massing for v in row if v)
    painted_total = sum(1 for row in painted for v in row if v)

    holes = [[massing[y][x] and not painted[y][x] for x in range(w)] for y in range(h)]
    drift = [[painted[y][x] and not massing[y][x] for x in range(w)] for y in range(h)]
    hole_n = sum(1 for row in holes for v in row if v)
    drift_n = sum(1 for row in drift for v in row if v)

    if massing_total and hole_n > 0.06 * massing_total:
        bbox = _largest_component_bbox(holes)
        loc = (" -- largest gap around %d,%d-%d,%d" % bbox) if bbox else ""
        out.append(Finding(
            "form-coverage", "warn",
            "%d px of the massing were left empty%s" % (hole_n, loc), frame.name,
            [((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)] if bbox else [],
            hint="fill a hole back to the face's base tone before adding detail, unless it is "
                 "a deliberately framed opening (a window, a door)"))
    if painted_total and drift_n > 0.10 * painted_total:
        bbox = _largest_component_bbox(drift)
        loc = (" -- largest patch around %d,%d-%d,%d" % bbox) if bbox else ""
        out.append(Finding(
            "form-coverage", "warn",
            "the painting drifted %d px outside the construction%s" % (drift_n, loc), frame.name,
            [((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)] if bbox else [],
            hint="anything outside the massing silhouette should be a deliberate addition (a "
                 "prop, a sign) -- if it is the building itself, fix the scene and re-render "
                 "rather than painting past the wireframe"))


def rule_iso_slope(doc, frame, sc, result, cfg, out):
    """On a 2:1 isometric projection (however the scene arrived at one), the
    outer silhouette must step a clean 2 px across per 1 px down. This is the
    single most common tell of freehand pixel art pretending to be iso."""
    if not _has_iso_slope(sc):
        return
    mask = _mask(doc, frame)
    hits = []
    for side in ("top", "bottom", "left", "right"):
        runs = _edge_runs(mask, side)
        horizontal_param = side in ("top", "bottom")
        n = len(runs)
        i = 0
        while i < n:
            j, direction = i, 0
            while j + 1 < n:
                d = runs[j + 1][0] - runs[j][0]
                if d == 0:
                    break
                dirn = 1 if d > 0 else -1
                if direction == 0:
                    direction = dirn
                elif dirn != direction:
                    break
                j += 1
            total_len = sum(r[2] for r in runs[i:j + 1])
            if j > i and total_len > 6:
                irregular = 0
                for k in range(i, j):
                    len_k = runs[k][2]
                    level_delta = abs(runs[k + 1][0] - runs[k][0])
                    clean = (len_k == 2 * level_delta) if horizontal_param \
                            else (level_delta == 2 * len_k)
                    if not clean:
                        irregular += 1
                allowed = max(1, total_len // 12)
                if irregular > allowed:
                    level_change = abs(runs[j][0] - runs[i][0])
                    if level_change:
                        ratio = (total_len / float(level_change)) if horizontal_param \
                                else (level_change / float(total_len))
                    else:
                        ratio = 0.0
                    pos, lvl = runs[i][1], runs[i][0]
                    coord = (pos, lvl) if horizontal_param else (lvl, pos)
                    hits.append((coord, ratio, total_len))
            i = j + 1 if j > i else i + 1
    if hits:
        out.append(Finding(
            "iso-slope", "warn",
            "%d silhouette run(s) do not hold the isometric 2:1 diagonal (2 px across per "
            "1 px down): %s"
            % (len(hits), "; ".join("~%.1f:1 over %dpx at %d,%d" % (r, l, c[0], c[1])
                                    for c, r, l in hits[:4])),
            frame.name, [c for c, r, l in hits],
            hint="an isometric edge steps exactly 2 px across for every 1 px down -- redraw "
                 "the run to a clean stair rather than freehand"))


def rule_plane_drift(doc, frame, sc, result, cfg, out):
    """A detail edge (a window, a plank, a trim line) drawn screen-horizontal
    or screen-vertical *inside* a face whose own projected tangents are
    neither is drawn by habit, not by the plane it sits on: a roof slope or a
    gable end needs its detail sheared with the plane, the way the face's own
    geometry already is. A face that genuinely has an axis-aligned tangent
    (any wall in a yaw=0 view, the front face at iso) is exempt entirely."""
    fid_grid = result.face_id
    if not fid_grid or len(fid_grid) != frame.height or len(fid_grid[0]) != frame.width:
        return
    t = doc.transparent_key()
    pts = _interior_edge_points(frame, fid_grid, t)
    if len(pts) < 8:
        return
    try:
        axes = scenemod._axes(sc)
    except Exception:
        return

    faces_by_id = dict((f["id"], f) for f in result.faces)
    exempt_cache = {}

    def is_exempt(fid):
        if fid not in exempt_cache:
            f = faces_by_id.get(fid)
            exempt_cache[fid] = True if f is None else _face_has_axis_tangent(axes, f["normal"])
        return exempt_cache[fid]

    coords = [(p[0], p[1]) for p in pts]
    group = [p[2] for p in pts]
    candidates = []
    for cluster, fid in _edge_chains(coords, group=group):
        if len(cluster) < 8 or fid is None or is_exempt(fid):
            continue
        deg, length, straightness, start = _line_fit(cluster)
        if length < 8 or straightness > 0.02:
            continue
        d_horiz, d_vert = _angle_distance(deg, 0.0), _angle_distance(deg, 90.0)
        if min(d_horiz, d_vert) > 5.0:
            continue
        orientation = "horizontal" if d_horiz <= d_vert else "vertical"
        ref_deg = 0.0 if orientation == "horizontal" else 90.0
        f = faces_by_id[fid]
        tangents = _face_screen_tangents(axes, f["normal"])
        near = min(tangents, key=lambda v: _angle_distance(_screen_angle(v) or 0.0, ref_deg))
        candidates.append((length, orientation, (int(round(start[0])), int(round(start[1]))),
                          f, _ratio_desc(near)))
    if candidates:
        candidates.sort(key=lambda c: -c[0])
        worst = candidates[:3]
        parts = ["%s/%s: a %d px %s edge at %d,%d sits on a face whose axes run %s -- "
                "shear the detail with the plane"
                % (f["object"], f["face"], length, orientation, sx, sy, ratio)
                for length, orientation, (sx, sy), f, ratio in worst]
        out.append(Finding(
            "plane-drift", "info", "; ".join(parts), frame.name,
            [(sx, sy) for _l, _o, (sx, sy), _f, _r in worst],
            hint="a window, plank or trim line on a slanted face should follow that face's own "
                 "edge direction, not the horizontal/vertical grid -- check `px scene faces` "
                 "for the face's slope"))


STRUCTURE_RULES = [rule_form_value, rule_form_coverage, rule_iso_slope, rule_plane_drift]


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def run(doc, cfg=None, frames=None, animation=True, path=None, scene=True, strict=False):
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
    if scene and doc.meta.get("scene") and path:
        resolved = _resolve_scene(doc, path)
        if resolved == "error":
            out.append(Finding(
                "form-check", "info",
                "could not check the massing: %r does not exist or failed to parse/render"
                % doc.meta.get("scene"), None,
                hint="re-render the scene, or fix the path in @meta scene:"))
        elif resolved:
            sc, result = resolved
            for f in targets:
                for rule in STRUCTURE_RULES:
                    try:
                        rule(doc, f, sc, result, cfg, out)
                    except Exception as exc:
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
    if not strict and doc.meta.get("stage") in MACHINE_STAGES:
        for finding in out:
            if finding.rule in CRAFT_RULE_NAMES:
                finding.severity = "info"
                finding.message = STAGE_DOWNGRADE_PREFIX + finding.message
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
