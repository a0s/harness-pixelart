"""Palette work: extraction from references, ramp construction, snapping,
and loading from files / bundled sets / Lospec."""

import os
import re
import json
import random

import pxa
import imaging

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets", "palettes")


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def parse_palette_text(text):
    """Accepts .hex (one hex per line), .gpl (GIMP), JASC .pal, or CSV."""
    colors = []
    lines = text.splitlines()
    if lines and lines[0].strip().upper().startswith("JASC-PAL"):
        for line in lines[3:]:
            parts = line.split()
            if len(parts) >= 3:
                colors.append((int(parts[0]), int(parts[1]), int(parts[2]), 255))
        return colors
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") and len(line) > 9 and not re.match(r"^#[0-9a-fA-F]{3,8}$", line):
            continue
        if line.lower().startswith(("gimp palette", "name:", "columns:")):
            continue
        m = re.match(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b", line)
        if m:
            colors.append(pxa.parse_hex(m.group(1)))
            continue
        parts = line.replace(",", " ").split()
        if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
            colors.append((int(parts[0]), int(parts[1]), int(parts[2]), 255))
    return colors


def load_palette(source):
    """source: path to a palette file or image, a bundled name, or 'lospec:slug'."""
    if source.startswith("lospec:"):
        return fetch_lospec(source.split(":", 1)[1])
    cand = [source,
            os.path.join(ASSETS, source),
            os.path.join(ASSETS, source + ".hex")]
    for path in cand:
        if os.path.isfile(path):
            if path.lower().endswith((".png", ".gif", ".jpg", ".jpeg", ".bmp", ".webp")):
                px, _, _ = imaging.load_image(path)
                seen, out = set(), []
                for row in px:
                    for p in row:
                        if p[3] > 0 and p not in seen:
                            seen.add(p); out.append(p)
                return sort_palette(out)
            with open(path, "r") as fh:
                return parse_palette_text(fh.read())
    raise pxa.PxaError("palette not found: %s (try `px palette list`)" % source)


def bundled_names():
    if not os.path.isdir(ASSETS):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(ASSETS) if f.endswith(".hex"))


def fetch_lospec(slug):
    import urllib.request
    url = "https://lospec.com/palette-list/%s.json" % slug
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [pxa.parse_hex(c) for c in data.get("colors", [])]


def save_hex(colors, path):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w") as fh:
        fh.write("\n".join(pxa.format_hex(c)[1:] for c in colors) + "\n")
    return path


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def _median_cut(samples, n):
    boxes = [samples]
    while len(boxes) < n:
        boxes.sort(key=lambda b: -_box_volume(b))
        target = None
        for b in boxes:
            if len(b) > 1:
                target = b
                break
        if target is None:
            break
        boxes.remove(target)
        ch = _widest_channel(target)
        target.sort(key=lambda p: p[ch])
        mid = len(target) // 2
        boxes.append(target[:mid])
        boxes.append(target[mid:])
    out = []
    for b in boxes:
        if not b:
            continue
        r = sum(p[0] for p in b) // len(b)
        g = sum(p[1] for p in b) // len(b)
        bl = sum(p[2] for p in b) // len(b)
        out.append((r, g, bl, 255))
    return out


def _box_volume(box):
    if not box:
        return 0
    return max((max(p[c] for p in box) - min(p[c] for p in box)) for c in range(3)) * len(box) ** 0.5


def _widest_channel(box):
    return max(range(3), key=lambda c: max(p[c] for p in box) - min(p[c] for p in box))


