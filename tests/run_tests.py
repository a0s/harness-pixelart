#!/usr/bin/env python3
"""Smoke and behaviour tests for the pixel-art toolchain.

Run: python3 tests/run_tests.py
No dependencies. Exits non-zero on the first failure summary.
"""

import os
import sys
import json
import shutil
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".agents", "skills", "pixel-art", "scripts"))

import pxa
import canvas
import palettes
import lint as lintmod
import render
import anim
import export as exportmod
import gifwrite
import imaging
import convert
import refstudy

RESULTS = []


def test(fn):
    RESULTS.append(fn)
    return fn


def eq(a, b, what=""):
    if a != b:
        raise AssertionError("%s: expected %r, got %r" % (what or "value", b, a))


def ok(cond, what):
    if not cond:
        raise AssertionError(what)


def sample_doc(w=16, h=16):
    doc = pxa.blank(w, h, "sample")
    for hexv, name in (("#1a1c2c", "ink"), ("#29366f", "shadow"),
                       ("#3b5dc9", "cloth"), ("#ef7d57", "skin"),
                       ("#ffcd75", "hair")):
        doc.add_swatch(pxa.parse_hex(hexv), name)
    pxa.assign_keys_by_value(doc)
    return doc


# --------------------------------------------------------------------------

@test
def format_roundtrip():
    doc = sample_doc()
    f = doc.frame()
    keys = [s.key for s in doc.opaque_swatches()]
    canvas.ellipse(f, 8, 8, 5, 5, keys[2], fill=True)
    canvas.outline(doc, f, keys[0], mode="inside")
    text = pxa.serialize(doc)
    again = pxa.parse(text)
    eq(pxa.serialize(again), text, "serialize is stable")
    eq(again.width, 16, "width")
    eq(again.frames[0].rows, doc.frames[0].rows, "grid survives")
    eq(again.validate(), [], "document validates")


@test
def format_rejects_bad_grid():
    doc = pxa.parse("@palette\n. #00000000 t\nK #ffffff w\n@frame a\nKK.\nK.\n")
    problems = doc.validate()
    ok(any("row 1" in p for p in problems), "short row is reported: %r" % problems)
    doc2 = pxa.parse("@palette\n. #00000000 t\n@frame a\n.Z.\n")
    ok(any("not in the palette" in p for p in doc2.validate()), "unknown key reported")


@test
def density_keys_track_luminance():
    doc = sample_doc()
    order = [s.key for s in sorted(doc.opaque_swatches(),
                                   key=lambda s: pxa.luminance(s.rgba))]
    idx = [pxa.DENSITY_KEYS.index(k) for k in order if k in pxa.DENSITY_KEYS]
    eq(idx, sorted(idx), "dark colours get heavy characters")


@test
def png_roundtrip():
    tmp = tempfile.mkdtemp()
    try:
        pixels = [[(255, 0, 0, 255), (0, 255, 0, 128)],
                  [(0, 0, 255, 255), (0, 0, 0, 0)]]
        p = pxa.write_png(os.path.join(tmp, "a.png"), pixels, upscale=3)
        back = pxa.read_png(p)
        eq(len(back), 6, "height scaled")
        eq(len(back[0]), 6, "width scaled")
        eq(back[0][0], (255, 0, 0, 255), "top-left pixel")
        eq(back[5][5], (0, 0, 0, 0), "transparent pixel")
    finally:
        shutil.rmtree(tmp)


@test
def colour_maths():
    ok(pxa.luminance((0, 0, 0, 255)) < 1, "black is dark")
    ok(pxa.luminance((255, 255, 255, 255)) > 99, "white is light")
    eq(pxa.format_hex(pxa.parse_hex("#abc")), "#aabbcc", "short hex expands")
    eq(pxa.format_hex((1, 2, 3, 0), True), "#01020300", "alpha hex")
    near = pxa.nearest_color((250, 10, 10, 255),
                            [(0, 0, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)])
    eq(near, 1, "nearest colour is the red one")
    ok(pxa.color_distance((0, 0, 0, 255), (0, 0, 0, 255)) == 0, "identical distance is 0")


@test
def ramp_shifts_hue_and_value():
    r = palettes.ramp((177, 62, 83, 255), steps=5, hue_shift=24)
    eq(len(r), 5, "step count")
    lums = [pxa.luminance(c) for c in r]
    ok(all(lums[i] < lums[i + 1] for i in range(4)), "value rises monotonically")
    hues = [pxa.rgb_to_hsl(c)[0] for c in r]
    spread = max(hues) - min(hues)
    ok(spread > 5, "ramp actually shifts hue (got %.1f deg)" % spread)


