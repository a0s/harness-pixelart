"""3D "massing" renderer for buildings and structures.

An agent cannot compute an isometric slope by hand in a text grid -- left to
itself it draws a front elevation and calls it a house. This module lets it
write a small text scene (boxes, roofs, cylinders in world units) and get back
a flat-shaded `.pxa` sprite with every visible face already at the right
slope, tone and texture direction, plus a wireframe guide PNG. The agent then
paints detail on top of the render by hand.

Everything here works on the Python standard library alone.

World axes: X right, Y away from the viewer (into the screen), Z up.
Screen axes: x right, y down (standard raster convention).
"""

import os
import re
import math
import copy
import zlib

import pxa
import palettes
import render as rendermod
import font3x5 as f35


class SceneError(Exception):
    def __init__(self, message, line=0):
        self.message = message
        self.line = line
        text = "line %d: %s" % (line, message) if line else message
        super(SceneError, self).__init__(text)


# --------------------------------------------------------------------------
# vector maths (plain tuples, no numpy anywhere in this toolchain)
# --------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale3(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _length(a):
    return math.sqrt(_dot(a, a))


def _normalize(a):
    l = _length(a)
    if l < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / l, a[1] / l, a[2] / l)


def _avg(points):
    n = len(points)
    return (sum(p[0] for p in points) / n,
            sum(p[1] for p in points) / n,
            sum(p[2] for p in points) / n)


def _dedupe_cyclic(points, eps=1e-7):
    """Drop consecutive (cyclically) duplicate points -- a ridge_len of 0
    collapses a trapezoid slope into a triangle this way."""
    out = []
    for p in points:
        if out and _length(_sub(p, out[-1])) < eps:
            continue
        out.append(p)
    if len(out) > 1 and _length(_sub(out[0], out[-1])) < eps:
        out.pop()
    return out


# --------------------------------------------------------------------------
# light directions (point FROM the light) and material ramps
# --------------------------------------------------------------------------

LIGHT_DIRS = {
    "top-left": (-0.55, -0.45, 0.70),
    "top-right": (0.55, -0.45, 0.70),
    "top": (0.0, -0.3, 0.95),
    "left": (-0.8, -0.4, 0.45),
    "right": (0.8, -0.4, 0.45),
    "front": (0.0, -0.9, 0.45),
}

TONE_IDX = {"dark": 0, "shadow": 1, "base": 2, "light": 3}

# texture symbol -> ramp-index offset from the face's own tone
TEX_OFFSETS = {".": 0, "-": -1, "+": 1, "=": -2, "*": 2}


def _extrapolate_hsl(h0, s0, l0, h1, s1, l1):
    """One more step past (h1,s1,l1) continuing the same delta from
    (h0,s0,l0) -- used to derive the extreme ramp steps from explicit
    shadow/light colours."""
    dh = ((h1 - h0 + 180.0) % 360.0) - 180.0
    h2 = (h1 + dh) % 360.0
    s2 = max(0.0, min(100.0, s1 + (s1 - s0)))
    l2 = max(0.0, min(100.0, l1 + (l1 - l0)))
    return h2, s2, l2


def _hue_toward(h, target, amount):
    diff = ((target - h + 180.0) % 360.0) - 180.0
    step = max(-abs(diff), min(abs(diff), diff))
    return (h + (step / abs(diff) if diff else 0.0) * min(amount, abs(diff))) % 360.0


def _auto_ramp(base):
    """Build a 5-step ramp around `base` alone, spaced by fixed L* offsets
    from the base itself (not by squeezing a fixed 18-92 range) so the steps
    stay clearly separated even when the base is already light or dark:
    shadow ~22 L* below base, light ~18 L* above; the extremes go one more
    step further, with a cool shift into shadow and a warm shift into
    light."""
    h0, s0, l0 = pxa.rgb_to_hsl(base)
    l_shadow = max(0.0, min(100.0, l0 - 22.0))
    l_light = max(0.0, min(100.0, l0 + 18.0))
    l_dark = max(0.0, min(100.0, l_shadow - 20.0))
    l_bright = max(0.0, min(100.0, l_light + 16.0))
    h_dark = _hue_toward(h0, 250.0, 24.0)
    h_shadow = _hue_toward(h0, 250.0, 14.0)
    h_light = _hue_toward(h0, 45.0, 10.0)
    h_bright = _hue_toward(h0, 45.0, 18.0)
    dark = pxa.hsl_to_rgb(h_dark, min(100.0, s0 + 14.0), l_dark)
    shadow = pxa.hsl_to_rgb(h_shadow, min(100.0, s0 + 8.0), l_shadow)
    light = pxa.hsl_to_rgb(h_light, max(0.0, s0 - 6.0), l_light)
    bright = pxa.hsl_to_rgb(h_bright, max(0.0, s0 - 10.0), l_bright)
    return [dark, shadow, base, light, bright]


def _build_ramp(mat):
    """-> [darkest, shadow, base, light, lightest] rgba, 5 steps."""
    base = mat.base
    if mat.shadow is None or mat.light is None:
        return _auto_ramp(base)
    hb, sb, lb = pxa.rgb_to_hsl(base)
    hs, ss, ls = pxa.rgb_to_hsl(mat.shadow)
    hl, sl, ll = pxa.rgb_to_hsl(mat.light)
    h0, s0, l0 = _extrapolate_hsl(hb, sb, lb, hs, ss, ls)
    h4, s4, l4 = _extrapolate_hsl(hb, sb, lb, hl, sl, ll)
    dark = pxa.hsl_to_rgb(h0, s0, l0)
    bright = pxa.hsl_to_rgb(h4, s4, l4)
    return [dark, mat.shadow, base, mat.light, bright]


def _ramp_names(name):
    return ["%s-dark" % name, "%s-shadow" % name, name, "%s-light" % name, "%s-bright" % name]


def _tone_for(normal, light):
    """4 buckets: a face pointed hard away from the light (the underside of
    an eave, the far slope of a roof) reads darker than a merely unlit wall
    -- it gets the darkest ramp step, not the shadow step."""
    d = _dot(normal, light)
    if d > 0.55:
        return "light"
    if d > 0.05:
        return "base"
    if d > -0.35:
        return "shadow"
    return "dark"


# --------------------------------------------------------------------------
# scene document model
# --------------------------------------------------------------------------

class Texture(object):
    __slots__ = ("rows", "w", "h")

    def __init__(self, rows, w, h):
        self.rows = rows
        self.w = w
        self.h = h


class Material(object):
    def __init__(self, name, base, shadow, light, texture, space, jitter, line):
        self.name = name
        self.base = base
        self.shadow = shadow
        self.light = light
        self.texture = texture
        self.space = space
        self.jitter = jitter
        self.line = line


class SceneObject(object):
    def __init__(self, type_, name, line):
        self.type = type_
        self.name = name
        self.line = line
        self.at = None
        self.size = None
        self.mat = None
        self.shade = None
        self.overrides = {}
        self.face_names = set()
        self.ridge = None
        self.ridge_len = None
        self.high = None
        self.r = None
        self.h = None
        self.sides = None
        self.thickness = 0.0


