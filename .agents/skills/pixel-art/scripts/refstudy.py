"""Reference analysis.

Turns "make it look like these" into numbers the pipeline can actually honour:
palette, ramp structure, hue-shift amount, value range, outline convention,
dither density, projection, subject size, and the native resolution the
reference was drawn at.
"""

import os
import math

import pxa
import imaging
import palettes
import render
import font3x5 as f35


# --------------------------------------------------------------------------
# projection: edge-orientation histogram over 3x3 Sobel gradients
# --------------------------------------------------------------------------

def _gray(pixels):
    return [[0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in row] for row in pixels]


def edge_orientation_peaks(pixels, top_fraction=0.15, bin_deg=2, min_share=0.03):
    """Sobel edge orientation histogram of the top `top_fraction` strongest
    gradients, as up to 5 well-separated peaks `[angle_deg, share]` (angle in
    0..180, edge orientation -- perpendicular to the gradient direction)."""
    w, h = imaging.size_of(pixels)
    if w < 3 or h < 3:
        return []
    gray = _gray(pixels)
    mags, thetas = [], []
    for y in range(1, h - 1):
        r0, r1, r2 = gray[y - 1], gray[y], gray[y + 1]
        for x in range(1, w - 1):
            gx = (r0[x + 1] + 2 * r1[x + 1] + r2[x + 1]) - (r0[x - 1] + 2 * r1[x - 1] + r2[x - 1])
            gy = (r2[x - 1] + 2 * r2[x] + r2[x + 1]) - (r0[x - 1] + 2 * r0[x] + r0[x + 1])
            mags.append((gx * gx + gy * gy) ** 0.5)
            thetas.append((math.degrees(math.atan2(gy, gx)) + 90.0) % 180.0)
    if not mags:
        return []
    cut = sorted(mags)[int(len(mags) * (1.0 - top_fraction))]
    nbins = int(180 / bin_deg)
    bins = [0.0] * nbins
    total = 0
    for mag, theta in zip(mags, thetas):
        if mag < cut or mag <= 0:
            continue
        bins[int(theta // bin_deg) % nbins] += 1
        total += 1
    if not total:
        return []
    smooth = [(bins[(i - 1) % nbins] + bins[i] + bins[(i + 1) % nbins]) / 3.0 for i in range(nbins)]
    # smoothing locates peak *centres* robustly, but two real edges that fall
    # either side of a bin boundary (e.g. a dead-on 90deg edge split between
    # bins 88 and 89) would otherwise show up as two separate, understated
    # peaks -- so centres within one smoothing window of each other are
    # merged before any mass is counted.
    centres = [i for i in range(nbins) if smooth[i] > 0
              and smooth[i] >= smooth[(i - 1) % nbins] and smooth[i] >= smooth[(i + 1) % nbins]]
    centres.sort(key=lambda i: -smooth[i])
    kept = []
    for i in centres:
        angle = i * bin_deg + bin_deg / 2.0
        if any(min(abs(angle - a), 180 - abs(angle - a)) <= 2 * bin_deg for a in kept):
            continue
        kept.append(angle)
    if not kept:
        return []
    # assign every bin's raw mass to its nearest surviving centre (a circular
    # Voronoi split) so shares are exact and never double-counted.
    mass = [0.0] * len(kept)
    for i in range(nbins):
        if not bins[i]:
            continue
        angle = i * bin_deg + bin_deg / 2.0
        j = min(range(len(kept)), key=lambda k: min(abs(angle - kept[k]), 180 - abs(angle - kept[k])))
        mass[j] += bins[i]
    peaks = [(kept[j], mass[j] / total) for j in range(len(kept)) if mass[j] / total >= min_share]
    peaks.sort(key=lambda t: -t[1])
    return [[round(a, 1), round(s, 3)] for a, s in peaks[:5]]


_AXIS_TARGETS = (0.0, 90.0)
_ISO21_TARGETS = (26.6, 153.4)
_ISO30_TARGETS = (30.0, 150.0)
_OBLIQUE_TARGETS = (45.0, 135.0)


def _angular_distance(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def _in_band(angle, targets, tol=4.0):
    return any(_angular_distance(angle, t) <= tol for t in targets)


def _share_in(peaks, targets, tol=4.0):
    return sum(s for a, s in peaks if _in_band(a, targets, tol))


def _strongest_outside(peaks, targets, tol=4.0):
    best = None
    for a, s in peaks:
        if _in_band(a, targets, tol):
            continue
        if best is None or s > best[1]:
            best = (a, s)
    return best


def classify_projection(peaks):
    """-> a human-readable projection guess from `edge_orientation_peaks` output.

    Real, painterly references rarely put an absolute majority of their edge
    energy on one exact set of angles -- roofs, dithering and rounded shapes
    all steal share from whichever axis is actually dominant. So this reads
    *relative* dominance instead of an absolute cut: A/I/I30/O are the shares
    that land within +-4deg of the axis-aligned, 2:1-isometric, 30deg-isometric
    and oblique angle pairs; a family wins when its own share clears a small
    floor (10%) and is not swamped by the axis-aligned family (>= 0.6x it for
    the diagonal families; axis-aligned instead needs to itself dominate every
    diagonal family by a wide margin, since 0/90deg edges are common even in
    isometric and oblique art)."""
    if not peaks:
        return "unclear -- decide by eye"
    a_share = _share_in(peaks, _AXIS_TARGETS)
    i_share = _share_in(peaks, _ISO21_TARGETS)
    i30_share = _share_in(peaks, _ISO30_TARGETS)
    o_share = _share_in(peaks, _OBLIQUE_TARGETS)
    if i_share >= 0.10 and i_share >= 0.6 * a_share:
        return "isometric 2:1"
    if i30_share >= 0.10 and i30_share >= 0.6 * a_share:
        return "isometric 30deg (true iso)"
    if o_share >= 0.10 and o_share >= 0.6 * a_share:
        return "oblique"
    if a_share >= 0.30 and a_share > 1.8 * max(i_share, i30_share, o_share):
        guess = "axis-aligned (side view or 3/4 top-down)"
        all_targets = _AXIS_TARGETS + _ISO21_TARGETS + _ISO30_TARGETS + _OBLIQUE_TARGETS
        other = _strongest_outside(peaks, all_targets)
        if other and other[1] >= 0.04:
            acute = min(other[0], 180 - other[0])
            guess += "; roof pitch ~%d deg" % round(acute)
        return guess
    return "unclear -- decide by eye"


# --------------------------------------------------------------------------
# subject size: bbox of everything that is not background
# --------------------------------------------------------------------------

def _border_pixels(pixels, w, h):
    pts = [pixels[0][x] for x in range(w)] + [pixels[h - 1][x] for x in range(w)]
    pts += [pixels[y][0] for y in range(1, h - 1)] + [pixels[y][w - 1] for y in range(1, h - 1)]
    return pts


def _background_colours(pixels, w, h):
    """-> None (background is transparency) or a list of reference colours a
    pixel counts as background if it lands within `pxa.color_distance` 12 of
    -- the most common border colour, plus up to two desaturated border greys
    to catch a checker backdrop."""
    border = _border_pixels(pixels, w, h)
    if any(p[3] == 0 for p in border):
        return None
    counts = {}
    for p in border:
        counts[p] = counts.get(p, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    bg = [ranked[0][0]]
    for c, _ in ranked[:8]:
        if pxa.rgb_to_hsl(c)[1] < 5 and c not in bg:
            bg.append(c)
        if len(bg) >= 3:
            break
    return bg


def _is_background(p, bg):
    if bg is None:
        return p[3] == 0
    for c in bg:
        if p == c or pxa.color_distance(p, c) <= 12:
            return True
    return False


def subject_bbox(pixels):
    """-> (x, y, w, h) of everything that is not background. Falls back to the
    full canvas when every pixel reads as background."""
    w, h = imaging.size_of(pixels)
    bg = _background_colours(pixels, w, h)
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = pixels[y]
        for x in range(w):
            if not _is_background(row[x], bg):
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    if maxx < 0:
        return (0, 0, w, h)
    return (minx, miny, maxx - minx + 1, maxy - miny + 1)


def _round_up8(v):
    return ((int(v) + 7) // 8) * 8


def _canvas_for_subject(bbox, native_w, native_h):
    _, _, sw, sh = bbox
    cw = min(native_w, _round_up8(sw + 8))
    ch = min(native_h, _round_up8(sh + 8))
    return cw, ch


def study(path, colors=16, max_side=192, scale=None):
    """`scale`, when given, overrides pixel-scale detection outright -- for a
    reference whose native pixel grid was smoothed away by resampling (a
    common fate for JPEG exports) and so cannot be recovered automatically;
    `px ref --scale N` is the escape hatch once a human has looked and knows."""
    px, w, h = imaging.load_image(path)
    if scale:
        scale_report = {"scale": int(scale), "method": "override", "confidence": 1.0,
                        "hint_scale": None}
    else:
        scale_report = imaging.detect_pixel_scale_report(px)
    scale = scale_report["scale"]
    native = px
    if scale > 1:
        native = imaging.nearest_resize(px, w // scale, h // scale)
    nw, nh = imaging.size_of(native)

    edge_peaks = edge_orientation_peaks(native)
    projection_guess = classify_projection(edge_peaks)

    bbox = subject_bbox(native)
    canvas_w, canvas_h = _canvas_for_subject(bbox, nw, nh)

    work = native
    if max(nw, nh) > max_side:
        f = max_side / float(max(nw, nh))
        work = imaging.box_resize(native, max(1, int(nw * f)), max(1, int(nh * f)))

    opaque = [p for row in work for p in row if p[3] > 24]
    exact = set(opaque)
    pal = palettes.extract(work, colors) if len(exact) > colors else \
        palettes.sort_palette(list(exact))

    # the same "big photo-like image, scale detection gave up" test `px ref`
    # uses to print its "no clean pixel grid found" note -- when it is true,
    # `subject_size`/`suggested_canvas` below are derived from a pixel grid
    # that was never actually recovered, so callers must not trust them at
    # face value (see `scale_confident` in the returned dict).
    scale_confident = not (scale_report["method"] == "none" and (w > 300 or h > 300)
                           and len(exact) > 2000)

    counts = palettes.usage(work, pal) if pal else []
    total = sum(counts) or 1
    lums = [pxa.luminance(c) for c in pal] or [0]
    sats = [pxa.rgb_to_hsl(c)[1] for c in pal] or [0]
    ramps = palettes.ramps_of(pal)

    hue_shift = 0.0
    measured = 0
    for r in ramps:
        if len(r) < 3:
            continue
        hs = [pxa.rgb_to_hsl(c) for c in r]
        if max(s for _, s, _ in hs) < 8:
            continue
        spread = max(h_ for h_, _, _ in hs) - min(h_ for h_, _, _ in hs)
        if spread > 180:
            spread = 360 - spread
        hue_shift += spread
        measured += 1
    hue_shift = round(hue_shift / measured, 1) if measured else 0.0

    checker = 0
    for y in range(1, len(work) - 1):
        for x in range(1, len(work[0]) - 1):
            c = work[y][x]
            if c[3] == 0:
                continue
            if work[y][x - 1] == work[y][x + 1] != c and work[y - 1][x] == work[y + 1][x] != c:
                checker += 1
    dither = round(checker / float(len(opaque) or 1), 3)

    darkest = min(pal, key=pxa.luminance) if pal else (0, 0, 0, 255)
    dark_share = counts[pal.index(darkest)] / float(total) if pal else 0.0

    return {
        "path": path,
        "file_size": "%dx%d" % (w, h),
        "pixel_scale": scale,
        "scale_method": scale_report["method"],
        "scale_confidence": scale_report["confidence"],
        "scale_hint": scale_report.get("hint_scale"),
        "native_size": "%dx%d" % (nw, nh),
        "unique_colors": len(exact),
        "palette": [pxa.format_hex(c) for c in pal],
        "palette_rgba": pal,
        "usage_pct": [round(100.0 * c / total, 1) for c in counts],
        "value_range": [round(min(lums)), round(max(lums))],
        "saturation": [round(min(sats)), round(max(sats))],
        "ramps": [[pxa.format_hex(c) for c in r] for r in ramps if len(r) > 1],
        "hue_shift_deg": hue_shift,
        "dither_density": dither,
        "outline": ("dark keyline (%.0f%% of pixels are the darkest colour)" % (dark_share * 100)
                    if dark_share > 0.10 else "no strong outline convention"),
        "edge_peaks": edge_peaks,
        "projection_guess": projection_guess,
        "subject_size": "%dx%d" % (bbox[2], bbox[3]),
        "subject_bbox": list(bbox),
        "suggested_canvas": "%dx%d" % (canvas_w, canvas_h),
        "scale_confident": scale_confident,
    }


def brief(reports):
    """Merge several reference studies into one art-direction brief."""
    all_colors = []
    for r in reports:
        all_colors.extend(r["palette_rgba"])
    merged = palettes.extract([all_colors], min(32, max(8, len(all_colors) // 2))) \
        if all_colors else []
    hue = [r["hue_shift_deg"] for r in reports]
    dither = [r["dither_density"] for r in reports]
    lo = min(r["value_range"][0] for r in reports) if reports else 0
    hi = max(r["value_range"][1] for r in reports) if reports else 100
    canvases = [tuple(int(v) for v in r["suggested_canvas"].split("x")) for r in reports]
    canvas = (max(c[0] for c in canvases), max(c[1] for c in canvases)) if canvases else (32, 32)
    # The floor a brief must clear is the SMALLEST reference subject, not the
    # largest: one reference whose pixel grid could not be recovered (a smooth
    # resample, a photo of a screen) would otherwise force an absurd canvas.
    # The largest stays in the report as the "suggested" size to aim at.
    floor = (min(c[0] for c in canvases), min(c[1] for c in canvases)) if canvases else (32, 32)
    # if the floor was set (in whole or in part) by a reference whose scale
    # detection failed, the floor itself cannot be trusted -- `px brief`
    # skips the hard gate in that case rather than enforcing a number that
    # was never actually measured.
    floor_reports = [r for r, c in zip(reports, canvases) if c[0] == floor[0] or c[1] == floor[1]]
    floor_confident = all(r.get("scale_confident", True) for r in floor_reports)
    return {
        "sources": [os.path.basename(r["path"]) for r in reports],
        "merged_palette": [pxa.format_hex(c) for c in merged],
        "merged_palette_rgba": merged,
        "hue_shift_deg": round(sum(hue) / len(hue), 1) if hue else 0.0,
        "dither_density": round(sum(dither) / len(dither), 3) if dither else 0.0,
        "value_range": [lo, hi],
        "native_sizes": [r["native_size"] for r in reports],
        "suggested_canvas": "%dx%d" % canvas,
        "minimum_canvas": "%dx%d" % floor,
        "floor_confident": floor_confident,
        "outline": reports[0]["outline"] if reports else "",
    }


def contact_sheet(reports, out_path, cell=180):
    """Reference thumbnails next to their extracted palettes -- look at this
    before deciding the palette, not after."""
    panels = []
    for r in reports:
        px, w, h = imaging.load_image(r["path"])
        f = cell / float(max(w, h))
        thumb = imaging.box_resize(px, max(1, int(w * f)), max(1, int(h * f)))
        panels.append((r, thumb))
    rowh = cell + 46
    width = max(cell * 2 + 40, 420)
    img = imaging.new_image(width, rowh * len(panels) + 10, render.BG)
    y = 6
    for r, thumb in panels:
        tw, th = imaging.size_of(thumb)
        imaging.paste(img, thumb, 6, y, blend=False)
        render._border(img, 5, y - 1, tw + 2, th + 2)
        tx = tw + 16
        f35.draw_text(img, tx, y, os.path.basename(r["path"])[:34], render.ACCENT)
        f35.draw_text(img, tx, y + 9, "NATIVE %s  SCALE X%d  %d COLOURS"
                      % (r["native_size"], r["pixel_scale"], r["unique_colors"]), render.DIM)
        f35.draw_text(img, tx, y + 18, "VALUE %d-%d  HUESHIFT %s DEG  DITHER %s"
                      % (r["value_range"][0], r["value_range"][1],
                         r["hue_shift_deg"], r["dither_density"]), render.DIM)
        sx, sy = tx, y + 30
        for i, c in enumerate(r["palette_rgba"]):
            cx = sx + (i % 12) * 13
            cy = sy + (i // 12) * 13
            render._panel(img, cx, cy, 11, 11, c)
            render._border(img, cx, cy, 11, 11, (14, 14, 18, 255))
        y += rowh
    return pxa.write_png(out_path, img)