@test
def palette_extraction_and_snapping():
    px = [[(255, 0, 0, 255)] * 8 + [(0, 0, 255, 255)] * 8 for _ in range(8)]
    pal = palettes.extract(px, 2)
    eq(len(pal), 2, "two clusters found")
    snapped = palettes.snap_pixels(px, pal)
    eq(len(set(tuple(p) for row in snapped for p in row)), 2, "snapped to two colours")
    dithered = palettes.snap_pixels(px, pal, dither="bayer4")
    eq(imaging.size_of(dithered), (16, 8), "dither preserves size")


@test
def bundled_palettes_parse():
    names = palettes.bundled_names()
    ok(len(names) >= 10, "palettes are bundled (%d)" % len(names))
    for n in names:
        cols = palettes.load_palette(n)
        ok(len(cols) >= 4, "%s has colours" % n)
        for c in cols:
            eq(len(c), 4, "%s colour is rgba" % n)


@test
def canvas_operations():
    doc = sample_doc()
    f = doc.frame()
    k = [s.key for s in doc.opaque_swatches()]
    canvas.rect(f, 2, 2, 6, 6, k[2], fill=True)
    eq(f.get(4, 4), k[2], "rect filled")
    canvas.flood_fill(f, 4, 4, k[3])
    eq(f.get(4, 4), k[3], "flood fill replaced it")
    canvas.mirror(f, axis="x", source="left")
    eq(f.rows[4], f.rows[4][::-1], "mirror is symmetric")
    before = f.counts().get(k[3], 0)
    canvas.shift(f, 1, 0, empty=".")
    ok(f.counts().get(k[3], 0) <= before, "shift moved content")
    canvas.crop_to_content(doc, f)
    ok(f.width < 16, "crop shrank the canvas")


@test
def lint_finds_orphans_and_jaggies():
    doc = sample_doc(12, 12)
    k = [s.key for s in doc.opaque_swatches()]
    f = doc.frame()
    f.set(1, 1, k[4])                       # a lone pixel far from the mass
    canvas.rect(f, 4, 4, 9, 9, k[2], fill=True)
    findings = lintmod.run(doc, animation=False)
    rules = set(x.rule for x in findings)
    ok("orphan-pixel" in rules, "orphan detected: %s" % rules)
    ok("detached-piece" in rules, "the stray island is reported: %s" % rules)

    solid = sample_doc(12, 12)
    sk = [s.key for s in solid.opaque_swatches()]
    canvas.rect(solid.frame(), 2, 2, 9, 9, sk[2], fill=True)
    rules = set(x.rule for x in lintmod.run(solid, animation=False))
    ok("blocky-silhouette" in rules, "a filled rectangle is called out: %s" % rules)


@test
def lint_detects_pillow_shading():
    doc = pxa.blank(20, 20, "pillow")
    for hexv in ("#1a1c2c", "#3b5dc9", "#41a6f6", "#94b0c2", "#f4f4f4"):
        doc.add_swatch(pxa.parse_hex(hexv))
    pxa.assign_keys_by_value(doc)
    ring = [s.key for s in sorted(doc.opaque_swatches(),
                                  key=lambda s: pxa.luminance(s.rgba))]
    f = doc.frame()
    for i, key in enumerate(ring):          # concentric rings = textbook pillow
        canvas.rect(f, 2 + i, 2 + i, 17 - i, 17 - i, key, fill=True)
    findings = lintmod.run(doc, animation=False)
    ok(any(x.rule == "pillow-shading" for x in findings),
       "pillow shading detected: %s" % set(x.rule for x in findings))


@test
def lint_detects_redundant_colours():
    doc = pxa.blank(8, 8, "dupe")
    doc.add_swatch((100, 100, 100, 255), "a")
    doc.add_swatch((101, 101, 101, 255), "b")
    pxa.assign_keys_by_value(doc)
    k = [s.key for s in doc.opaque_swatches()]
    f = doc.frame()
    canvas.rect(f, 1, 1, 3, 6, k[0], fill=True)
    canvas.rect(f, 4, 1, 6, 6, k[1], fill=True)
    findings = lintmod.run(doc, animation=False)
    ok(any(x.rule == "redundant-colour" for x in findings),
       "near-identical colours flagged")


@test
def lint_is_clean_on_reasonable_art():
    path = os.path.join(ROOT, "workspace", "swordsman", "swordsman.pxa")
    if not os.path.exists(path):
        return
    doc = pxa.load(path)
    eq(doc.validate(), [], "the bundled example is a valid document")
    findings = lintmod.run(doc)
    errors = [f for f in findings if f.severity == "error"]
    eq(errors, [], "the bundled example has no errors")