class Scene(object):
    def __init__(self):
        self.name = None
        self.view = "topdown"
        self.k = 0.5
        self.pitch = None
        self.yaw = 0.0
        self.axes = None
        self.unit = 8.0
        self.light = "top-left"
        self.canvas = None
        self.origin = None
        self.outline = "ink"
        self.shadow = 2
        self.tones = 3
        self.materials = {}
        self.objects = []
        self.objects_by_name = {}
        self.base_dir = "."
        self.path = None
        self.ink_rgba = None
        self._ramp_cache = {}


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^@(scene|materials|objects)\b\s*(.*)$")


def _pair(text, lineno):
    parts = text.split(",")
    if len(parts) != 2:
        raise SceneError("expected 'x,y': %r" % text, lineno)
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        raise SceneError("bad number in %r" % text, lineno)


def _floats(text, n, lineno):
    parts = text.split(",")
    if len(parts) != n:
        raise SceneError("expected %d comma-separated numbers, got %r" % (n, text), lineno)
    try:
        return tuple(float(p) for p in parts)
    except ValueError:
        raise SceneError("bad number in %r" % text, lineno)


def _float1(text, lineno):
    try:
        return float(text)
    except ValueError:
        raise SceneError("bad number: %r" % text, lineno)


def _load_texture(path):
    with open(path, "r") as fh:
        raw_lines = fh.read().splitlines()
    rows = [l for l in raw_lines if l.strip() and not l.lstrip().startswith(";")]
    if not rows:
        raise SceneError("empty texture file: %s" % path, 0)
    w = len(rows[0])
    for r in rows:
        if len(r) != w:
            raise SceneError("texture rows must all be the same length: %s" % path, 0)
    return Texture(rows, w, len(rows))


def _set_scene_field(scene, key, val, lineno):
    if key == "name":
        scene.name = val
    elif key == "view":
        scene.view = val
    elif key == "k":
        scene.k = _float1(val, lineno)
    elif key == "pitch":
        scene.pitch = _float1(val, lineno)
    elif key == "yaw":
        scene.yaw = _float1(val, lineno)
    elif key == "axes":
        parts = val.split()
        if len(parts) != 3:
            raise SceneError("axes: needs three 'x,y' vectors (X Y Z)", lineno)
        scene.axes = tuple(_pair(p, lineno) for p in parts)
    elif key == "unit":
        scene.unit = _float1(val, lineno)
    elif key == "light":
        if val not in LIGHT_DIRS:
            raise SceneError("unknown light: %r (pick one of %s)"
                             % (val, ", ".join(sorted(LIGHT_DIRS))), lineno)
        scene.light = val
    elif key == "canvas":
        t = val.lower().replace("*", "x")
        if "x" not in t:
            raise SceneError("bad canvas: %r (expected WxH)" % val, lineno)
        w, h = t.split("x", 1)
        try:
            scene.canvas = (int(w), int(h))
        except ValueError:
            raise SceneError("bad canvas: %r" % val, lineno)
    elif key == "origin":
        x, y = _pair(val, lineno)
        scene.origin = (x, y)
    elif key == "outline":
        if val not in ("ink", "none"):
            raise SceneError("bad outline: %r (ink|none)" % val, lineno)
        scene.outline = val
    elif key == "shadow":
        scene.shadow = int(_float1(val, lineno))
    elif key == "tones":
        scene.tones = int(_float1(val, lineno))
    else:
        raise SceneError("unknown @scene key: %r" % key, lineno)


def _parse_material_line(scene, line, lineno):
    toks = line.split()
    if len(toks) < 2:
        raise SceneError("bad @materials line (expected 'name base ...')", lineno)
    name, basetok = toks[0], toks[1]
    try:
        base = pxa.parse_hex(basetok)
    except pxa.PxaError as exc:
        raise SceneError("bad material colour: %s" % exc, lineno)
    idx = 2
    shadow = light = None
    if idx < len(toks) and toks[idx].startswith("#"):
        try:
            shadow = pxa.parse_hex(toks[idx])
        except pxa.PxaError as exc:
            raise SceneError("bad shadow colour: %s" % exc, lineno)
        idx += 1
    if idx < len(toks) and toks[idx].startswith("#"):
        try:
            light = pxa.parse_hex(toks[idx])
        except pxa.PxaError as exc:
            raise SceneError("bad light colour: %s" % exc, lineno)
        idx += 1
    texture_name, space, jitter = None, "screen", 0.0
    for tok in toks[idx:]:
        if "=" not in tok:
            raise SceneError("bad material token %r" % tok, lineno)
        k, v = tok.split("=", 1)
        if k == "texture":
            texture_name = v
        elif k == "space":
            if v not in ("screen", "world"):
                raise SceneError("bad space=%r (screen|world)" % v, lineno)
            space = v
        elif k == "jitter":
            jitter = _float1(v, lineno)
            if not (0.0 <= jitter <= 3.0):
                raise SceneError("jitter must be 0..3: %r" % v, lineno)
        else:
            raise SceneError("unknown material key: %r" % k, lineno)
    if name in scene.materials:
        raise SceneError("duplicate material: %r" % name, lineno)
    texture = None
    if texture_name:
        tpath = os.path.join(scene.base_dir, texture_name)
        try:
            texture = _load_texture(tpath)
        except (IOError, OSError) as exc:
            raise SceneError("cannot read texture %r: %s" % (texture_name, exc), lineno)
    scene.materials[name] = Material(name, base, shadow, light, texture, space, jitter, lineno)