def extract(pixels, n=16, refine=6, sample_cap=6000, seed=7):
    """Extract an n-colour palette from an rgba grid (transparent pixels ignored)."""
    flat = [p for row in pixels for p in row if p[3] > 24]
    if not flat:
        return []
    rnd = random.Random(seed)
    samples = flat if len(flat) <= sample_cap else rnd.sample(flat, sample_cap)
    centers = _median_cut([list(s) for s in samples], n)
    centers = [tuple(c) for c in centers]
    for _ in range(refine):                     # k-means refinement in Lab space
        buckets = [[] for _ in centers]
        for p in samples:
            buckets[pxa.nearest_color(p, centers)].append(p)
        moved = []
        for i, b in enumerate(buckets):
            if not b:
                moved.append(centers[i]); continue
            moved.append((sum(p[0] for p in b) // len(b),
                          sum(p[1] for p in b) // len(b),
                          sum(p[2] for p in b) // len(b), 255))
        if moved == centers:
            break
        centers = moved
    uniq = []
    for c in centers:
        if c not in uniq:
            uniq.append(c)
    return sort_palette(uniq)


def sort_palette(colors):
    """Group by hue family, order by luminance inside each family -- this is how
    an artist reads a palette (ramps first, greys last)."""
    def key(c):
        h, s, l = pxa.rgb_to_hsl(c)
        family = 99 if s < 8 else int(h // 30)
        return (family, pxa.luminance(c))
    return sorted(colors, key=key)


def usage(pixels, palette):
    counts = [0] * len(palette)
    for row in pixels:
        for p in row:
            if p[3] > 0:
                counts[pxa.nearest_color(p, palette)] += 1
    return counts


# --------------------------------------------------------------------------
# ramp construction
# --------------------------------------------------------------------------

def ramp(base, steps=5, hue_shift=22.0, shadow_hue=250.0, light_hue=45.0,
         lum_low=18.0, lum_high=92.0, sat_boost=12.0):
    """Build a hue-shifted value ramp around `base`.

    Shadows rotate toward `shadow_hue` (cool) and gain saturation; highlights
    rotate toward `light_hue` (warm) and lose it. This is the single biggest
    difference between painted-looking pixel art and flat dead ramps."""
    h0, s0, l0 = pxa.rgb_to_hsl(base)
    out = []
    for i in range(steps):
        t = i / float(max(1, steps - 1))          # 0 = darkest, 1 = lightest
        lum = lum_low + (lum_high - lum_low) * t
        d = t - 0.5
        target = light_hue if d > 0 else shadow_hue
        amount = hue_shift * abs(d) * 2.0
        h = _hue_toward(h0, target, amount)
        s = s0 + sat_boost * (0.5 - abs(d) * 2 * 0.5) - (t - 0.5) * sat_boost * 1.2
        out.append(pxa.hsl_to_rgb(h, max(0.0, min(100.0, s)), lum))
    return out


def _hue_toward(h, target, amount):
    diff = ((target - h + 180.0) % 360.0) - 180.0
    step = max(-abs(diff), min(abs(diff), diff))
    return (h + (step / abs(diff) if diff else 0) * min(amount, abs(diff))) % 360.0


def ramps_of(palette, max_gap=26.0):
    """Cluster a flat palette into probable ramps (same hue family, rising value)."""
    groups = {}
    for c in palette:
        h, s, l = pxa.rgb_to_hsl(c)
        fam = "grey" if s < 8 else str(int(h // 30))
        groups.setdefault(fam, []).append(c)
    out = []
    for fam, cols in groups.items():
        cols.sort(key=pxa.luminance)
        cur = [cols[0]]
        for c in cols[1:]:
            if pxa.luminance(c) - pxa.luminance(cur[-1]) <= max_gap:
                cur.append(c)
            else:
                out.append(cur); cur = [c]
        out.append(cur)
    return [r for r in out if r]


# --------------------------------------------------------------------------
# snapping
# --------------------------------------------------------------------------

def snap_pixels(pixels, palette, dither="none", strength=1.0, alpha_cut=128):
    """Quantise an rgba grid to `palette`. dither: none|bayer2|bayer4|bayer8|fs|atkinson."""
    w, h = imaging.size_of(pixels)
    buf = [[list(p) for p in row] for row in pixels]
    out = [[(0, 0, 0, 0)] * w for _ in range(h)]
    if dither.startswith("bayer"):
        n = int(dither[5:] or 4)
        m = _bayer(n)
        span = _mean_step(palette) * strength
        for y in range(h):
            for x in range(w):
                p = buf[y][x]
                if p[3] < alpha_cut:
                    continue
                t = (m[y % n][x % n] / float(n * n)) - 0.5
                cand = (max(0, min(255, int(p[0] + t * span))),
                        max(0, min(255, int(p[1] + t * span))),
                        max(0, min(255, int(p[2] + t * span))), 255)
                out[y][x] = palette[pxa.nearest_color(cand, palette)]
        return out
    if dither in ("fs", "atkinson"):
        kernels = {
            "fs": [(1, 0, 7 / 16.0), (-1, 1, 3 / 16.0), (0, 1, 5 / 16.0), (1, 1, 1 / 16.0)],
            "atkinson": [(1, 0, .125), (2, 0, .125), (-1, 1, .125), (0, 1, .125),
                         (1, 1, .125), (0, 2, .125)],
        }[dither]
        for y in range(h):
            for x in range(w):
                p = buf[y][x]
                if p[3] < alpha_cut:
                    continue
                cur = (max(0, min(255, int(p[0]))), max(0, min(255, int(p[1]))),
                       max(0, min(255, int(p[2]))), 255)
                new = palette[pxa.nearest_color(cur, palette)]
                out[y][x] = new
                err = [(cur[i] - new[i]) * strength for i in range(3)]
                for dx, dy, wgt in kernels:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        for i in range(3):
                            buf[ny][nx][i] += err[i] * wgt
        return out
    for y in range(h):
        for x in range(w):
            p = pixels[y][x]
            if p[3] >= alpha_cut:
                out[y][x] = palette[pxa.nearest_color(p, palette)]
    return out


def _bayer(n):
    m = [[0]]
    size = 1
    while size < n:
        m = [[4 * v for v in row] + [4 * v + 2 for v in row] for row in m] + \
            [[4 * v + 3 for v in row] + [4 * v + 1 for v in row] for row in m]
        size *= 2
    return m


def _mean_step(palette):
    if len(palette) < 2:
        return 0.0
    lums = sorted(pxa.luminance(c) for c in palette)
    gaps = [lums[i + 1] - lums[i] for i in range(len(lums) - 1)]
    return (sum(gaps) / len(gaps)) * 2.55 * 1.6
