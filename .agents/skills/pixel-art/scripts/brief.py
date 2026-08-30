"""Art-direction brief: a machine-readable header the model fills in before
drawing anything, so `px new` / `px scene` never start from a guess about
class, view, canvas or palette.

A brief.md carries one '---' fenced header of 'key: value' lines (comments
after a ' #' are stripped) followed by the usual prose sections. `validate()`
is the hard gate `px brief` runs; `brief_header()` is the bit other modules
need to read it back.
"""

import os
import re
import json

import pxa

HEADER_KEYS = ("class", "view", "canvas", "palette", "light", "outline", "dither")
CLASS_CHOICES = ("character", "structure", "prop", "scene")
VIEW_KINDS = ("side", "3/4-topdown", "iso", "oblique", "custom", "camera")
LIGHT_CHOICES = ("top-left", "top-right", "top", "left", "right",
                 "front", "back", "overhead", "rim")

# structures and scenes are built up from placed pieces; characters and props
# are drawn directly on one canvas.
PIPELINE_FOR_CLASS = {"character": "character", "prop": "character",
                      "structure": "structure", "scene": "structure"}


def _strip_comment(line):
    """Drop a trailing ' #comment' -- but not a '#' that is part of a value
    such as a hex colour, which never has a space before it."""
    i = line.find(" #")
    return line[:i] if i != -1 else line


def _is_float(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def _brief_path(path):
    return os.path.join(path, "brief.md") if os.path.isdir(path) else path


def brief_header(path):
    """-> dict of the '---' fenced header at the top of a brief.md. `path` may
    be a project directory (looks for brief.md inside it) or the file itself."""
    p = _brief_path(path)
    if not os.path.exists(p):
        raise pxa.PxaError("no such brief: %s" % p)
    with open(p, "r") as fh:
        lines = fh.read().splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return {}
    i += 1
    header = {}
    while i < len(lines) and lines[i].strip() != "---":
        line = _strip_comment(lines[i]).strip()
        i += 1
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        header[k.strip()] = v.strip()
    return header


def pipeline_for(header):
    return PIPELINE_FOR_CLASS.get(header.get("class"), "character")


def validate(path):
    """-> (header, problems, notes). `problems` is a list of human-readable
    strings; an empty list means the brief is good to build from. `notes` are
    advisory -- they never block, but are worth printing (e.g. a canvas gate
    that was skipped because the reference study behind it is unverified)."""
    p = _brief_path(path)
    header = brief_header(p)
    problems = []
    notes = []

    for k in HEADER_KEYS:
        if not header.get(k):
            problems.append("missing key: %s" % k)

    cls = header.get("class")
    if cls and cls not in CLASS_CHOICES:
        problems.append("class: %r is not one of %s" % (cls, " | ".join(CLASS_CHOICES)))

    view = header.get("view")
    if view:
        kind = view.split()[0]
        if kind not in VIEW_KINDS:
            problems.append("view: %r is not one of %s" % (view, " | ".join(VIEW_KINDS)))
        elif kind == "3/4-topdown":
            m = re.search(r"\bk=([^\s]+)", view)
            if not m or not _is_float(m.group(1)):
                problems.append("view: '3/4-topdown' must carry a k=<float> parameter, "
                                "e.g. '3/4-topdown k=0.5' (got %r)" % view)
        elif kind == "custom" and "axes=" not in view:
            problems.append("view: 'custom' must carry an axes=... parameter (got %r)" % view)
        elif kind == "camera" and not re.search(r"\bpitch=([0-9.]+)", view):
            problems.append("view: 'camera' must carry a pitch=<degrees> parameter "
                            "(0 = side view, 26.57 = the RPG tilt, 90 = straight down), "
                            "optionally yaw=<degrees> (0 = front-on, 45 = isometric); "
                            "got %r" % view)

    canvas = header.get("canvas")
    cw = ch = None
    if canvas:
        m = re.match(r"^(\d+)\s*x\s*(\d+)$", canvas.strip())
        if not m:
            problems.append("canvas: %r is not WxH" % canvas)
        else:
            cw, ch = int(m.group(1)), int(m.group(2))
            if not (16 <= cw <= 512 and 16 <= ch <= 512):
                problems.append("canvas: %s -- W and H must both be in 16..512" % canvas)

    light = header.get("light")
    if light and light not in LIGHT_CHOICES:
        problems.append("light: %r is not a known direction (%s)"
                        % (light, " | ".join(LIGHT_CHOICES)))

    if cw is not None and ch is not None:
        study_path = os.path.join(os.path.dirname(os.path.abspath(p)), "ref_study.json")
        if os.path.exists(study_path):
            with open(study_path, "r") as fh:
                data = json.load(fh)
            brief_data = data.get("brief", {})
            suggested = brief_data.get("minimum_canvas") or brief_data.get("suggested_canvas")
            # the floor is only trustworthy if the reference(s) that set it had
            # their pixel scale actually detected -- otherwise "smallest
            # reference subject" is a number derived from a grid `px ref`
            # admitted it never found, and gating on it would silently force
            # whatever absurd canvas that guess implies.
            floor_confident = brief_data.get("floor_confident", True)
            if suggested and not floor_confident:
                notes.append(
                    "canvas gate skipped: the reference study's floor (%s) came from a "
                    "reference whose pixel scale could not be detected -- verify the "
                    "scale by eye on the contact sheet and re-run 'px ref --scale N', "
                    "then re-check the canvas against the corrected study" % suggested)
            elif suggested:
                sw, sh = (int(v) for v in suggested.split("x"))
                if (cw < sw or ch < sh) and not header.get("canvas-override"):
                    problems.append(
                        "canvas: %s is smaller than the smallest reference subject (%s) "
                        "-- the volumes will collapse into blocks at that size. Widen it, "
                        "or add a 'canvas-override: reason ...' line to force it"
                        % (canvas, suggested))

    return header, problems, notes