def _parse_object_line(scene, line, lineno):
    toks = line.split()
    if len(toks) < 2:
        raise SceneError("bad @objects line (expected 'type name ...')", lineno)
    type_, name = toks[0], toks[1]
    if type_ not in BUILDERS:
        raise SceneError("unknown object type: %r" % type_, lineno)
    if name in scene.objects_by_name:
        raise SceneError("duplicate object name: %r" % name, lineno)
    kv = {}
    for tok in toks[2:]:
        if "=" not in tok:
            raise SceneError("bad object token %r (expected key=value)" % tok, lineno)
        k, v = tok.split("=", 1)
        kv[k] = v

    obj = SceneObject(type_, name, lineno)
    if "at" not in kv:
        raise SceneError("object %r missing at=" % name, lineno)
    obj.at = _floats(kv.pop("at"), 3, lineno)
    obj.mat = kv.pop("mat", None)
    obj.shade = kv.pop("shade", None)
    if obj.shade and obj.shade not in ("dark", "shadow", "base", "light"):
        raise SceneError("bad shade=%r (dark|shadow|base|light)" % obj.shade, lineno)

    if type_ == "ground":
        if "size" not in kv:
            raise SceneError("ground %r missing size=" % name, lineno)
        obj.size = _floats(kv.pop("size"), 2, lineno)
        face_names = {"top"}

    elif type_ == "box":
        if "size" not in kv:
            raise SceneError("box %r missing size=" % name, lineno)
        obj.size = _floats(kv.pop("size"), 3, lineno)
        face_names = {"top", "bottom", "front", "back", "left", "right"}

    elif type_ in ("gable", "hip"):
        if "size" not in kv:
            raise SceneError("%s %r missing size=" % (type_, name), lineno)
        obj.size = _floats(kv.pop("size"), 3, lineno)
        obj.ridge = kv.pop("ridge", "y")
        if obj.ridge not in ("x", "y"):
            raise SceneError("bad ridge=%r (x|y)" % obj.ridge, lineno)
        obj.thickness = _float1(kv.pop("thickness", "0"), lineno)
        if type_ == "hip":
            sx, sy, _sz = obj.size
            default_rl = 0.5 * (sx if obj.ridge == "x" else sy)
            obj.ridge_len = _float1(kv.pop("ridge_len", str(default_rl)), lineno)
        else:
            obj.ridge_len = None
        if obj.ridge == "x":
            face_names = {"slope-front", "slope-back", "gable-left", "gable-right"}
        else:
            face_names = {"slope-l", "slope-r", "gable-front", "gable-back"}

    elif type_ == "pyramid":
        if "size" not in kv:
            raise SceneError("pyramid %r missing size=" % name, lineno)
        obj.size = _floats(kv.pop("size"), 3, lineno)
        obj.ridge = kv.pop("ridge", "x")
        obj.ridge_len = 0.0
        obj.thickness = _float1(kv.pop("thickness", "0"), lineno)
        face_names = {"slope-front", "slope-back", "gable-left", "gable-right",
                     "slope-l", "slope-r", "gable-front", "gable-back"}

    elif type_ == "shed":
        if "size" not in kv:
            raise SceneError("shed %r missing size=" % name, lineno)
        obj.size = _floats(kv.pop("size"), 3, lineno)
        obj.high = kv.pop("high", "+y")
        if obj.high not in ("+x", "-x", "+y", "-y"):
            raise SceneError("bad high=%r (+x|-x|+y|-y)" % obj.high, lineno)
        obj.thickness = _float1(kv.pop("thickness", "0"), lineno)
        face_names = {"slope"}

    elif type_ in ("cyl", "cone"):
        if "r" not in kv or "h" not in kv:
            raise SceneError("%s %r missing r=/h=" % (type_, name), lineno)
        obj.r = _float1(kv.pop("r"), lineno)
        obj.h = _float1(kv.pop("h"), lineno)
        obj.sides = int(_float1(kv.pop("sides", "12"), lineno))
        if obj.sides < 3:
            raise SceneError("sides must be >= 3", lineno)
        sidenames = set("side%d" % i for i in range(obj.sides))
        if type_ == "cyl":
            face_names = {"top", "bottom"} | sidenames
        else:
            face_names = {"bottom"} | sidenames
    else:
        raise SceneError("unknown object type: %r" % type_, lineno)

    obj.face_names = face_names
    for k, v in kv.items():
        if k not in face_names:
            raise SceneError("unknown key %r for %s %r" % (k, type_, name), lineno)
        obj.overrides[k] = v

    scene.objects.append(obj)
    scene.objects_by_name[name] = obj


def _finalize_scene(scene):
    if not scene.name:
        raise SceneError("@scene is missing name:", 0)
    if scene.view == "camera" and scene.pitch is None:
        raise SceneError("view: camera requires pitch: (0 = side view, 90 = straight down)", 0)
    if scene.view not in ("topdown", "iso", "oblique", "custom", "camera"):
        raise SceneError("unknown view: %r" % scene.view, 0)
    if scene.view == "custom" and scene.axes is None:
        raise SceneError("view: custom requires axes:", 0)
    scene.ink_rgba = (scene.materials["ink"].base if "ink" in scene.materials
                      else pxa.parse_hex("#1a1c2c"))
    for obj in scene.objects:
        for fn in sorted(obj.face_names):
            matname = obj.overrides.get(fn, obj.mat)
            if not matname:
                raise SceneError("object %r face %r has no material (mat= or %s=)"
                                 % (obj.name, fn, fn), obj.line)
            if matname not in scene.materials:
                raise SceneError("object %r references unknown material %r"
                                 % (obj.name, matname), obj.line)


def parse(text, base_dir="."):
    scene = Scene()
    scene.base_dir = base_dir
    section = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        m = _SECTION_RE.match(stripped)
        if m:
            section = m.group(1)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if section is None:
            continue
        if section == "scene":
            nc = re.sub(r"\s+#.*$", "", stripped)
            if ":" not in nc:
                raise SceneError("bad @scene line (expected 'key: value'): %r" % stripped, lineno)
            k, v = nc.split(":", 1)
            _set_scene_field(scene, k.strip(), v.strip(), lineno)
        elif section == "materials":
            _parse_material_line(scene, stripped, lineno)
        elif section == "objects":
            _parse_object_line(scene, stripped, lineno)
    _finalize_scene(scene)
    return scene


def load(path):
    with open(path, "r") as fh:
        text = fh.read()
    scene = parse(text, base_dir=os.path.dirname(os.path.abspath(path)))
    scene.path = path
    return scene


# --------------------------------------------------------------------------
# starter scene (for `px scene new`)
# --------------------------------------------------------------------------

def starter_text(name, view="topdown", unit=6, pitch=26.57, yaw=0.0):
    view_lines = "view: %s\n" % view
    if view == "camera":
        view_lines += "pitch: %s               # 0 = side view, 90 = straight down\n" % pitch
        view_lines += "yaw: %s                  # 0 = fronted-on, 45 = corner-on (isometric)\n" % yaw
    else:
        view_lines += "k: 0.5                 # topdown only: vertical foreshortening of the depth axis\n"
        view_lines += ("# view: camera          # tilt/turn stated as a camera: pitch: / yaw: -- "
                       "pitch=26.57 yaw=0 == topdown k=0.5, pitch=26.57 yaw=45 == iso\n")
    return ("""@scene
name: %(name)s
""" + view_lines + """unit: %(unit)s
light: top-left
outline: ink
shadow: 2

@materials
# name   base       [shadow    light]     [texture=FILE] [space=screen|world]
grass    #8e8b2e
wall     #d7c996
roof     #4d94a7    #2f6b86    #7fc0d0

@objects
# type   name    at=x,y,z       size=sx,sy,sz     mat=NAME   extras
ground   yard    at=-2,-2,0     size=20,16        mat=grass
box      body    at=0,0,0       size=10,8,6       mat=wall
gable    roof    at=-1,-1,6     size=12,10,4      mat=roof   ridge=x
""") % {"name": name, "unit": unit}


# --------------------------------------------------------------------------
# geometry: build the faces of one object
# --------------------------------------------------------------------------

_UP = (0.0, 0.0, 1.0)


def _poly_normal(corners, interior):
    """Robust outward normal of a planar convex polygon: cross the first
    non-degenerate pair of edges, then flip it to point away from a known
    interior reference point of the solid."""
    n = None
    for i in range(1, len(corners) - 1):
        e1 = _sub(corners[i], corners[0])
        e2 = _sub(corners[i + 1], corners[0])
        c = _cross(e1, e2)
        if _dot(c, c) > 1e-9:
            n = c
            break
    if n is None:
        n = (0.0, 0.0, 1.0)
    centroid = _avg(corners)
    if _dot(n, _sub(centroid, interior)) < 0:
        n = _scale3(n, -1)
    return _normalize(n)


def _uv_basis(normal, cap):
    """e1 (along), e2 (down) for texture UV -- see references/format.md
    (`structures.md`) for the exact tangent convention this reproduces."""
    if cap:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    e1 = _cross(_UP, normal)
    if _dot(e1, e1) < 1e-9:
        e1 = (1.0, 0.0, 0.0)
    e1 = _normalize(e1)
    e2 = _normalize(_cross(normal, e1))
    if e2[2] > 1e-9:
        e2 = _scale3(e2, -1)
    return e1, e2


