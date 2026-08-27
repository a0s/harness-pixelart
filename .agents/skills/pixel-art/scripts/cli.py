#!/usr/bin/env python3
"""px -- the pixel-art toolchain.

One command surface for both the agent and the human. Every subcommand prints
the path of whatever it produced, so the next step is always obvious.
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pxa
import imaging
import palettes
import canvas
import lint as lintmod
import render
import anim
import convert
import refstudy
import export as exportmod

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _out(msg=""):
    sys.stdout.write(str(msg) + "\n")


def _doc(path):
    if not os.path.exists(path):
        raise SystemExit("no such file: %s" % path)
    return pxa.load(path)


def _save(doc, path, quiet=False):
    pxa.save(doc, path)
    if not quiet:
        _out("wrote %s  (%dx%d, %d frame(s), %d colours)"
             % (path, doc.width, doc.height, len(doc.frames), len(doc.opaque_swatches())))
    return path


def _sidecar(path, kind, ext="png"):
    base = os.path.splitext(os.path.abspath(path))[0]
    d = os.path.join(os.path.dirname(base), "review")
    if not os.path.isdir(d):
        os.makedirs(d)
    return os.path.join(d, "%s_%s.%s" % (os.path.basename(base), kind, ext))


def _parse_size(text, default=(32, 32)):
    if not text:
        return default
    t = text.lower().replace("*", "x")
    if "x" in t:
        a, b = t.split("x", 1)
        return int(a), int(b)
    return int(t), int(t)


def _resolve_palette(spec, colors=16):
    if not spec:
        return None
    if os.path.exists(spec) and spec.endswith(".pxa"):
        return [s.rgba for s in pxa.load(spec).opaque_swatches()]
    if os.path.exists(spec) and spec.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        px, _, _ = imaging.load_image(spec)
        return palettes.extract(px, colors)
    return palettes.load_palette(spec)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_new(a):
    w, h = _parse_size(a.size)
    doc = pxa.blank(w, h, a.name or os.path.splitext(os.path.basename(a.file))[0])
    pal = _resolve_palette(a.palette, a.colors) if a.palette else None
    if pal:
        for c in palettes.sort_palette(pal):
            doc.add_swatch(c)
        pxa.assign_keys_by_value(doc)
    doc.meta["stage"] = "silhouette"
    if a.light:
        doc.meta["light"] = a.light
    if a.fps:
        doc.meta["fps"] = str(a.fps)
    for i in range(1, max(1, a.frames)):
        anim.add_frame(doc, "f%d" % i)
    return _save(doc, a.file)


def cmd_grid(a):
    doc = _doc(a.file)
    frames = doc.frames if a.all else [doc.frame(a.frame)]
    for f in frames:
        _out("@frame %s   %dx%d" % (f.name, f.width, f.height))
        head = "".join(str((x // 10) % 10) if x % 5 == 0 else " " for x in range(f.width))
        ones = "".join(str(x % 10) for x in range(f.width))
        _out("     " + head)
        _out("     " + ones)
        for y, row in enumerate(f.rows):
            _out("%4d %s" % (y, row))
        _out("")
    if a.palette:
        _out("@palette")
        counts = doc.frames[0].counts()
        for s in doc.swatches:
            _out("  %s %-9s %-16s %5d px" % (s.key, pxa.format_hex(s.rgba, s.is_transparent),
                                             s.name or "", counts.get(s.key, 0)))


def cmd_render(a):
    doc = _doc(a.file)
    frame = doc.frame(a.frame)
    scale = a.scale or 1
    bg = pxa.parse_hex(a.background) if a.background else None
    out = a.out or _sidecar(a.file, "render_%s_x%d" % (frame.name, scale))
    img = render.render_frame(doc, frame, scale, background=bg,
                              checker=(max(2, scale // 2) if a.checker else 0))
    if a.grid and scale >= 3:
        render.draw_grid(img, scale, major=8)
    pxa.write_png(out, img)
    _out(out)


def cmd_view(a):
    doc = _doc(a.file)
    notes = a.note or []
    if a.lint:
        findings = lintmod.run(doc, {"max_colors": a.max_colors}, animation=False,
                               frames=[a.frame] if a.frame else None)
        notes = notes + ["%s: %s" % (f.rule.upper(), f.message[:88])
                         for f in findings if f.severity != "info"][:6]
    img = render.review_sheet(doc, a.frame, scale=a.scale, target=a.target,
                              grid=not a.no_grid, notes=notes)
    out = a.out or _sidecar(a.file, "sheet")
    pxa.write_png(out, img)
    _out(out)
    _out("look at this image before you touch the grid again")


def cmd_strip(a):
    doc = _doc(a.file)
    img = render.filmstrip(doc, scale=a.scale, target=a.target)
    out = a.out or _sidecar(a.file, "strip")
    pxa.write_png(out, img)
    _out(out)


def cmd_onion(a):
    doc = _doc(a.file)
    idx = doc.frames.index(doc.frame(a.frame)) if a.frame else 0
    img = render.onion_sheet(doc, idx, scale=a.scale, prev=a.prev, next=a.next)
    out = a.out or _sidecar(a.file, "onion_%d" % idx)
    pxa.write_png(out, img)
    _out(out)


def cmd_lint(a):
    doc = _doc(a.file)
    cfg = {}
    if a.max_colors:
        cfg["max_colors"] = a.max_colors
    findings = lintmod.run(doc, cfg, frames=[a.frame] if a.frame else None,
                           animation=not a.no_anim)
    if a.json:
        _out(json.dumps([f.as_dict() for f in findings], indent=2))
    else:
        _out(lintmod.format_text(findings, verbose=a.verbose))
    if a.strict and any(f.severity == "error" for f in findings):
        raise SystemExit(2)


def cmd_fix(a):
    doc = _doc(a.file)
    changed = 0
    for f in doc.frames:
        if a.orphans:
            changed += canvas.clean_orphans(doc, f)
    if a.dedupe:
        opaque = doc.opaque_swatches()
        merged = []
        for i, s in enumerate(opaque):
            for t in opaque[:i]:
                if t.key in [m[1] for m in merged]:
                    continue
                if pxa.color_distance(s.rgba, t.rgba) < a.dedupe_threshold:
                    merged.append((s.key, t.key)); break
        for src, dst in merged:
            for f in doc.frames:
                canvas.replace(f, src, dst)
            doc.swatches = [s for s in doc.swatches if s.key != src]
            changed += 1
        if merged:
            _out("merged %d redundant colour(s)" % len(merged))
    if a.prune:
        used = set()
        for f in doc.frames:
            used |= set(f.counts().keys())
        before = len(doc.swatches)
        doc.swatches = [s for s in doc.swatches if s.key in used or s.is_transparent]
        if before != len(doc.swatches):
            _out("dropped %d unused swatch(es)" % (before - len(doc.swatches)))
            changed += before - len(doc.swatches)
    _out("changed %d pixel(s)/entry(ies)" % changed)
    _save(doc, a.out or a.file)


def cmd_edit(a):
    doc = _doc(a.file)
    frames = doc.frames if a.all_frames else [doc.frame(a.frame)]
    for f in frames:
        op = a.op
        if op == "rect":
            canvas.rect(f, a.x, a.y, a.x2, a.y2, a.key, fill=a.fill)
        elif op == "line":
            canvas.line(f, a.x, a.y, a.x2, a.y2, a.key)
        elif op == "ellipse":
            canvas.ellipse(f, a.x, a.y, a.x2, a.y2, a.key, fill=a.fill)
        elif op == "fill":
            canvas.flood_fill(f, a.x, a.y, a.key, diagonal=a.diagonal)
        elif op == "replace":
            canvas.replace(f, a.key_from, a.key)
        elif op == "shift":
            canvas.shift(f, a.x, a.y, empty=doc.transparent_key())
        elif op == "mirror":
            canvas.mirror(f, axis=a.axis, source=a.source)
        elif op == "flip":
            (canvas.flip_h if a.axis == "x" else canvas.flip_v)(f)
        elif op == "outline":
            canvas.outline(doc, f, a.key, mode=a.mode, diagonal=a.diagonal)
        elif op == "silhouette":
            canvas.silhouette(doc, f, a.key)
        elif op == "crop":
            canvas.crop_to_content(doc, f, margin=a.margin)
        elif op == "resize":
            w, h = _parse_size(a.size)
            canvas.resize_canvas(doc, f, w, h, anchor=a.anchor)
        elif op == "scale":
            canvas.scale_up(f, a.factor)
        elif op == "patch":
            rows = [r for r in (a.rows or "").split("/") if r]
            canvas.patch(f, a.x, a.y, rows, transparent_passthrough=a.passthrough)
        else:
            raise SystemExit("unknown op: %s" % op)
    _save(doc, a.out or a.file)


def cmd_palette(a):
    sub = a.palette_cmd
    if sub == "list":
        names = palettes.bundled_names()
        _out("bundled palettes (%s):" % palettes.ASSETS)
        for n in names:
            cols = palettes.load_palette(n)
            _out("  %-22s %2d colours  %s" % (n, len(cols),
                 " ".join(pxa.format_hex(c) for c in cols[:8]) + (" ..." if len(cols) > 8 else "")))
        _out("\nalso: lospec:<slug>, any .hex/.gpl/.pal file, any image, any .pxa")
        return
    if sub == "extract":
        px, w, h = imaging.load_image(a.image)
        cols = palettes.extract(px, a.colors)
        _out("\n".join(pxa.format_hex(c) for c in cols))
        if a.out:
            _out("wrote " + palettes.save_hex(cols, a.out))
        return
    if sub == "ramp":
        base = pxa.parse_hex(a.color)
        r = palettes.ramp(base, steps=a.steps, hue_shift=a.hue_shift,
                          shadow_hue=a.shadow_hue, light_hue=a.light_hue)
        for c in r:
            h, s, l = pxa.rgb_to_hsl(c)
            _out("%s   h%3.0f s%3.0f l%3.0f" % (pxa.format_hex(c), h, s, l))
        if a.out:
            _out("wrote " + palettes.save_hex(r, a.out))
        return
    if sub == "get":
        cols = palettes.load_palette(a.name)
        _out("\n".join(pxa.format_hex(c) for c in cols))
        if a.out:
            _out("wrote " + palettes.save_hex(cols, a.out))
        return
    if sub == "apply":
        doc = _doc(a.file)
        pal = _resolve_palette(a.palette, a.colors)
        if not pal:
            raise SystemExit("--palette is required")
        newdoc = doc.copy()
        newdoc.swatches = [pxa.Swatch(pxa.TRANSPARENT_KEY, (0, 0, 0, 0), "transparent")]
        for c in palettes.sort_palette(pal):
            newdoc.add_swatch(c)
        newdoc.frames = []
        for f in doc.frames:
            px = pxa.frame_to_pixels(doc, f)
            snapped = palettes.snap_pixels(px, pal, dither=a.dither, strength=a.strength)
            newdoc.frames.append(pxa.pixels_to_frame(newdoc, snapped, f.name, add_missing=False))
        _save(newdoc, a.out or a.file)
        return
    if sub == "show":
        doc = _doc(a.file)
        img = render.palette_strip(doc, doc.frames[0], cell=18, cols=8)
        out = a.out or _sidecar(a.file, "palette")
        pxa.write_png(out, img)
        _out(out)
        for s in doc.swatches:
            h, sa, l = pxa.rgb_to_hsl(s.rgba)
            _out("  %s %-9s h%3.0f s%3.0f l%3.0f  %s"
                 % (s.key, pxa.format_hex(s.rgba, s.is_transparent), h, sa, l, s.name))
        return


def cmd_ref(a):
    reports = [refstudy.study(p, colors=a.colors) for p in a.images]
    b = refstudy.brief(reports)
    out_dir = a.out or os.path.dirname(os.path.abspath(a.images[0]))
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    sheet = refstudy.contact_sheet(reports, os.path.join(out_dir, "ref_contact.png"))
    data = {"references": [dict((k, v) for k, v in r.items() if k != "palette_rgba")
                           for r in reports],
            "brief": dict((k, v) for k, v in b.items() if k != "merged_palette_rgba")}
    jpath = os.path.join(out_dir, "ref_study.json")
    with open(jpath, "w") as fh:
        json.dump(data, fh, indent=2)
    if b["merged_palette_rgba"]:
        palettes.save_hex(b["merged_palette_rgba"], os.path.join(out_dir, "ref_palette.hex"))
    for r in reports:
        _out("%s  native %s (scale x%d)  %d unique colours  value %d-%d  hue-shift %s deg  dither %s"
             % (os.path.basename(r["path"]), r["native_size"], r["pixel_scale"],
                r["unique_colors"], r["value_range"][0], r["value_range"][1],
                r["hue_shift_deg"], r["dither_density"]))
        _out("   outline: %s" % r["outline"])
        _out("   palette: %s" % " ".join(r["palette"]))
        for ramp in r["ramps"]:
            _out("     ramp: %s" % " -> ".join(ramp))
    _out("")
    _out("suggested canvas: %s" % b["suggested_canvas"])
    _out("merged palette:   %s" % " ".join(b["merged_palette"]))
    _out("wrote %s and %s" % (sheet, jpath))
    _out("look at the contact sheet before you choose the palette")


def cmd_import(a):
    pal = _resolve_palette(a.palette, a.colors) if a.palette else None
    w, h = (_parse_size(a.size) if a.size else (None, None))
    doc = convert.image_to_doc(a.image, width=w, height=h, colors=a.colors,
                               palette=pal, dither=a.dither, strength=a.strength,
                               name=a.name, crop_transparent=not a.no_crop)
    _save(doc, a.out)
    _out("this is a draft: machine downsampling does not know which pixel carries the read")


def cmd_sheet(a):
    fw, fh = _parse_size(a.frame_size)
    pal = _resolve_palette(a.palette, a.colors) if a.palette else None
    doc = convert.sheet_to_doc(a.image, fw, fh, columns=a.columns, rows=a.rows,
                               colors=a.colors, palette=pal, name=a.name)
    _save(doc, a.out)


def cmd_anim(a):
    doc = _doc(a.file)
    sub = a.anim_cmd
    if sub == "add":
        anim.add_frame(doc, a.name, source=a.copy_from, after=a.after)
        _save(doc, a.file)
    elif sub == "remove":
        anim.remove_frame(doc, a.name)
        _save(doc, a.file)
    elif sub == "order":
        anim.reorder(doc, a.names)
        _save(doc, a.file)
    elif sub == "timing":
        if a.fps:
            doc.meta["fps"] = str(a.fps)
            doc.meta.pop("timing", None)
        if a.ms:
            doc.meta["timing"] = a.ms
        _save(doc, a.file)
        _out("timing: %s ms" % anim.timing(doc))
    elif sub == "drift":
        findings = anim.drift(doc, anchor=a.anchor)
        if not findings:
            _out("no drift: volume, size and anchor hold across all frames")
        for f in findings:
            _out("* [%s] (%s) %s" % (f["rule"], f["frame"], f["message"]))
        for m in anim.motion_report(doc):
            _out("  %s -> %s: %d px change (%.1f%% of canvas)"
                 % (m["from"], m["to"], m["changed"], m["ratio"] * 100))
    elif sub == "stats":
        for f in doc.frames:
            s = anim.stats(doc, f)
            _out("%-10s area %4d  bbox %s  size %dx%d  com %s"
                 % (s["name"], s["area"], s["bbox"], s["width"], s["height"], s["com"]))
    elif sub == "gif":
        out = a.out or os.path.splitext(a.file)[0] + ".gif"
        _out(exportmod.gif(doc, out, scale=a.scale, fps=a.fps))


def cmd_export(a):
    doc = _doc(a.file)
    out_dir = a.out or os.path.join(os.path.dirname(os.path.abspath(a.file)), "out")
    scales = tuple(int(s) for s in a.scales.split(",") if s.strip())
    written = exportmod.bundle(doc, out_dir, scales=scales, fps=a.fps,
                               sheet=not a.no_sheet, make_gif=(None if not a.no_gif else False))
    for p in written:
        _out(p)


def cmd_diff(a):
    d1, d2 = _doc(a.a), _doc(a.b)
    f1, f2 = d1.frame(a.frame), d2.frame(a.frame)
    if (f1.width, f1.height) != (f2.width, f2.height):
        _out("different canvas sizes: %dx%d vs %dx%d" % (f1.width, f1.height, f2.width, f2.height))
        return
    changed = [(x, y) for y in range(f1.height) for x in range(f1.width)
               if f1.rows[y][x] != f2.rows[y][x]]
    _out("%d pixel(s) differ (%.1f%% of canvas)"
         % (len(changed), 100.0 * len(changed) / (f1.width * f1.height)))
    if a.show and changed:
        _out(" ".join("%d,%d" % c for c in changed[:80]))
    if a.image:
        img = render.compare_sheet([pxa.frame_to_pixels(d1, f1), pxa.frame_to_pixels(d2, f2)],
                                   [os.path.basename(a.a), os.path.basename(a.b)],
                                   scale=a.scale, title="diff")
        pxa.write_png(a.image, img)
        _out(a.image)


def cmd_snapshot(a):
    doc = _doc(a.file)
    base = os.path.dirname(os.path.abspath(a.file))
    hist = os.path.join(base, "history")
    if not os.path.isdir(hist):
        os.makedirs(hist)
    n = len([f for f in os.listdir(hist) if f.endswith(".png")])
    stage = a.stage or doc.meta.get("stage", "step")
    name = "%03d_%s" % (n + 1, stage.replace(" ", "-"))
    scale = a.scale or max(1, 240 // max(doc.width, doc.height))
    pxa.write_png(os.path.join(hist, name + ".png"),
                  render.render_frame(doc, doc.frame(a.frame), scale, checker=max(1, scale // 2)))
    pxa.save(doc, os.path.join(hist, name + ".pxa"))
    if a.stage:
        doc.meta["stage"] = a.stage
        pxa.save(doc, a.file)
    with open(os.path.join(hist, name + ".txt"), "w") as fh:
        fh.write((a.note or stage) + "\n")
    _out(os.path.join(hist, name + ".png"))


def cmd_project(a):
    root = os.path.abspath(a.dir)
    for sub in ("refs", "review", "history", "out"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            os.makedirs(d)
    brief = os.path.join(root, "brief.md")
    if not os.path.exists(brief):
        with open(brief, "w") as fh:
            fh.write(BRIEF_TEMPLATE % {"name": a.name or os.path.basename(root)})
    _out(root)
    _out("  refs/     drop reference images here")
    _out("  brief.md  fill this in before drawing anything")
    _out("  history/  stage snapshots (the studio timeline reads this)")


def cmd_doctor(a):
    _out("python:  %s" % sys.version.split()[0])
    _out("pillow:  %s" % ("yes" if imaging.HAVE_PIL else "no (PNG-only reference intake)"))
    _out("skill:   %s" % SKILL_DIR)
    _out("palettes: %d bundled" % len(palettes.bundled_names()))
    try:
        import urllib.request  # noqa
        _out("network: urllib available (lospec:<slug> works if online)")
    except Exception:
        _out("network: unavailable")
    if not imaging.HAVE_PIL:
        _out("")
        _out("to read JPEG/WebP references, install Pillow:")
        _out("  python3 -m pip install --user Pillow")


BRIEF_TEMPLATE = """# %(name)s -- art direction brief