@test
def animation_drift_detects_growth():
    doc = sample_doc(16, 16)
    k = [s.key for s in doc.opaque_swatches()]
    f = doc.frame()
    canvas.rect(f, 5, 6, 10, 15, k[2], fill=True)
    grown = anim.add_frame(doc, "f1", source=doc.frames[0].name)
    canvas.rect(grown, 3, 2, 12, 15, k[2], fill=True)
    findings = anim.drift(doc, anchor="bottom")
    rules = set(x["rule"] for x in findings)
    ok("volume-drift" in rules, "growth detected: %s" % rules)
    ok("height-drift" in rules, "height change detected: %s" % rules)


@test
def animation_drift_accepts_a_real_idle():
    path = os.path.join(ROOT, "workspace", "swordsman", "swordsman.pxa")
    if not os.path.exists(path):
        return
    doc = pxa.load(path)
    ok(len(doc.frames) > 1, "the example is animated")
    eq(anim.drift(doc, anchor="bottom"), [], "a well-built idle does not drift")
    motion = anim.motion_report(doc)
    ok(all(0.001 < m["ratio"] < 0.5 for m in motion),
       "every frame moves a sensible amount: %s" % motion)


@test
def animation_timing():
    doc = sample_doc()
    anim.add_frame(doc, "b")
    doc.meta["fps"] = "10"
    eq(anim.timing(doc), [100, 100], "fps drives timing")
    doc.meta["timing"] = "200,50"
    eq(anim.timing(doc), [200, 50], "explicit timing wins")


@test
def gif_encoder_produces_a_valid_file():
    tmp = tempfile.mkdtemp()
    try:
        frames = [[[0, 1], [1, 0]], [[1, 0], [0, 1]]]
        p = gifwrite.write_gif(os.path.join(tmp, "a.gif"), frames,
                               [(0, 0, 0), (255, 255, 255)], 2, 2,
                               delays_cs=10, transparent_index=0, scale=4)
        data = open(p, "rb").read()
        eq(data[:6], b"GIF89a", "gif header")
        eq(data[-1:], b";", "gif terminator")
        ok(b"NETSCAPE2.0" in data, "loop extension present")
        ok(len(data) > 40, "gif has content")
    finally:
        shutil.rmtree(tmp)


@test
def renderers_produce_images():
    doc = sample_doc()
    k = [s.key for s in doc.opaque_swatches()]
    canvas.ellipse(doc.frame(), 8, 8, 5, 5, k[2], fill=True)
    anim.add_frame(doc, "b", source=doc.frames[0].name)
    sheet = render.review_sheet(doc)
    w, h = imaging.size_of(sheet)
    ok(w > 200 and h > 200, "review sheet has a sensible size: %dx%d" % (w, h))
    strip = render.filmstrip(doc)
    ok(imaging.size_of(strip)[0] > 40, "filmstrip rendered")
    onion = render.onion_sheet(doc, 1)
    ok(imaging.size_of(onion)[0] > 40, "onion sheet rendered")
    val = render.value_view(doc, doc.frame(), 2)
    for row in val:
        for px in row:
            if px[3] == 255 and px != render.PANEL:
                eq(px[0], px[1], "value view is greyscale")
                eq(px[1], px[2], "value view is greyscale")


@test
def export_bundle_writes_everything():
    tmp = tempfile.mkdtemp()
    try:
        doc = sample_doc()
        k = [s.key for s in doc.opaque_swatches()]
        canvas.ellipse(doc.frame(), 8, 8, 4, 5, k[2], fill=True)
        anim.add_frame(doc, "b", source=doc.frames[0].name)
        canvas.shift(doc.frames[1], 1, 0)
        written = exportmod.bundle(doc, tmp, scales=(1, 2))
        names = set(os.path.basename(p) for p in written)
        for expected in ("sample_main.png", "sample.hex", "sample.gpl",
                         "sample_sheet.png", "sample.gif", "sample.lua"):
            ok(expected in names, "%s written (%s)" % (expected, sorted(names)))
        meta = json.load(open(os.path.join(tmp, "sample_sheet.json")))
        eq(len(meta["frames"]), 2, "sheet manifest lists both frames")
        ok(meta["frames"][0]["duration"] > 0, "manifest carries durations")
    finally:
        shutil.rmtree(tmp)