def _make_face(name, corners, cap, interior):
    corners = _dedupe_cyclic(corners)
    if len(corners) < 3:
        return None
    normal = _poly_normal(corners, interior)
    e1, e2 = _uv_basis(normal, cap)
    return {"face": name, "corners": corners, "normal": normal,
           "e1": e1, "e2": e2, "origin": corners[0], "cap": cap}


def _thicken_face(face, thickness):
    """Extrude a slope plane into a slab: the original polygon stays the top
    surface, a copy offset inward along -normal becomes the underside (its
    own face, usually shadowed), and a thin quad per boundary edge becomes
    the visible eave/rake edge -- named `edge-0`, `edge-1`, ... This is what
    makes a roof read as built rather than folded from paper."""
    if not face:
        return []
    if thickness is None or thickness <= 0:
        return [face]
    corners = face["corners"]
    normal = face["normal"]
    offset = _scale3(normal, -thickness)
    under_raw = [_add(c, offset) for c in corners]
    under_corners = list(reversed(under_raw))
    under_normal = _scale3(normal, -1.0)
    under_e1, under_e2 = _uv_basis(under_normal, False)
    underside = {"face": "underside", "corners": under_corners, "normal": under_normal,
                "e1": under_e1, "e2": under_e2, "origin": under_corners[0], "cap": False}
    out = [face, underside]
    n = len(corners)
    slab_centroid = _avg(corners + under_raw)
    for i in range(n):
        j = (i + 1) % n
        quad = [corners[i], corners[j], under_raw[j], under_raw[i]]
        edge = _make_face("edge-%d" % i, quad, False, slab_centroid)
        if edge:
            out.append(edge)
    return out


def _ground_faces(obj):
    ax, ay, az = obj.at
    sx, sy = obj.size
    corners = [(ax, ay, az), (ax + sx, ay, az), (ax + sx, ay + sy, az), (ax, ay + sy, az)]
    interior = (ax + sx / 2.0, ay + sy / 2.0, az - 1.0)
    return [_make_face("top", corners, True, interior)]


def _box_faces(obj):
    ax, ay, az = obj.at
    sx, sy, sz = obj.size
    ax2, ay2, az2 = ax + sx, ay + sy, az + sz
    center = (ax + sx / 2.0, ay + sy / 2.0, az + sz / 2.0)
    specs = [
        ("top", [(ax, ay, az2), (ax2, ay, az2), (ax2, ay2, az2), (ax, ay2, az2)], True),
        ("bottom", [(ax, ay, az), (ax, ay2, az), (ax2, ay2, az), (ax2, ay, az)], True),
        ("front", [(ax, ay, az), (ax2, ay, az), (ax2, ay, az2), (ax, ay, az2)], False),
        ("back", [(ax, ay2, az), (ax, ay2, az2), (ax2, ay2, az2), (ax2, ay2, az)], False),
        ("left", [(ax, ay, az), (ax, ay, az2), (ax, ay2, az2), (ax, ay2, az)], False),
        ("right", [(ax2, ay, az), (ax2, ay2, az), (ax2, ay2, az2), (ax2, ay, az2)], False),
    ]
    return [_make_face(n, c, cap, center) for n, c, cap in specs]


def _gable_faces(obj):
    ax, ay, az = obj.at
    sx, sy, h = obj.size
    center = (ax + sx / 2.0, ay + sy / 2.0, az + h / 2.0)
    rz = az + h
    faces = []
    if obj.ridge == "x":
        ry = ay + sy / 2.0
        faces.append(_make_face("slope-front",
                                [(ax, ay, az), (ax + sx, ay, az), (ax + sx, ry, rz), (ax, ry, rz)],
                                False, center))
        faces.append(_make_face("slope-back",
                                [(ax, ay + sy, az), (ax, ry, rz), (ax + sx, ry, rz), (ax + sx, ay + sy, az)],
                                False, center))
        faces.append(_make_face("gable-left",
                                [(ax, ay, az), (ax, ay + sy, az), (ax, ry, rz)], False, center))
        faces.append(_make_face("gable-right",
                                [(ax + sx, ay, az), (ax + sx, ry, rz), (ax + sx, ay + sy, az)], False, center))
    else:
        rx = ax + sx / 2.0
        faces.append(_make_face("slope-l",
                                [(ax, ay, az), (rx, ay, rz), (rx, ay + sy, rz), (ax, ay + sy, az)],
                                False, center))
        faces.append(_make_face("slope-r",
                                [(ax + sx, ay, az), (ax + sx, ay + sy, az), (rx, ay + sy, rz), (rx, ay, rz)],
                                False, center))
        faces.append(_make_face("gable-front",
                                [(ax, ay, az), (rx, ay, rz), (ax + sx, ay, az)], False, center))
        faces.append(_make_face("gable-back",
                                [(ax, ay + sy, az), (ax + sx, ay + sy, az), (rx, ay + sy, rz)], False, center))
    out = []
    for f in faces:
        if not f:
            continue
        if f["face"].startswith("slope-"):
            out.extend(_thicken_face(f, obj.thickness))
        else:
            out.append(f)
    return out


def _hip_faces(obj, force_pyramid=False):
    ax, ay, az = obj.at
    sx, sy, h = obj.size
    ridge = obj.ridge or "y"
    rl = 0.0 if force_pyramid else max(0.0, obj.ridge_len or 0.0)
    center = (ax + sx / 2.0, ay + sy / 2.0, az + h / 2.0)
    cx, cy = ax + sx / 2.0, ay + sy / 2.0
    rz = az + h
    faces = []
    if ridge == "x":
        rl = min(rl, sx)
        rx0, rx1 = cx - rl / 2.0, cx + rl / 2.0
        RL, RR = (rx0, cy, rz), (rx1, cy, rz)
        faces.append(_make_face("slope-front", [(ax, ay, az), (ax + sx, ay, az), RR, RL], False, center))
        faces.append(_make_face("slope-back", [(ax, ay + sy, az), RL, RR, (ax + sx, ay + sy, az)], False, center))
        faces.append(_make_face("gable-left", [(ax, ay, az), (ax, ay + sy, az), RL], False, center))
        faces.append(_make_face("gable-right", [(ax + sx, ay, az), RR, (ax + sx, ay + sy, az)], False, center))
    else:
        rl = min(rl, sy)
        ry0, ry1 = cy - rl / 2.0, cy + rl / 2.0
        RL, RR = (cx, ry0, rz), (cx, ry1, rz)
        faces.append(_make_face("slope-l", [(ax, ay, az), RL, RR, (ax, ay + sy, az)], False, center))
        faces.append(_make_face("slope-r", [(ax + sx, ay, az), (ax + sx, ay + sy, az), RR, RL], False, center))
        faces.append(_make_face("gable-front", [(ax, ay, az), RL, (ax + sx, ay, az)], False, center))
        faces.append(_make_face("gable-back", [(ax, ay + sy, az), (ax + sx, ay + sy, az), RR], False, center))
    out = []
    for f in faces:
        if f:
            out.extend(_thicken_face(f, obj.thickness))
    return out


def _pyramid_faces(obj):
    if obj.ridge is None:
        obj.ridge = "x"
    return _hip_faces(obj, force_pyramid=True)


