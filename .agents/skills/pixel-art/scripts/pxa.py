"""Core library for the .pxa pixel-art source format.

A .pxa file is a plain-text, diff-friendly, LLM-editable representation of an
indexed pixel image: a palette of single-character keys plus one grid of
characters per animation frame.

Everything in this module works on the Python standard library alone.
Pillow is only needed for reading raster references (see imaging.py).
"""

import os
import re
import zlib
import struct
import colorsys

TRANSPARENT_KEY = "."
DEFAULT_FRAME = "main"

# Character alphabet offered to callers that need to allocate new palette keys.
# '.' is reserved for transparency; visually confusable pairs are kept but
# ordered so the most legible characters get handed out first.
KEY_ALPHABET = "KWRGBYOPCMNVIDEFHJLSTUXZ" + "abcdefghijklmnopqrstuvwxyz" + "0123456789" + "+*#%$&@=~"

# Keys ordered from visually heaviest to lightest. When the palette is assigned
# in luminance order from this alphabet, the raw grid text reads as a rough
# ASCII picture of the sprite -- which is the whole point of a text format:
# the model can see the drawing without rendering it.
DENSITY_KEYS = "@#%$&8BMWNHKREXSAouc=+-:;'`"


class PxaError(Exception):
    pass


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------

def parse_hex(text):
    """'#rgb' / '#rrggbb' / '#rrggbbaa' -> (r, g, b, a)."""
    s = text.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s) + "ff"
    elif len(s) == 4:
        s = "".join(c * 2 for c in s)
    elif len(s) == 6:
        s = s + "ff"
    elif len(s) != 8:
        raise PxaError("bad hex colour: %r" % text)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4, 6))
    except ValueError:
        raise PxaError("bad hex colour: %r" % text)


def format_hex(rgba, force_alpha=False):
    r, g, b, a = rgba
    if a == 255 and not force_alpha:
        return "#%02x%02x%02x" % (r, g, b)
    return "#%02x%02x%02x%02x" % (r, g, b, a)


def rgb_to_hsl(rgba):
    r, g, b = [c / 255.0 for c in rgba[:3]]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return (h * 360.0, s * 100.0, l * 100.0)


def hsl_to_rgb(h, s, l, a=255):
    r, g, b = colorsys.hls_to_rgb((h % 360.0) / 360.0, max(0.0, min(1.0, l / 100.0)),
                                  max(0.0, min(1.0, s / 100.0)))
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)), a)


def luminance(rgba):
    """Perceptual luminance 0..100 (Rec. 709 on linearised channels)."""
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [lin(c) for c in rgba[:3]]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) * 100.0