@test
def import_detects_upscaled_pixel_art():
    tmp = tempfile.mkdtemp()
    try:
        small = [[(255, 0, 0, 255) if (x + y) % 2 else (0, 0, 255, 255)
                  for x in range(8)] for y in range(8)]
        big = [[small[y // 6][x // 6] for x in range(48)] for y in range(48)]
        p = pxa.write_png(os.path.join(tmp, "big.png"), big)
        eq(imaging.detect_pixel_scale(big), 6, "scale detected")
        doc = convert.image_to_doc(p, colors=4)
        eq((doc.width, doc.height), (8, 8), "native resolution recovered")
    finally:
        shutil.rmtree(tmp)


@test
def reference_study_reports_useful_numbers():
    tmp = tempfile.mkdtemp()
    try:
        doc = sample_doc(24, 24)
        k = [s.key for s in doc.opaque_swatches()]
        canvas.ellipse(doc.frame(), 12, 12, 8, 9, k[2], fill=True)
        canvas.ellipse(doc.frame(), 10, 9, 4, 4, k[4], fill=True)
        p = pxa.write_png(os.path.join(tmp, "ref.png"),
                          render.render_frame(doc, doc.frame(), 4))
        r = refstudy.study(p, colors=6)
        eq(r["pixel_scale"], 4, "upscale detected")
        eq(r["native_size"], "24x24", "native size")
        ok(len(r["palette"]) >= 2, "palette extracted")
        ok(r["value_range"][1] > r["value_range"][0], "value range measured")
        b = refstudy.brief([r])
        ok(b["suggested_canvas"], "canvas suggested")
        sheet = refstudy.contact_sheet([r], os.path.join(tmp, "contact.png"))
        ok(os.path.getsize(sheet) > 100, "contact sheet written")
    finally:
        shutil.rmtree(tmp)


@test
def cli_runs_end_to_end():
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        px = os.path.join(ROOT, "bin", "px")
        f = os.path.join(tmp, "t.pxa")
        def run(*args):
            r = subprocess.run([px] + list(args), capture_output=True, text=True)
            ok(r.returncode == 0, "px %s failed: %s%s" % (args[0], r.stdout, r.stderr))
            return r.stdout
        run("new", f, "--size", "16x16", "--palette", "pico-8")
        run("edit", f, "ellipse", "-x", "8", "-y", "8", "--x2", "5", "--y2", "5",
            "--key", "@", "--fill")
        run("anim", "add", f, "b", "--copy-from", "main")
        run("edit", f, "shift", "-x", "1", "--frame", "b")
        out = run("lint", f, "--json")
        json.loads(out)
        run("view", f)
        run("strip", f)
        run("onion", f, "--frame", "b")
        run("snapshot", f, "--stage", "test")
        run("export", f, "--out", os.path.join(tmp, "out"))
        run("grid", f, "--palette")
        run("doctor")
        ok(os.path.exists(os.path.join(tmp, "history")), "snapshot wrote history/")
        ok(os.path.exists(os.path.join(tmp, "out", "t.gif")), "gif exported")
    finally:
        shutil.rmtree(tmp)


@test
def skill_files_are_present_and_sane():
    skill = os.path.join(ROOT, ".agents", "skills", "pixel-art")
    md = open(os.path.join(skill, "SKILL.md")).read()
    ok(md.startswith("---"), "SKILL.md has frontmatter")
    head = md.split("---")[1]
    ok("name: pixel-art" in head, "name matches the directory")
    ok("description:" in head, "description present")
    desc = [l for l in head.splitlines() if l.startswith("description:")][0]
    ok(len(desc) < 1024, "description within the 1024-char limit")
    ok(len(md) < 24000, "SKILL.md stays under the progressive-disclosure budget")
    for ref in ("craft", "colour", "animation", "format", "workflow", "troubleshooting"):
        ok(os.path.exists(os.path.join(skill, "references", "%s.md" % ref)),
           "references/%s.md exists" % ref)
    ok(os.path.islink(os.path.join(ROOT, "CLAUDE.md")), "CLAUDE.md is a symlink")
    ok(os.path.islink(os.path.join(ROOT, ".claude", "skills")),
       ".claude/skills is a symlink")
    eq(os.path.realpath(os.path.join(ROOT, ".claude", "skills")),
       os.path.realpath(os.path.join(ROOT, ".agents", "skills")),
       ".claude/skills resolves to .agents/skills")


def main():
    failures = []
    for fn in RESULTS:
        name = fn.__name__
        try:
            fn()
            sys.stdout.write("  ok    %s\n" % name)
        except Exception as exc:
            failures.append((name, exc, traceback.format_exc()))
            sys.stdout.write("  FAIL  %s -- %s\n" % (name, exc))
    print("")
    if failures:
        for name, exc, tb in failures:
            print("=" * 60)
            print(name)
            print(tb)
        print("%d of %d tests failed" % (len(failures), len(RESULTS)))
        return 1
    print("%d tests passed" % len(RESULTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