def _shed_faces(obj):
    ax, ay, az = obj.at
    sx, sy, h = obj.size
    high = obj.high or "+y"
    if high == "+x":
        corners = [(ax, ay, az), (ax, ay + sy, az), (ax + sx, ay + sy, az + h), (ax + sx, ay, az + h)]
    elif high == "-x":
        corners = [(ax + sx, ay, az), (ax + sx, ay + sy, az), (ax, ay + sy, az + h), (ax, ay, az + h)]
    elif high == "+y":
        corners = [(ax, ay, az), (ax + sx, ay, az), (ax + sx, ay + sy, az + h), (ax, ay + sy, az + h)]
    else:
        corners = [(ax, ay + sy, az), (ax + sx, ay + sy, az), (ax + sx, ay, az + h), (ax, ay, az + h)]
    interior = (ax + sx / 2.0, ay + sy / 2.0, az - 1.0)
    f = _make_face("slope", corners, False, interior)
    return _thicken_face(f, obj.thickness)


def _cyl_faces(obj):
    cx, cy, z0 = obj.at
    r, h, n = obj.r, obj.h, obj.sides
    top_z = z0 + h
    center = (cx, cy, z0 + h / 2.0)
    top_pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), top_z)
              for i in range(n)]
    bot_pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z0)
              for i in range(n)]
    faces = [_make_face("top", top_pts, True, center),
            _make_face("bottom", list(reversed(bot_pts)), True, center)]
    for i in range(n):
        j = (i + 1) % n
        faces.append(_make_face("side%d" % i, [top_pts[i], top_pts[j], bot_pts[j], bot_pts[i]], False, center))
    return [f for f in faces if f]


def _cone_faces(obj):
    cx, cy, z0 = obj.at
    r, h, n = obj.r, obj.h, obj.sides
    apex = (cx, cy, z0 + h)
    center = (cx, cy, z0 + h / 3.0)
    bot_pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z0)
              for i in range(n)]
    faces = [_make_face("bottom", list(reversed(bot_pts)), True, center)]
    for i in range(n):
        j = (i + 1) % n
        faces.append(_make_face("side%d" % i, [bot_pts[i], bot_pts[j], apex], False, center))
    return [f for f in faces if f]


BUILDERS = {
    "ground": _ground_faces,
    "box": _box_faces,
    "gable": _gable_faces,
    "hip": _hip_faces,
    "pyramid": _pyramid_faces,
    "shed": _shed_faces,
    "cyl": _cyl_faces,
    "cone": _cone_faces,
}


# --------------------------------------------------------------------------
# projection
# --------------------------------------------------------------------------

def camera_axes(pitch_deg, yaw_deg=0.0):
    """Screen axes of a camera tilted `pitch` degrees down from the horizon and
    turned `yaw` degrees around the world Z axis.

    This is the projection stated the way a person thinks about a camera:

      pitch  0    side view, no top surfaces at all
      pitch 26.6  the classic RPG tilt (the ground foreshortens to 1:2)
      pitch 45    a high camera
      pitch 90    straight down, no walls
      yaw   0     the front wall faces the viewer -- the 3/4 top-down look
      yaw   45    the box stands corner-on -- the isometric look

    `pitch=26.57 yaw=0` is identical to `view: topdown k=0.5`, and
    `pitch=26.57 yaw=45` is identical to `view: iso` (pixel 2:1 isometric).
    True 30-degree isometry is `pitch=35.264 yaw=45`.

    World height stays 1:1 with screen pixels -- vertical edges never
    foreshorten -- and the horizontal scale is normalised so that `unit` is the
    screen length of the longer horizontal axis. That is the convention pixel
    art uses: it keeps wall heights and unit sizes integral.
    """
    if not (0.0 <= pitch_deg <= 90.0):
        raise SceneError("pitch must be between 0 and 90 degrees", 0)
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)
    t = math.tan(p) if pitch_deg < 89.999 else 1e6
    cy, sy = math.cos(y), math.sin(y)
    n = max(abs(cy), abs(sy)) or 1.0
    X = (cy / n, sy * t / n)
    Y = (sy / n, -cy * t / n)
    return (X, Y, (0.0, -1.0))


def _view_meta(scene, ox, oy):
    """-> the `view:` line written into a rendered `.pxa`'s `@meta`, carrying
    whichever parameters actually determine the projection so it can be
    reconstructed from the file alone -- `camera` records pitch/yaw (the real
    source of its foreshortening, not the derived `k`), `topdown` its `k`,
    `custom` its `axes`, and `iso`/`oblique` need nothing beyond their name."""
    tail = "unit=%s origin=%d,%d" % (scene.unit, ox, oy)
    if scene.view == "camera":
        return "camera pitch=%s yaw=%s %s" % (scene.pitch, scene.yaw, tail)
    if scene.view == "topdown":
        return "topdown k=%s %s" % (scene.k, tail)
    if scene.view == "custom":
        axes_str = " ".join("%s,%s" % (v[0], v[1]) for v in scene.axes)
        return "custom axes=%s %s" % (axes_str, tail)
    return "%s %s" % (scene.view, tail)


def _axes(scene):
    if scene.view == "camera":
        return camera_axes(scene.pitch, scene.yaw)
    if scene.view == "topdown":
        return ((1.0, 0.0), (0.0, -scene.k), (0.0, -1.0))
    if scene.view == "iso":
        return ((1.0, 0.5), (1.0, -0.5), (0.0, -1.0))
    if scene.view == "oblique":
        return ((1.0, 0.0), (0.5, -0.5), (0.0, -1.0))
    return scene.axes


def _length2(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1])


def _proj_unit(axes, p):
    X, Y, Z = axes
    return (p[0] * X[0] + p[1] * Y[0] + p[2] * Z[0],
            p[0] * X[1] + p[1] * Y[1] + p[2] * Z[1])


def _compute_cam(axes):
    X, Y, Z = axes
    sx_row = (X[0], Y[0], Z[0])
    sy_row = (X[1], Y[1], Z[1])
    cam = _cross(sx_row, sy_row)
    if cam[2] < 0:
        cam = _scale3(cam, -1)
    elif cam[2] == 0 and cam[1] > 0:
        cam = _scale3(cam, -1)
    return cam


# --------------------------------------------------------------------------
# rasterisation
# --------------------------------------------------------------------------

def _fill_triangle(v0, v1, v2, w, h, plot):
    """v0/v1/v2: (x, y, attr0, attr1, ...) in absolute screen px -- any number
    of trailing attributes, barycentrically interpolated. Pixel-centre
    sampling, top-left fill rule -- shared edges never double-cover or gap.
    `plot(px, py, attrs)` is called with attrs the interpolated tuple."""
    ax, ay = v0[0], v0[1]
    bx, by = v1[0], v1[1]
    cx, cy = v2[0], v2[1]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if area == 0:
        return
    if area < 0:
        v1, v2 = v2, v1
        bx, by = v1[0], v1[1]
        cx, cy = v2[0], v2[1]
        area = -area

    minx = max(0, int(math.floor(min(ax, bx, cx))))
    maxx = min(w, int(math.ceil(max(ax, bx, cx))))
    miny = max(0, int(math.floor(min(ay, by, cy))))
    maxy = min(h, int(math.ceil(max(ay, by, cy))))
    if minx >= maxx or miny >= maxy:
        return

    def edge(x1, y1, x2, y2, px, py):
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)

    def incl(x1, y1, x2, y2):
        return (y1 == y2 and x2 > x1) or (y2 > y1)

    inc0 = incl(bx, by, cx, cy)
    inc1 = incl(cx, cy, ax, ay)
    inc2 = incl(ax, ay, bx, by)
    nattr = len(v0) - 2

    for py in range(miny, maxy):
        py_c = py + 0.5
        for px in range(minx, maxx):
            px_c = px + 0.5
            w0 = edge(bx, by, cx, cy, px_c, py_c)
            w1 = edge(cx, cy, ax, ay, px_c, py_c)
            w2 = edge(ax, ay, bx, by, px_c, py_c)
            if ((w0 > 0 or (w0 == 0 and inc0)) and
                    (w1 > 0 or (w1 == 0 and inc1)) and
                    (w2 > 0 or (w2 == 0 and inc2))):
                l0, l1, l2 = w0 / area, w1 / area, w2 / area
                attrs = tuple(l0 * v0[2 + i] + l1 * v1[2 + i] + l2 * v2[2 + i] for i in range(nattr))
                plot(px, py, attrs)


