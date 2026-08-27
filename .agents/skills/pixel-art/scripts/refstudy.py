"""Reference analysis.

Turns "make it look like these" into numbers the pipeline can actually honour:
palette, ramp structure, hue-shift amount, value range, outline convention,
dither density, and the native resolution the reference was drawn at.
"""

import os

import pxa
import imaging
import palettes
import render
import font3x5 as f35


def study(path, colors=16, max_side=192):
    px, w, h = imaging.load_image(path)
    scale = imaging.detect_pixel_scale(px)
    native = px
    if scale > 1:
        native = imaging.nearest_resize(px, w // scale, h // scale)
    nw, nh = imaging.size_of(native)
    work = native
    if max(nw, nh) > max_side:
        f = max_side / float(max(nw, nh))
        work = imaging.box_resize(native, max(1, int(nw * f)), max(1, int(nh * f)))

    opaque = [p for row in work for p in row if p[3] > 24]
    exact = set(opaque)
    pal = palettes.extract(work, colors) if len(exact) > colors else \
        palettes.sort_palette(list(exact))

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
        "suggested_canvas": _suggest_canvas(nw, nh),
    }


def _suggest_canvas(w, h):
    for s in (16, 24, 32, 48, 64, 96, 128):
        if max(w, h) <= s:
            return "%dx%d" % (s, s)
    return "%dx%d" % (w, h)


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
    return {
        "sources": [os.path.basename(r["path"]) for r in reports],
        "merged_palette": [pxa.format_hex(c) for c in merged],
        "merged_palette_rgba": merged,
        "hue_shift_deg": round(sum(hue) / len(hue), 1) if hue else 0.0,
        "dither_density": round(sum(dither) / len(dither), 3) if dither else 0.0,
        "value_range": [lo, hi],
        "native_sizes": [r["native_size"] for r in reports],
        "suggested_canvas": reports[0]["suggested_canvas"] if reports else "32x32",
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