def contrast_ratio(c1, c2):
    l1, l2 = luminance(c1) / 100.0, luminance(c2) / 100.0
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _srgb_to_lab(rgba):
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [lin(c) for c in rgba[:3]]
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    xn, yn, zn = 0.95047, 1.0, 1.08883
    def f(t):
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t + 16.0 / 116.0)
    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def color_distance(c1, c2):
    """Perceptual distance (CIE76 in Lab). Good enough for palette matching."""
    l1, a1, b1 = _srgb_to_lab(c1)
    l2, a2, b2 = _srgb_to_lab(c2)
    return ((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2) ** 0.5


def nearest_color(rgba, candidates):
    """Return index of the perceptually closest colour in `candidates`."""
    best, best_d = 0, None
    for i, c in enumerate(candidates):
        d = color_distance(rgba, c)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


# --------------------------------------------------------------------------
# document model
# --------------------------------------------------------------------------

class Swatch(object):
    __slots__ = ("key", "rgba", "name")

    def __init__(self, key, rgba, name=""):
        self.key = key
        self.rgba = rgba
        self.name = name or ""

    @property
    def is_transparent(self):
        return self.rgba[3] == 0

    def __repr__(self):
        return "Swatch(%r, %s, %r)" % (self.key, format_hex(self.rgba), self.name)


class Frame(object):
    __slots__ = ("name", "rows")

    def __init__(self, name, rows):
        self.name = name
        self.rows = list(rows)

    @property
    def width(self):
        return len(self.rows[0]) if self.rows else 0

    @property
    def height(self):
        return len(self.rows)

    def get(self, x, y):
        if 0 <= y < len(self.rows) and 0 <= x < len(self.rows[y]):
            return self.rows[y][x]
        return None

    def set(self, x, y, key):
        if not (0 <= y < len(self.rows) and 0 <= x < len(self.rows[y])):
            return False
        row = self.rows[y]
        self.rows[y] = row[:x] + key + row[x + 1:]
        return True

    def copy(self, name=None):
        return Frame(name or self.name, list(self.rows))

    def counts(self):
        out = {}
        for row in self.rows:
            for ch in row:
                out[ch] = out.get(ch, 0) + 1
        return out


class Doc(object):
    def __init__(self, meta=None, swatches=None, frames=None):
        self.meta = dict(meta or {})
        self.swatches = list(swatches or [])
        self.frames = list(frames or [])

    # -- palette access ---------------------------------------------------
    @property
    def palette(self):
        return dict((s.key, s.rgba) for s in self.swatches)

    def swatch(self, key):
        for s in self.swatches:
            if s.key == key:
                return s
        return None

    def rgba(self, key):
        s = self.swatch(key)
        return s.rgba if s else (0, 0, 0, 0)

    def opaque_swatches(self):
        return [s for s in self.swatches if not s.is_transparent]

    def transparent_key(self):
        for s in self.swatches:
            if s.is_transparent:
                return s.key
        return TRANSPARENT_KEY

    def free_key(self):
        used = set(s.key for s in self.swatches)
        for ch in KEY_ALPHABET:
            if ch not in used:
                return ch
        raise PxaError("palette is full (no free key characters left)")

    def add_swatch(self, rgba, name="", key=None):
        for s in self.swatches:
            if s.rgba == rgba:
                return s
        sw = Swatch(key or self.free_key(), rgba, name)
        self.swatches.append(sw)
        return sw

    # -- frame access -----------------------------------------------------
    @property
    def width(self):
        return self.frames[0].width if self.frames else 0

    @property
    def height(self):
        return self.frames[0].height if self.frames else 0

    def frame(self, name_or_index=None):
        if not self.frames:
            raise PxaError("document has no frames")
        if name_or_index is None:
            return self.frames[0]
        if isinstance(name_or_index, int):
            return self.frames[name_or_index]
        for f in self.frames:
            if f.name == name_or_index:
                return f
        try:
            return self.frames[int(name_or_index)]
        except (ValueError, IndexError):
            raise PxaError("no such frame: %r" % (name_or_index,))

    def copy(self):
        return Doc(dict(self.meta),
                   [Swatch(s.key, s.rgba, s.name) for s in self.swatches],
                   [f.copy() for f in self.frames])

    # -- validation -------------------------------------------------------
    def validate(self):
        problems = []
        if not self.frames:
            problems.append("no @frame block found")
            return problems
        keys = set(s.key for s in self.swatches)
        if len(keys) != len(self.swatches):
            problems.append("duplicate palette keys")
        w, h = self.frames[0].width, self.frames[0].height
        for f in self.frames:
            if f.width != w or f.height != h:
                problems.append("frame %r is %dx%d, expected %dx%d"
                                % (f.name, f.width, f.height, w, h))
            for y, row in enumerate(f.rows):
                if len(row) != w:
                    problems.append("frame %r row %d has %d chars, expected %d"
                                    % (f.name, y, len(row), w))
                for x, ch in enumerate(row):
                    if ch not in keys:
                        problems.append("frame %r (%d,%d): character %r is not in the palette"
                                        % (f.name, x, y, ch))
        declared = self.meta.get("size")
        if declared:
            m = re.match(r"^\s*(\d+)\s*[xX*]\s*(\d+)\s*$", declared)
            if m and (int(m.group(1)) != w or int(m.group(2)) != h):
                problems.append("meta size %s does not match grid %dx%d" % (declared, w, h))
        return problems


# --------------------------------------------------------------------------
# parse / serialise
# --------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^@(meta|palette|frame|grid)\b\s*(.*)$")


def parse(text):
    doc = Doc()
    section = None
    frame_name = None
    frame_rows = []

    def flush_frame():
        if frame_name is not None:
            doc.frames.append(Frame(frame_name, frame_rows))

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        m = _SECTION_RE.match(stripped)
        if m:
            if section == "frame":
                flush_frame()
                frame_rows = []
            kind, arg = m.group(1), m.group(2).strip()
            if kind in ("frame", "grid"):
                section = "frame"
                frame_name = arg or ("f%d" % len(doc.frames))
                frame_rows = []
            else:
                section = kind
            continue
        if section is None:
            continue
        if section == "frame":
            # inside a grid, only a leading '#' at column 0 with a space is a comment
            if stripped.startswith("# "):
                continue
            if not stripped:
                continue
            frame_rows.append(stripped)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if section == "meta":
            if ":" not in stripped:
                raise PxaError("bad @meta line (expected 'key: value'): %r" % stripped)
            k, v = stripped.split(":", 1)
            doc.meta[k.strip()] = v.strip()
        elif section == "palette":
            parts = stripped.split(None, 2)
            if len(parts) < 2:
                raise PxaError("bad @palette line (expected 'KEY #hex [name]'): %r" % stripped)
            key, hexval = parts[0], parts[1]
            if len(key) != 1:
                raise PxaError("palette key must be exactly one character: %r" % key)
            name = parts[2].strip() if len(parts) > 2 else ""
            doc.swatches.append(Swatch(key, parse_hex(hexval), name))

    if section == "frame":
        flush_frame()

    if not doc.swatches:
        doc.swatches.append(Swatch(TRANSPARENT_KEY, (0, 0, 0, 0), "transparent"))
    return doc


def serialize(doc):
    out = []
    out.append("@meta")
    meta = dict(doc.meta)
    if doc.frames:
        meta["size"] = "%dx%d" % (doc.width, doc.height)
    order = ["name", "size", "stage", "palette", "light", "note"]
    for k in order:
        if k in meta:
            out.append("%s: %s" % (k, meta.pop(k)))
    for k in sorted(meta):
        out.append("%s: %s" % (k, meta[k]))
    out.append("")
    out.append("@palette")
    namew = max([len(s.name) for s in doc.swatches] + [0])
    for s in doc.swatches:
        line = "%s %-9s" % (s.key, format_hex(s.rgba, force_alpha=s.is_transparent))
        if s.name:
            line += " %s" % s.name
        out.append(line.rstrip())
    for f in doc.frames:
        out.append("")
        out.append("@frame %s" % f.name)
        out.extend(f.rows)
    out.append("")
    return "\n".join(out)


def load(path):
    with open(path, "r") as fh:
        doc = parse(fh.read())
    doc.meta.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    return doc


def save(doc, path):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w") as fh:
        fh.write(serialize(doc))
    return path


def assign_keys_by_value(doc):
    """Re-key the palette so heavy characters mean dark colours and light ones
    mean light colours. Keeps '.' for transparency and rewrites every frame."""
    opaque = sorted(doc.opaque_swatches(), key=lambda sw: luminance(sw.rgba))
    if not opaque:
        return doc
    used = set([TRANSPARENT_KEY])
    mapping = {}
    pool = [c for c in DENSITY_KEYS] + [c for c in KEY_ALPHABET if c not in DENSITY_KEYS]
    n = len(opaque)
    chosen = []
    if n <= len(DENSITY_KEYS):
        # spread the picks across the density ramp so the contrast stays visible
        step = (len(DENSITY_KEYS) - 1) / float(max(1, n - 1)) if n > 1 else 0
        for i in range(n):
            idx = int(round(i * step))
            while DENSITY_KEYS[idx] in used and idx < len(DENSITY_KEYS) - 1:
                idx += 1
            ch = DENSITY_KEYS[idx]
            if ch in used:
                ch = next(c for c in pool if c not in used)
            used.add(ch)
            chosen.append(ch)
    else:
        for i in range(n):
            ch = next(c for c in pool if c not in used)
            used.add(ch)
            chosen.append(ch)
    for sw, ch in zip(opaque, chosen):
        mapping[sw.key] = ch
    for f in doc.frames:
        f.rows = ["".join(mapping.get(c, c) for c in row) for row in f.rows]
    for sw in opaque:
        sw.key = mapping[sw.key]
    doc.swatches = [s for s in doc.swatches if s.is_transparent] + opaque
    return doc


def blank(width, height, name="sprite", palette=None):
    doc = Doc(meta={"name": name, "size": "%dx%d" % (width, height)})
    doc.swatches.append(Swatch(TRANSPARENT_KEY, (0, 0, 0, 0), "transparent"))
    for rgba, label in (palette or []):
        doc.add_swatch(rgba, label)
    doc.frames.append(Frame(DEFAULT_FRAME, [TRANSPARENT_KEY * width for _ in range(height)]))
    return doc


# --------------------------------------------------------------------------
# raster conversion
# --------------------------------------------------------------------------

def frame_to_pixels(doc, frame):
    """-> list of rows, each a list of (r,g,b,a) tuples."""
    lut = doc.palette
    fallback = (0, 0, 0, 0)
    return [[lut.get(ch, fallback) for ch in row] for row in frame.rows]


def pixels_to_frame(doc, pixels, name=DEFAULT_FRAME, add_missing=True):
    """Build a Frame from an rgba grid, allocating palette keys as needed."""
    by_color = dict((s.rgba, s.key) for s in doc.swatches)
    rows = []
    for row in pixels:
        chars = []
        for px in row:
            px = tuple(px)
            if px[3] == 0:
                px = (0, 0, 0, 0)
            key = by_color.get(px)
            if key is None:
                if add_missing:
                    sw = doc.add_swatch(px)
                    by_color[px] = sw.key
                    key = sw.key
                else:
                    opts = [s.rgba for s in doc.swatches]
                    key = doc.swatches[nearest_color(px, opts)].key
            chars.append(key)
        rows.append("".join(chars))
    return Frame(name, rows)


# --------------------------------------------------------------------------
# PNG output (stdlib only, always 8-bit RGBA)
# --------------------------------------------------------------------------

def write_png(path, pixels, upscale=1):
    """pixels: list of rows of (r,g,b,a). Nearest-neighbour upscale, no smoothing."""
    h = len(pixels)
    w = len(pixels[0]) if h else 0
    if w == 0 or h == 0:
        raise PxaError("cannot write an empty image")
    s = max(1, int(upscale))
    raw = bytearray()
    for row in pixels:
        line = bytearray()
        for px in row:
            r, g, b, a = px
            line += bytes((r & 255, g & 255, b & 255, a & 255)) * s
        for _ in range(s):
            raw.append(0)          # filter type 0 (None) for every scanline
            raw += line
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w * s, h * s, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def read_png(path):
    """Minimal PNG reader for the formats this toolchain itself emits
    (8-bit RGB/RGBA/grey/palette, no interlacing). Raises for anything else --
    use imaging.load_image() for arbitrary user files."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PxaError("not a PNG file: %s" % path)
    pos, idat, plte, trns, hdr = 8, bytearray(), None, None, None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IEND":
            break
    if hdr is None:
        raise PxaError("corrupt PNG (no IHDR): %s" % path)
    w, h, depth, ctype, comp, filt, interlace = hdr
    if depth != 8 or interlace != 0:
        raise PxaError("unsupported PNG (depth=%d interlace=%d): %s" % (depth, interlace, path))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise PxaError("unsupported PNG colour type %d: %s" % (ctype, path))
    raw = zlib.decompress(bytes(idat))
    stride = w * channels
    out, prev = [], bytearray(stride)
    p = 0
    for _ in range(h):
        ftype = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            x = line[i]
            if ftype == 1:
                x += a
            elif ftype == 2:
                x += b
            elif ftype == 3:
                x += (a + b) >> 1
            elif ftype == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                x += a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = x & 255
        prev = line
        row = []
        for x in range(w):
            o = x * channels
            if ctype == 6:
                row.append((line[o], line[o + 1], line[o + 2], line[o + 3]))
            elif ctype == 2:
                row.append((line[o], line[o + 1], line[o + 2], 255))
            elif ctype == 0:
                v = line[o]; row.append((v, v, v, 255))
            elif ctype == 4:
                v = line[o]; row.append((v, v, v, line[o + 1]))
            else:
                i = line[o]
                r, g, b = plte[i * 3], plte[i * 3 + 1], plte[i * 3 + 2]
                a = trns[i] if (trns and i < len(trns)) else 255
                row.append((r, g, b, a))
        out.append(row)
    return out