def _fit_canvas(minx, maxx, miny, maxy, scene):
    bbox_w = maxx - minx
    bbox_h = maxy - miny
    if scene.canvas:
        cw, ch = scene.canvas
    else:
        # round off float noise (e.g. camera_axes(26.57, 0) is 0.5 to 4 decimal
        # places, not exactly) before ceiling, so an equivalent view never
        # rounds up an extra canvas pixel that an exact preset would not
        cw = int(math.ceil(round(bbox_w, 6))) + 2
        ch = int(math.ceil(round(bbox_h, 6))) + 2
    if scene.origin:
        ox, oy = scene.origin
    else:
        ox = (cw - bbox_w) / 2.0 - minx
        oy = (ch - 2) - maxy
    return cw, ch, int(round(ox)), int(round(oy))


# --------------------------------------------------------------------------
# the render pipeline
# --------------------------------------------------------------------------

class Result(object):
    def __init__(self, doc, face_id, closeness, faces, edges, origin, unit, warnings=None):
        self.doc = doc
        self.face_id = face_id
        self.closeness = closeness
        self.faces = faces
        self.edges = edges
        self.origin = origin
        self.unit = unit
        self.warnings = warnings or []


def _material_ramp(scene, name):
    cache = scene._ramp_cache
    if name not in cache:
        cache[name] = _build_ramp(scene.materials[name])
    return cache[name]


def _jitter_hash(object_name, face_name, u, v):
    """Deterministic 0..999 hash of a texture cell -- same scene, same
    render, always the same jittered pixels."""
    key = ("%s|%s|%d|%d" % (object_name, face_name, u, v)).encode("utf-8")
    return zlib.crc32(key) % 1000


SHADOW_BIAS = 0.35
SHADOW_DEEP = 3.0


def _build_light_map(all_faces, light):
    """A depth buffer in light space: a second parallel projection whose
    camera direction is the light itself, so `dot(p, light)` is the distance
    towards the light and the z-test ("nearest wins") finds whichever surface
    the light reaches first. Only faces that actually face the light can cast
    a shadow, same logic as the main camera's back-face cull but with L."""
    e1 = _cross(_UP, light)
    if _dot(e1, e1) < 1e-9:
        e1 = (1.0, 0.0, 0.0)
    e1 = _normalize(e1)
    e2 = _normalize(_cross(light, e1))
    casters = [f for f in all_faces if _dot(f["normal"], light) > 1e-6]
    if not casters:
        return None
    # Texels per world unit. A thin (sub-unit) roof-edge slab needs enough
    # texel density that its occlusion test does not flicker column to
    # column and saw-tooth the eave shadow along the wall below it -- finer
    # than a literal 0.5-world-unit texel, still resolution-independent of
    # the main canvas and clamped below.
    scale = 6.0
    pts = [c for f in casters for c in f["corners"]]
    lxs = [_dot(p, e1) for p in pts]
    lys = [_dot(p, e2) for p in pts]
    minx, maxx = min(lxs), max(lxs)
    miny, maxy = min(lys), max(lys)
    bw = (maxx - minx) * scale + 4
    bh = (maxy - miny) * scale + 4
    if bw > 1024 or bh > 1024:
        factor = 1024.0 / max(bw, bh)
        scale *= factor
        bw *= factor
        bh *= factor
    lw = max(1, min(1024, int(math.ceil(bw))))
    lh = max(1, min(1024, int(math.ceil(bh))))
    lox = 2.0 - minx * scale
    loy = 2.0 - miny * scale
    depth = [[float("-inf")] * lw for _ in range(lh)]
    lobj = [[None] * lw for _ in range(lh)]

    def _lplot(x, y, attrs, objn):
        if 0 <= x < lw and 0 <= y < lh and attrs[0] > depth[y][x]:
            depth[y][x] = attrs[0]
            lobj[y][x] = objn

    for f in casters:
        verts = []
        for c in f["corners"]:
            verts.append((_dot(c, e1) * scale + lox, _dot(c, e2) * scale + loy, _dot(c, light)))
        n = len(verts)
        objn = f["object"]
        for i in range(1, n - 1):
            _fill_triangle(verts[0], verts[i], verts[i + 1], lw, lh,
                           lambda px, py, attrs, objn=objn: _lplot(px, py, attrs, objn))
    return {"depth": depth, "obj": lobj, "e1": e1, "e2": e2, "scale": scale,
           "ox": lox, "oy": loy, "w": lw, "h": lh}


# --------------------------------------------------------------------------
# dirty-slope warnings
# --------------------------------------------------------------------------

_CLEAN_RATIOS = sorted(set([0.0] + [p / float(q) for q in range(1, 5) for p in range(1, 5)]))


def _nearest_clean_ratios(ratio, count=2):
    return sorted(_CLEAN_RATIOS, key=lambda c: abs(c - ratio))[:count]


def _ratio_label(c):
    """'1:N' for shallow ratios, 'N:1' for steep ones -- whichever side is
    the integer, matching how pixel artists talk about a slope."""
    if c <= 1e-9:
        return "0:1"
    if c >= 1.0:
        return "%d:1" % int(round(c))
    return "1:%d" % int(round(1.0 / c))


def _ratio_disp(ratio):
    if ratio <= 1e-9:
        return "0:1"
    if ratio >= 1.0:
        return "%.2f:1" % ratio
    return "1:%.2f" % (1.0 / ratio)


def _axis_ratio(vec):
    dx, dy = vec
    if abs(dx) < 1e-9:
        return float("inf")
    return abs(dy) / abs(dx)


def slope_warnings(scene, axes):
    """Pixel art wants slopes that step in clean ratios (1:1 .. 1:4 and their
    inverses). `view: camera` can land anywhere, so warn -- without blocking
    the render -- when an axis is off by more than 0.02 from the nearest
    clean ratio, and suggest the nearest yaw values that would fix it."""
    if scene.view != "camera" or scene.pitch is None:
        return []
    pitch, yaw = scene.pitch, scene.yaw
    t = math.tan(math.radians(pitch)) if pitch < 89.999 else 1e6
    out = []
    for name, vec in zip(("X", "Y", "Z"), axes):
        ratio = _axis_ratio(vec)
        if ratio == float("inf") or name == "Z":
            continue
        nearest = min(_CLEAN_RATIOS, key=lambda c: abs(c - ratio))
        if abs(ratio - nearest) <= 0.02:
            continue
        sugg = []
        for c in _nearest_clean_ratios(ratio, 2):
            if c <= 1e-9 or t <= 1e-9:
                continue
            if name == "X":
                yv = math.degrees(math.atan(c / t))
            else:
                yv = math.degrees(math.atan(t / c)) if c > 1e-9 else 90.0
            if yaw < 0:
                yv = -yv
            sugg.append((yv, _ratio_label(c)))
        msg = ("view: yaw %g gives a %s slope along %s -- "
              "long edges will step irregularly" % (yaw, _ratio_disp(ratio), name))
        if sugg:
            msg += "; nearest clean angles are " + " and ".join(
                "yaw %.1f (%s)" % (yv, lbl) for yv, lbl in sugg)
        out.append(msg)
    return out