## Subject
One sentence. What is it, seen from where, doing what.

## Read at 1x
What must be identifiable when the sprite is 32 px tall and moving.

## Canvas & palette
- canvas:
- palette (locked before drawing):
- colour budget:

## Light
- direction:
- key/shadow logic:

## Style rules taken from the references
- outline:
- dither:
- hue shift:
- level of detail:

## Animation
- frames:
- loop type:
- what moves, what holds:

## Out of scope
"""


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="px", description="pixel-art toolchain")
    sub = p.add_subparsers(dest="cmd")

    q = sub.add_parser("new", help="create a blank .pxa")
    q.add_argument("file")
    q.add_argument("--size", default="32x32")
    q.add_argument("--name")
    q.add_argument("--palette")
    q.add_argument("--colors", type=int, default=16)
    q.add_argument("--frames", type=int, default=1)
    q.add_argument("--light")
    q.add_argument("--fps", type=int)
    q.set_defaults(func=cmd_new)

    q = sub.add_parser("grid", help="print the grid as text with a coordinate ruler")
    q.add_argument("file")
    q.add_argument("--frame")
    q.add_argument("--all", action="store_true")
    q.add_argument("--palette", action="store_true")
    q.set_defaults(func=cmd_grid)

    q = sub.add_parser("render", help="render one frame to PNG")
    q.add_argument("file")
    q.add_argument("--frame")
    q.add_argument("--scale", type=int, default=1)
    q.add_argument("--out")
    q.add_argument("--background")
    q.add_argument("--checker", action="store_true")
    q.add_argument("--grid", action="store_true")
    q.set_defaults(func=cmd_render)

    q = sub.add_parser("view", help="review sheet: the image you must actually look at")
    q.add_argument("file")
    q.add_argument("--frame")
    q.add_argument("--scale", type=int)
    q.add_argument("--target", type=int, default=560)
    q.add_argument("--out")
    q.add_argument("--note", action="append")
    q.add_argument("--no-grid", action="store_true")
    q.add_argument("--lint", action="store_true", help="print top findings on the sheet")
    q.add_argument("--max-colors", type=int)
    q.set_defaults(func=cmd_view)

    q = sub.add_parser("strip", help="filmstrip of every frame")
    q.add_argument("file")
    q.add_argument("--scale", type=int)
    q.add_argument("--target", type=int, default=110)
    q.add_argument("--out")
    q.set_defaults(func=cmd_strip)

    q = sub.add_parser("onion", help="onion-skin sheet for one frame")
    q.add_argument("file")
    q.add_argument("--frame")
    q.add_argument("--scale", type=int)
    q.add_argument("--prev", type=int, default=1)
    q.add_argument("--next", type=int, default=1)
    q.add_argument("--out")
    q.set_defaults(func=cmd_onion)

    q = sub.add_parser("lint", help="craft check")
    q.add_argument("file")
    q.add_argument("--frame")
    q.add_argument("--json", action="store_true")
    q.add_argument("--verbose", action="store_true")
    q.add_argument("--strict", action="store_true")
    q.add_argument("--no-anim", action="store_true")
    q.add_argument("--max-colors", type=int)
    q.set_defaults(func=cmd_lint)

    q = sub.add_parser("fix", help="mechanical cleanups")
    q.add_argument("file")
    q.add_argument("--orphans", action="store_true")
    q.add_argument("--dedupe", action="store_true")
    q.add_argument("--dedupe-threshold", type=float, default=7.0)
    q.add_argument("--prune", action="store_true")
    q.add_argument("--out")
    q.set_defaults(func=cmd_fix)

    q = sub.add_parser("edit", help="coarse drawing operations")
    q.add_argument("file")
    q.add_argument("op", choices=["rect", "line", "ellipse", "fill", "replace", "shift",
                                  "mirror", "flip", "outline", "silhouette", "crop",
                                  "resize", "scale", "patch"])
    q.add_argument("--frame")
    q.add_argument("--all-frames", action="store_true")
    q.add_argument("-x", type=int, default=0)
    q.add_argument("-y", type=int, default=0)
    q.add_argument("--x2", type=int, default=0)
    q.add_argument("--y2", type=int, default=0)
    q.add_argument("--key", default="K")
    q.add_argument("--key-from", default=".")
    q.add_argument("--fill", action="store_true")
    q.add_argument("--diagonal", action="store_true")
    q.add_argument("--mode", default="inside", choices=["inside", "outside"])
    q.add_argument("--axis", default="x", choices=["x", "y"])
    q.add_argument("--source", default="left", choices=["left", "right"])
    q.add_argument("--margin", type=int, default=0)
    q.add_argument("--size", default="32x32")
    q.add_argument("--anchor", default="center", choices=["center", "topleft", "bottom"])
    q.add_argument("--factor", type=int, default=2)
    q.add_argument("--rows", help="patch rows separated by /")
    q.add_argument("--passthrough", default="~")
    q.add_argument("--out")
    q.set_defaults(func=cmd_edit)

    q = sub.add_parser("palette", help="palette work")
    ps = q.add_subparsers(dest="palette_cmd")
    r = ps.add_parser("list"); r.set_defaults(func=cmd_palette)
    r = ps.add_parser("extract"); r.add_argument("image"); r.add_argument("--colors", type=int, default=16)
    r.add_argument("--out"); r.set_defaults(func=cmd_palette)
    r = ps.add_parser("ramp"); r.add_argument("color"); r.add_argument("--steps", type=int, default=5)
    r.add_argument("--hue-shift", type=float, default=22.0)
    r.add_argument("--shadow-hue", type=float, default=250.0)
    r.add_argument("--light-hue", type=float, default=45.0)
    r.add_argument("--out"); r.set_defaults(func=cmd_palette)
    r = ps.add_parser("get"); r.add_argument("name"); r.add_argument("--out")
    r.set_defaults(func=cmd_palette)
    r = ps.add_parser("apply"); r.add_argument("file"); r.add_argument("--palette", required=True)
    r.add_argument("--colors", type=int, default=16)
    r.add_argument("--dither", default="none",
                   choices=["none", "bayer2", "bayer4", "bayer8", "fs", "atkinson"])
    r.add_argument("--strength", type=float, default=1.0)
    r.add_argument("--out"); r.set_defaults(func=cmd_palette)
    r = ps.add_parser("show"); r.add_argument("file"); r.add_argument("--out")
    r.set_defaults(func=cmd_palette)

    q = sub.add_parser("ref", help="study reference images")
    q.add_argument("images", nargs="+")
    q.add_argument("--colors", type=int, default=16)
    q.add_argument("--out")
    q.set_defaults(func=cmd_ref)

    q = sub.add_parser("import", help="raster image -> draft .pxa")
    q.add_argument("image")
    q.add_argument("--out", required=True)
    q.add_argument("--size")
    q.add_argument("--colors", type=int, default=16)
    q.add_argument("--palette")
    q.add_argument("--dither", default="none",
                   choices=["none", "bayer2", "bayer4", "bayer8", "fs", "atkinson"])
    q.add_argument("--strength", type=float, default=1.0)
    q.add_argument("--name")
    q.add_argument("--no-crop", action="store_true")
    q.set_defaults(func=cmd_import)

    q = sub.add_parser("sheet", help="slice a spritesheet into frames")
    q.add_argument("image")
    q.add_argument("--frame-size", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--columns", type=int)
    q.add_argument("--rows", type=int)
    q.add_argument("--colors", type=int, default=16)
    q.add_argument("--palette")
    q.add_argument("--name")
    q.set_defaults(func=cmd_sheet)

    q = sub.add_parser("anim", help="animation")
    as_ = q.add_subparsers(dest="anim_cmd")
    r = as_.add_parser("add"); r.add_argument("file"); r.add_argument("name")
    r.add_argument("--copy-from"); r.add_argument("--after"); r.set_defaults(func=cmd_anim)
    r = as_.add_parser("remove"); r.add_argument("file"); r.add_argument("name")
    r.set_defaults(func=cmd_anim)
    r = as_.add_parser("order"); r.add_argument("file"); r.add_argument("names", nargs="+")
    r.set_defaults(func=cmd_anim)
    r = as_.add_parser("timing"); r.add_argument("file"); r.add_argument("--fps", type=int)
    r.add_argument("--ms"); r.set_defaults(func=cmd_anim)
    r = as_.add_parser("drift"); r.add_argument("file")
    r.add_argument("--anchor", default="bottom", choices=["bottom", "center", "none"])
    r.set_defaults(func=cmd_anim)
    r = as_.add_parser("stats"); r.add_argument("file"); r.set_defaults(func=cmd_anim)
    r = as_.add_parser("gif"); r.add_argument("file"); r.add_argument("--out")
    r.add_argument("--scale", type=int, default=6); r.add_argument("--fps", type=int)
    r.set_defaults(func=cmd_anim)

    q = sub.add_parser("export", help="game-ready bundle")
    q.add_argument("file")
    q.add_argument("--out")
    q.add_argument("--scales", default="1,2,4")
    q.add_argument("--fps", type=int)
    q.add_argument("--no-sheet", action="store_true")
    q.add_argument("--no-gif", action="store_true")
    q.set_defaults(func=cmd_export)

    q = sub.add_parser("diff", help="compare two .pxa files")
    q.add_argument("a"); q.add_argument("b")
    q.add_argument("--frame")
    q.add_argument("--show", action="store_true")
    q.add_argument("--image")
    q.add_argument("--scale", type=int, default=6)
    q.set_defaults(func=cmd_diff)

    q = sub.add_parser("snapshot", help="freeze the current state into history/")
    q.add_argument("file")
    q.add_argument("--stage")
    q.add_argument("--note")
    q.add_argument("--frame")
    q.add_argument("--scale", type=int)
    q.set_defaults(func=cmd_snapshot)

    q = sub.add_parser("project", help="create a workspace project folder")
    q.add_argument("dir")
    q.add_argument("--name")
    q.set_defaults(func=cmd_project)

    q = sub.add_parser("studio", help="live split-screen viewer")
    q.add_argument("--dir", default=".")
    q.add_argument("--port", type=int, default=8765)
    q.add_argument("--host", default="127.0.0.1")
    q.add_argument("--open", action="store_true")
    q.set_defaults(func=lambda a: __import__("studio").serve(a.dir, a.host, a.port, a.open))

    q = sub.add_parser("doctor", help="environment check")
    q.set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if not getattr(a, "func", None):
        p.print_help()
        return 1
    try:
        a.func(a)
    except pxa.PxaError as exc:
        raise SystemExit("error: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