def render(scene):
    axes = _axes(scene)
    cam = _compute_cam(axes)
    light = _normalize(LIGHT_DIRS[scene.light])
    warnings = slope_warnings(scene, axes)

    all_faces = []
    for obj in scene.objects:
        for f in BUILDERS[obj.type](obj):
            if f is None:
                continue
            f["object"] = obj.name
            f["material"] = obj.overrides.get(f["face"], obj.mat)
            f["shade"] = obj.shade
            all_faces.append(f)

    visible = [f for f in all_faces if _dot(f["normal"], cam) > 0]
    if not visible:
        raise SceneError("scene has no visible geometry for view %r" % scene.view, 0)

    for f in visible:
        f["tone"] = f["shade"] if f["shade"] else _tone_for(f["normal"], light)
        su = _length2(_proj_unit(axes, f["e1"])) * scene.unit
        sv = _length2(_proj_unit(axes, f["e2"])) * scene.unit
        f["su"], f["sv"] = su, sv
        verts = []
        for c in f["corners"]:
            ux, uy = _proj_unit(axes, c)
            close = _dot(c, cam)
            a = _dot(_sub(c, f["origin"]), f["e1"])
            b = _dot(_sub(c, f["origin"]), f["e2"])
            verts.append((ux * scene.unit, uy * scene.unit, close, a, b, c[0], c[1], c[2]))
        f["verts_rel"] = verts

    minx = min(v[0] for f in visible for v in f["verts_rel"])
    maxx = max(v[0] for f in visible for v in f["verts_rel"])
    miny = min(v[1] for f in visible for v in f["verts_rel"])
    maxy = max(v[1] for f in visible for v in f["verts_rel"])
    cw, ch, ox, oy = _fit_canvas(minx, maxx, miny, maxy, scene)

    face_id = [[-1] * cw for _ in range(ch)]
    close_g = [[float("-inf")] * cw for _ in range(ch)]
    a_g = [[0.0] * cw for _ in range(ch)]
    b_g = [[0.0] * cw for _ in range(ch)]
    world_g = [[None] * cw for _ in range(ch)]

    def _plot(x, y, attrs, fi):
        close = attrs[0]
        if close > close_g[y][x]:
            close_g[y][x] = close
            face_id[y][x] = fi
            a_g[y][x] = attrs[1]
            b_g[y][x] = attrs[2]
            world_g[y][x] = (attrs[3], attrs[4], attrs[5])

    for fi, f in enumerate(visible):
        verts = [(v[0] + ox, v[1] + oy, v[2], v[3], v[4], v[5], v[6], v[7]) for v in f["verts_rel"]]
        n = len(verts)
        for i in range(1, n - 1):
            _fill_triangle(verts[0], verts[i], verts[i + 1], cw, ch,
                           lambda px, py, attrs, fi=fi: _plot(px, py, attrs, fi))

    color = [[(0, 0, 0, 0)] * cw for _ in range(ch)]
    ramp_idx_g = [[-1] * cw for _ in range(ch)]
    material_g = [[None] * cw for _ in range(ch)]
    is_ink_g = [[False] * cw for _ in range(ch)]

    for y in range(ch):
        for x in range(cw):
            fi = face_id[y][x]
            if fi < 0:
                continue
            f = visible[fi]
            mat = scene.materials[f["material"]]
            ramp = _material_ramp(scene, f["material"])
            tone_idx = TONE_IDX[f["tone"]]
            char = None
            if mat.texture:
                tex = mat.texture
                if mat.space == "world":
                    u, v = a_g[y][x] * scene.unit, b_g[y][x] * scene.unit
                else:
                    u, v = a_g[y][x] * f["su"], b_g[y][x] * f["sv"]
                lu, lv = int(math.floor(u)), int(math.floor(v))
                char = tex.rows[lv % tex.h][lu % tex.w]
                if mat.jitter and char != ".":
                    hv = _jitter_hash(f["object"], f["face"], lu, lv)
                    if (hv % 100) < mat.jitter:
                        if hv % 2 == 0:
                            char = "."
                        else:
                            ddx = 1 if (hv // 2) % 2 == 0 else -1
                            ddy = 1 if (hv // 3) % 2 == 0 else -1
                            char = tex.rows[(lv + ddy) % tex.h][(lu + ddx) % tex.w]
            if char == "#":
                is_ink_g[y][x] = True
                material_g[y][x] = f["material"]
                ramp_idx_g[y][x] = tone_idx
                color[y][x] = scene.ink_rgba
            else:
                offset = TEX_OFFSETS.get(char, 0)
                idx = max(0, min(4, tone_idx + offset))
                material_g[y][x] = f["material"]
                ramp_idx_g[y][x] = idx
                color[y][x] = ramp[idx]

    # -- post pass 1: cast shadows, via a light-space depth (shadow-map) pass
    if scene.shadow >= 1:
        light_map = _build_light_map(all_faces, light)
        if light_map is not None:
            ldepth, lobj = light_map["depth"], light_map["obj"]
            le1, le2, lscale = light_map["e1"], light_map["e2"], light_map["scale"]
            lox, loy, lw, lh = light_map["ox"], light_map["oy"], light_map["w"], light_map["h"]
            for y in range(ch):
                for x in range(cw):
                    if face_id[y][x] < 0 or is_ink_g[y][x]:
                        continue
                    wpos = world_g[y][x]
                    if wpos is None:
                        continue
                    obj_p = visible[face_id[y][x]]["object"]
                    own_depth = _dot(wpos, light)
                    ix = int(round(_dot(wpos, le1) * lscale + lox))
                    iy = int(round(_dot(wpos, le2) * lscale + loy))
                    votes, max_gap = 0, 0.0
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = ix + dx, iy + dy
                        if not (0 <= nx < lw and 0 <= ny < lh):
                            continue
                        oname = lobj[ny][nx]
                        if oname is None or oname == obj_p:
                            continue
                        gap = ldepth[ny][nx] - own_depth
                        if gap > SHADOW_BIAS:
                            votes += 1
                            max_gap = max(max_gap, gap)
                    if votes >= 2:
                        steps = 2 if max_gap > SHADOW_DEEP else 1
                        idx = max(0, ramp_idx_g[y][x] - steps)
                        ramp = _material_ramp(scene, material_g[y][x])
                        color[y][x] = ramp[idx]
                        ramp_idx_g[y][x] = idx

    # -- post pass 1b: one-pixel ambient occlusion along object creases -----
    if scene.shadow >= 2:
        for y in range(ch):
            for x in range(cw):
                if face_id[y][x] < 0 or is_ink_g[y][x]:
                    continue
                obj_p = visible[face_id[y][x]]["object"]
                cp = close_g[y][x]
                darken = False
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < cw and 0 <= ny < ch) or face_id[ny][nx] < 0:
                        continue
                    if visible[face_id[ny][nx]]["object"] != obj_p and cp < close_g[ny][nx] - 0.02:
                        darken = True
                        break
                if darken:
                    idx = max(0, ramp_idx_g[y][x] - 1)
                    ramp = _material_ramp(scene, material_g[y][x])
                    color[y][x] = ramp[idx]
                    ramp_idx_g[y][x] = idx

    # -- post pass 2: outline ----------------------------------------------
    if scene.outline != "none":
        opaque = [[face_id[y][x] >= 0 for x in range(cw)] for y in range(ch)]
        to_ink = set()
        for y in range(ch):
            for x in range(cw):
                if not opaque[y][x]:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < cw and 0 <= ny < ch) or not opaque[ny][nx]:
                        to_ink.add((x, y))
                        break
        for y in range(ch):
            for x in range(cw - 1):
                if opaque[y][x] and opaque[y][x + 1]:
                    o1 = visible[face_id[y][x]]["object"]
                    o2 = visible[face_id[y][x + 1]]["object"]
                    if o1 != o2 and abs(close_g[y][x] - close_g[y][x + 1]) > 0.5:
                        to_ink.add((x, y)); to_ink.add((x + 1, y))
        for y in range(ch - 1):
            for x in range(cw):
                if opaque[y][x] and opaque[y + 1][x]:
                    o1 = visible[face_id[y][x]]["object"]
                    o2 = visible[face_id[y + 1][x]]["object"]
                    if o1 != o2 and abs(close_g[y][x] - close_g[y + 1][x]) > 0.5:
                        to_ink.add((x, y)); to_ink.add((x, y + 1))
        for x, y in to_ink:
            color[y][x] = scene.ink_rgba

    # -- assemble the .pxa doc ---------------------------------------------
    doc = pxa.Doc()
    doc.swatches.append(pxa.Swatch(pxa.TRANSPARENT_KEY, (0, 0, 0, 0), "transparent"))
    color_key = {}
    rows = []
    for y in range(ch):
        chars = []
        for x in range(cw):
            if face_id[y][x] < 0:
                chars.append(pxa.TRANSPARENT_KEY)
                continue
            rgba = color[y][x]
            key = color_key.get(rgba)
            if key is None:
                if rgba == scene.ink_rgba:
                    nm = "ink"
                else:
                    nm = _ramp_names(material_g[y][x])[ramp_idx_g[y][x]]
                sw = doc.add_swatch(rgba, nm)
                key = sw.key
                color_key[rgba] = key
            chars.append(key)
        rows.append("".join(chars))
    doc.frames.append(pxa.Frame("main", rows))
    pxa.assign_keys_by_value(doc)

    doc.meta["name"] = scene.name
    doc.meta["stage"] = "massing"
    doc.meta["light"] = scene.light
    doc.meta["view"] = _view_meta(scene, ox, oy)
    doc.meta["scene"] = os.path.basename(scene.path) if scene.path else (scene.name + ".scene")

    # -- faces report --------------------------------------------------------
    counts, bboxes = {}, {}
    for y in range(ch):
        for x in range(cw):
            fi = face_id[y][x]
            if fi < 0:
                continue
            counts[fi] = counts.get(fi, 0) + 1
            b = bboxes.get(fi)
            if b is None:
                bboxes[fi] = [x, y, x, y]
            else:
                if x < b[0]: b[0] = x
                if y < b[1]: b[1] = y
                if x > b[2]: b[2] = x
                if y > b[3]: b[3] = y

    faces_out = []
    for fi, f in enumerate(visible):
        n = counts.get(fi, 0)
        if n <= 0:
            continue
        b = bboxes[fi]
        faces_out.append({"id": fi, "object": f["object"], "face": f["face"],
                          "material": f["material"], "tone": f["tone"],
                          "normal": f["normal"], "bbox": tuple(b), "pixels": n})

    edges_out = []
    for f in visible:
        verts = f["verts_rel"]
        n = len(verts)
        for i in range(n):
            v0, v1 = verts[i], verts[(i + 1) % n]
            edges_out.append(((v0[0] + ox, v0[1] + oy), (v1[0] + ox, v1[1] + oy)))

    return Result(doc, face_id, close_g, faces_out, edges_out, (ox, oy), scene.unit, warnings)


def render_maps(scene, width=None, height=None):
    """Like render(), but honours an explicit target canvas size (the linter
    uses this to check a painted .pxa still matches the massing)."""
    if width and height:
        sc = copy.copy(scene)
        sc.canvas = (int(width), int(height))
        return render(sc)
    return render(scene)


# --------------------------------------------------------------------------
# guide image and reports
# --------------------------------------------------------------------------

_MAGENTA = (255, 40, 220, 255)


def _line_px(img, x0, y0, x1, y1, color):
    h = len(img); w = len(img[0]) if h else 0
    x0i, y0i = int(round(x0)), int(round(y0))
    x1i, y1i = int(round(x1)), int(round(y1))
    dx, dy = abs(x1i - x0i), abs(y1i - y0i)
    sx = 1 if x0i < x1i else -1
    sy = 1 if y0i < y1i else -1
    err = dx - dy
    x, y = x0i, y0i
    while True:
        if 0 <= x < w and 0 <= y < h:
            img[y][x] = color
        if x == x1i and y == y1i:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy; x += sx
        if e2 < dx:
            err += dx; y += sy


def guide_image(result, scale=4, over_doc=None):
    doc = over_doc if over_doc is not None else result.doc
    frame = doc.frame()
    img = rendermod.render_frame(doc, frame, scale, checker=max(2, scale // 2))
    rendermod.draw_grid(img, scale, major=8)

    for (x0, y0), (x1, y1) in result.edges:
        _line_px(img, x0 * scale, y0 * scale, x1 * scale, y1 * scale, _MAGENTA)

    best = {}
    for f in result.faces:
        cur = best.get(f["object"])
        if cur is None or f["pixels"] > cur["pixels"]:
            best[f["object"]] = f
    for obj_name, f in best.items():
        x0, y0, x1, y1 = f["bbox"]
        cx = int(((x0 + x1 + 1) / 2.0) * scale) - f35.text_width(obj_name) // 2
        cy = int(((y0 + y1 + 1) / 2.0) * scale) - f35.H // 2
        f35.draw_text(img, max(0, cx), max(0, cy), obj_name, _MAGENTA)

    view_word = result.doc.meta.get("view", "").split()[0] if result.doc.meta.get("view") else "?"
    legend = "VIEW:%s  UNIT:%s  LIGHT:%s" % (view_word.upper(), result.unit,
                                            result.doc.meta.get("light", "").upper())
    f35.draw_text(img, 2, 2, legend, (255, 255, 255, 255))
    return img


def faces_report(result):
    lines = ["%-14s %-14s %-12s %-7s %-16s %6s" % ("OBJECT", "FACE", "MATERIAL", "TONE", "BBOX", "PIXELS")]
    for f in result.faces:
        bbox = "%d,%d-%d,%d" % f["bbox"]
        lines.append("%-14s %-14s %-12s %-7s %-16s %6d"
                     % (f["object"], f["face"], f["material"], f["tone"], bbox, f["pixels"]))
    return "\n".join(lines)
