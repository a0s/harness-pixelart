#!/usr/bin/env python3
"""Smoke and behaviour tests for the pixel-art toolchain.

Run: python3 tests/run_tests.py
No dependencies. Exits non-zero on the first failure summary.
"""

import os
import io
import re
import math
import sys
import json
import random
import shutil
import struct
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
import brief as briefmod
import scene as scenemod
import studio as studiomod

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


def gif_delays_cs(path):
    """-> the per-frame delay (centiseconds) of every Graphic Control
    Extension in a GIF file, in frame order -- reads back what
    `gifwrite.write_gif` actually wrote, independent of the encoder."""
    with open(path, "rb") as fh:
        data = fh.read()
    delays, i, marker = [], 0, b"\x21\xF9\x04"
    while True:
        i = data.find(marker, i)
        if i < 0:
            break
        delays.append(struct.unpack("<H", data[i + 4:i + 6])[0])
        i += 1
    return delays


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
def lint_blocky_silhouette_skips_structure_and_machine_stage_docs():
    """A scene's full-bleed ground plane legitimately fills its bounding box --
    the rule is about a character silhouette, so it must not fire on a doc
    whose `@meta scene:` marks it as a structure render, nor on one still at a
    machine-rendered stage (before craft rules even apply)."""
    def solid_doc():
        doc = sample_doc(12, 12)
        sk = [s.key for s in doc.opaque_swatches()]
        canvas.rect(doc.frame(), 2, 2, 9, 9, sk[2], fill=True)
        return doc

    plain = solid_doc()
    ok("blocky-silhouette" in set(x.rule for x in lintmod.run(plain, animation=False)),
       "control: a filled rectangle with no scene/stage meta is still called out")

    has_scene = solid_doc()
    has_scene.meta["scene"] = "keep.scene"
    rules = set(x.rule for x in lintmod.run(has_scene, animation=False))
    ok("blocky-silhouette" not in rules, "a doc with @meta scene: is skipped: %s" % rules)

    massing = solid_doc()
    massing.meta["stage"] = "massing"
    rules = set(x.rule for x in lintmod.run(massing, animation=False))
    ok("blocky-silhouette" not in rules, "a massing-stage doc is skipped: %s" % rules)


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
def gif_export_keeps_varied_timing_unless_fps_is_forced():
    """`--fps` on a GIF export used to silently flatten a hand-tuned
    `timing:` rhythm to a uniform rate. It must now be opt-in: a varied
    timing wins over `fps` unless `force_fps` says otherwise, a uniform or
    absent timing takes `fps` same as always, and `anim.timing_conflict`
    reports the clash so a caller can warn about it."""
    tmp = tempfile.mkdtemp()
    try:
        doc = sample_doc()
        anim.add_frame(doc, "b")
        anim.add_frame(doc, "c")
        doc.meta["timing"] = "220,170,160"

        conflict = anim.timing_conflict(doc, 6)
        eq(conflict, [220, 170, 160], "a varied timing conflicts with an explicit fps")
        eq(anim.timing_conflict(doc, None), None, "no fps, no conflict")

        kept = os.path.join(tmp, "kept.gif")
        anim.to_gif(doc, kept, fps=6)
        eq(gif_delays_cs(kept), [22, 17, 16],
           "fps is ignored by default -- the varied timing survives the export")

        forced = os.path.join(tmp, "forced.gif")
        anim.to_gif(doc, forced, fps=6, force_fps=True)
        eq(gif_delays_cs(forced), [17, 17, 17],
           "force_fps takes the flat rate over the varied timing")

        # a uniform timing has nothing to lose -- fps applies same as ever,
        # with nothing to warn about
        doc.meta["timing"] = "100,100,100"
        eq(anim.timing_conflict(doc, 6), None, "a uniform timing is not a conflict")
        uniform = os.path.join(tmp, "uniform.gif")
        anim.to_gif(doc, uniform, fps=6)
        eq(gif_delays_cs(uniform), [17, 17, 17], "a uniform timing still takes --fps")
    finally:
        shutil.rmtree(tmp)


@test
def export_cli_warns_before_an_fps_override_and_force_fps_silences_it():
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        px = os.path.join(ROOT, "bin", "px")
        f = os.path.join(tmp, "t.pxa")
        subprocess.run([px, "new", f, "--size", "8x8"], check=True, capture_output=True)
        subprocess.run([px, "anim", "add", f, "b", "--copy-from", "main"],
                       check=True, capture_output=True)
        subprocess.run([px, "anim", "timing", f, "--ms", "220,170"],
                       check=True, capture_output=True)

        r = subprocess.run([px, "export", f, "--out", os.path.join(tmp, "out"), "--fps", "6"],
                           capture_output=True, text=True)
        ok(r.returncode == 0, "export failed: %s%s" % (r.stdout, r.stderr))
        ok("note: --fps 6 overrides this sprite's per-frame timing (220,170 ms)" in r.stdout,
           "the override note is printed: %s" % r.stdout)
        eq(gif_delays_cs(os.path.join(tmp, "out", "t.gif")), [22, 17],
           "the exported GIF kept the sprite's own timing")

        r2 = subprocess.run([px, "export", f, "--out", os.path.join(tmp, "out2"),
                            "--fps", "6", "--force-fps"], capture_output=True, text=True)
        ok(r2.returncode == 0, "export --force-fps failed: %s%s" % (r2.stdout, r2.stderr))
        ok("note:" not in r2.stdout, "no note when --force-fps is given: %s" % r2.stdout)
        eq(gif_delays_cs(os.path.join(tmp, "out2", "t.gif")), [17, 17],
           "--force-fps flattens the GIF to the requested rate")
    finally:
        shutil.rmtree(tmp)


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
def reference_study_scale_override_forces_native_size():
    # a reference whose native pixel grid was smoothed away by resampling
    # cannot be auto-detected -- `scale=` is the manual escape hatch
    tmp = tempfile.mkdtemp()
    try:
        doc = sample_doc(24, 24)
        k = [s.key for s in doc.opaque_swatches()]
        canvas.ellipse(doc.frame(), 12, 12, 8, 9, k[2], fill=True)
        p = pxa.write_png(os.path.join(tmp, "ref.png"),
                          render.render_frame(doc, doc.frame(), 3))
        r = refstudy.study(p, scale=3)
        eq(r["native_size"], "24x24", "native size is file size / the forced scale")
        eq(r["pixel_scale"], 3, "reported scale matches the override")
        eq(r["scale_method"], "override", "method records the override")
    finally:
        shutil.rmtree(tmp)


@test
def reference_study_flags_unconfident_scale_and_the_brief_floor_skips_it():
    """When scale detection fails on a big, colour-dense image, `subject_size`
    and `suggested_canvas` are still computed but are not trustworthy -- the
    study must say so (`scale_confident: False`), and a brief merged from it
    must mark its floor unconfident too so `px brief` knows not to gate on it."""
    tmp = tempfile.mkdtemp()
    try:
        # a clean, cleanly-upscaled reference: confident
        doc = sample_doc(24, 24)
        k = [s.key for s in doc.opaque_swatches()]
        canvas.ellipse(doc.frame(), 12, 12, 8, 9, k[2], fill=True)
        clean_path = pxa.write_png(os.path.join(tmp, "clean.png"),
                                   render.render_frame(doc, doc.frame(), 4))
        clean = refstudy.study(clean_path, colors=6)
        ok(clean["scale_confident"], "a cleanly-detected scale is confident: %s" % clean)

        # a big, noisy, colour-dense image: scale detection gives up
        random.seed(1)
        noisy_px = [[(random.randrange(256), random.randrange(256), random.randrange(256), 255)
                    for x in range(320)] for y in range(320)]
        noisy_path = pxa.write_png(os.path.join(tmp, "noisy.png"), noisy_px)
        noisy = refstudy.study(noisy_path)
        eq(noisy["scale_method"], "none", "scale detection fails on noise")
        ok(not noisy["scale_confident"], "an undetected scale is flagged unconfident: %s" % noisy)

        b_clean = refstudy.brief([clean])
        ok(b_clean["floor_confident"], "a brief built only from confident studies is confident")

        # the brief's floor is the SMALLEST suggested canvas across all
        # references (see refstudy.brief) -- build two minimal fake reports so
        # the unconfident one is deliberately the smaller, and check that
        # brief() reads floor_confident off of *that* one, not the other.
        def fake_report(canvas, confident):
            return {"path": "%s.png" % canvas, "palette_rgba": [], "hue_shift_deg": 0.0,
                    "dither_density": 0.0, "value_range": [0, 100], "native_size": "1x1",
                    "suggested_canvas": canvas, "outline": "", "scale_confident": confident}

        small_unconfident = fake_report("40x40", False)
        large_confident = fake_report("200x200", True)
        b = refstudy.brief([small_unconfident, large_confident])
        eq(b["minimum_canvas"], "40x40", "the floor is the smaller of the two canvases")
        ok(not b["floor_confident"],
           "the floor came from the unconfident report, so the brief is unconfident too: %s" % b)

        # swap which one is smaller: now the floor is confident
        b2 = refstudy.brief([fake_report("40x40", True), fake_report("200x200", False)])
        ok(b2["floor_confident"],
           "a floor set by a confident report stays confident even with an "
           "unconfident report alongside it: %s" % b2)
    finally:
        shutil.rmtree(tmp)


@test
def ref_cli_prints_and_writes_the_scale_confidence_flag():
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        px = os.path.join(ROOT, "bin", "px")
        random.seed(2)
        noisy_px = [[(random.randrange(256), random.randrange(256), random.randrange(256), 255)
                    for x in range(320)] for y in range(320)]
        noisy_path = pxa.write_png(os.path.join(tmp, "noisy.png"), noisy_px)
        r = subprocess.run([px, "ref", noisy_path, "--out", tmp], capture_output=True, text=True)
        ok(r.returncode == 0, "px ref failed: %s%s" % (r.stdout, r.stderr))
        ok("(unverified -- scale unknown)" in r.stdout,
           "an unconfident study's subject/canvas line is caveated: %s" % r.stdout)
        with open(os.path.join(tmp, "ref_study.json")) as fh:
            data = json.load(fh)
        ok(data["references"][0]["scale_confident"] is False,
           "scale_confident: false is written to ref_study.json")
        ok(data["brief"]["floor_confident"] is False,
           "floor_confident: false is written to the merged brief block")
    finally:
        shutil.rmtree(tmp)


@test
def ref_default_out_lands_in_the_project_root_not_inside_refs():
    """`px ref workspace/proj/refs/x.png` with no `--out` used to drop a
    second ref_contact.png/ref_study.json into refs/, shadowing the
    project-level pair `px brief`'s canvas gate actually reads. When every
    input lives under a `refs/` directory the default must be that
    directory's parent (the project root) instead."""
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        px = os.path.join(ROOT, "bin", "px")
        proj = os.path.join(tmp, "castle")
        refs = os.path.join(proj, "refs")
        os.makedirs(refs)
        doc = sample_doc(16, 16)
        img_path = pxa.write_png(os.path.join(refs, "castle.png"),
                                 render.render_frame(doc, doc.frame(), 2))

        r = subprocess.run([px, "ref", img_path], capture_output=True, text=True)
        ok(r.returncode == 0, "px ref failed: %s%s" % (r.stdout, r.stderr))
        ok(("writing to %s" % proj) in r.stdout, "destination is printed: %s" % r.stdout)
        ok(os.path.exists(os.path.join(proj, "ref_study.json")),
           "ref_study.json lands in the project root, next to brief.md")
        ok(not os.path.exists(os.path.join(refs, "ref_study.json")),
           "ref_study.json does not shadow the project pair inside refs/")

        # a loose image with no refs/ ancestor keeps today's behaviour: its
        # own directory
        loose_dir = os.path.join(tmp, "loose")
        os.makedirs(loose_dir)
        loose_path = pxa.write_png(os.path.join(loose_dir, "x.png"),
                                   render.render_frame(doc, doc.frame(), 2))
        r2 = subprocess.run([px, "ref", loose_path], capture_output=True, text=True)
        ok(r2.returncode == 0, "px ref failed: %s%s" % (r2.stdout, r2.stderr))
        ok(os.path.exists(os.path.join(loose_dir, "ref_study.json")),
           "a non-refs/ input still defaults to its own directory")
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


@test
def pixel_scale_edge_period_recovers_jpeg_upscales():
    # a clean nearest-neighbour upscale is found by the strict block test
    small = [[(40 + (x * 17 + y * 29) % 180, 60 + (x * 11 + y * 5) % 160,
              90 + (x * 7 + y * 13) % 140, 255) for x in range(24)] for y in range(24)]
    s = 3
    clean = [[small[y // s][x // s] for x in range(24 * s)] for y in range(24 * s)]
    rep = imaging.detect_pixel_scale_report(clean)
    eq(rep["scale"], 3, "clean upscale: scale")
    eq(rep["method"], "exact", "clean upscale: method")

    # the same upscale with a little per-pixel noise (simulating JPEG re-encode)
    # breaks the strict test but should still be found by the tolerant pass
    rnd = random.Random(3)
    noisy = []
    for y in range(24 * s):
        row = []
        for x in range(24 * s):
            r, g, b, a = small[y // s][x // s]
            row.append((max(0, min(255, r + rnd.randint(-4, 4))),
                       max(0, min(255, g + rnd.randint(-4, 4))),
                       max(0, min(255, b + rnd.randint(-4, 4))), a))
        noisy.append(row)
    rep = imaging.detect_pixel_scale_report(noisy)
    eq(rep["scale"], 3, "noisy upscale: scale recovered")
    eq(rep["method"], "edge-period", "noisy upscale: tolerant pass used")

    # random per-pixel noise carries no periodic structure at all
    rnd2 = random.Random(9)
    noise_img = [[(rnd2.randint(0, 255), rnd2.randint(0, 255), rnd2.randint(0, 255), 255)
                 for _x in range(80)] for _y in range(80)]
    eq(imaging.detect_pixel_scale(noise_img), 1, "pure noise: no scale detected")


@test
def projection_classifies_iso_diamond_and_rectangle():
    # a filled 2:1 isometric diamond (a floor-tile outline)
    doc = pxa.blank(64, 64, "iso")
    doc.add_swatch((20, 20, 30, 255), "ink")
    k = doc.opaque_swatches()[0].key
    f = doc.frame()
    cx, cy, hx, hy = 32, 32, 28, 14
    for y in range(64):
        dy = abs(y - cy)
        if dy > hy:
            continue
        dx = int(round(hx * (1 - dy / float(hy))))
        for x in range(max(0, cx - dx), min(64, cx + dx + 1)):
            f.set(x, y, k)
    peaks = refstudy.edge_orientation_peaks(pxa.frame_to_pixels(doc, f))
    ok("isometric 2:1" in refstudy.classify_projection(peaks),
       "diamond classifies as isometric 2:1: %r" % (peaks,))

    # an axis-aligned rectangle outline
    doc2 = pxa.blank(64, 64, "rect")
    doc2.add_swatch((20, 20, 30, 255), "ink")
    k2 = doc2.opaque_swatches()[0].key
    f2 = doc2.frame()
    canvas.rect(f2, 8, 8, 55, 55, k2, fill=False)
    peaks2 = refstudy.edge_orientation_peaks(pxa.frame_to_pixels(doc2, f2))
    ok("axis-aligned" in refstudy.classify_projection(peaks2),
       "rectangle classifies as axis-aligned: %r" % (peaks2,))


@test
def projection_classifies_a_noisy_real_like_roofed_rectangle():
    # a boxy rectangle with a thick 35deg roof band and a little fixed-seed
    # 1px noise -- meant to stand in for a real, painterly reference where
    # nothing is perfectly clean but the walls still dominate the roof.
    import math
    doc = pxa.blank(80, 64, "roofrect")
    doc.add_swatch((20, 20, 30, 255), "ink")
    k = doc.opaque_swatches()[0].key
    f = doc.frame()
    canvas.rect(f, 12, 34, 68, 60, k, fill=False)
    ang = math.radians(35)
    x0, y0, run = 10, 32, 46
    dx = int(round(run * math.cos(ang)))
    dy = int(round(run * math.sin(ang)))
    for off in (-1, 0, 1):                      # a few pixels thick, not a bare Bresenham hair
        canvas.line(f, x0, y0 + off, x0 + dx, y0 - dy + off, k)
    rnd = random.Random(11)
    for _ in range(15):
        f.set(rnd.randrange(80), rnd.randrange(64), k)
    peaks = refstudy.edge_orientation_peaks(pxa.frame_to_pixels(doc, f))
    guess = refstudy.classify_projection(peaks)
    ok(guess.startswith("axis-aligned"), "roofed rectangle reads as axis-aligned: %r (%r)" % (guess, peaks))
    ok("roof pitch" in guess, "a roof pitch note is attached: %r" % (guess,))


@test
def subject_bbox_finds_the_sprite_on_flat_and_checker_backgrounds():
    w, h = 40, 30
    bg = (200, 200, 200, 255)
    flat = [[bg] * w for _ in range(h)]
    for y in range(8, 21):
        for x in range(10, 26):
            flat[y][x] = (220, 40, 40, 255)
    eq(refstudy.subject_bbox(flat), (10, 8, 16, 13), "flat background bbox")

    g1, g2 = (230, 230, 230, 255), (210, 210, 210, 255)
    cw, ch = 48, 48
    checker = [[g1 if ((x // 4) + (y // 4)) % 2 == 0 else g2 for x in range(cw)] for y in range(ch)]
    for y in range(15, 33):
        for x in range(12, 30):
            checker[y][x] = (40, 90, 200, 255)
    eq(refstudy.subject_bbox(checker), (12, 15, 18, 18), "grey-checker background bbox")


@test
def brief_gate_accepts_valid_and_rejects_broken_headers():
    tmp = tempfile.mkdtemp()
    try:
        def write(text):
            p = os.path.join(tmp, "brief.md")
            with open(p, "w") as fh:
                fh.write(text)
            return p

        valid = """---
class: character
view: 3/4-topdown k=0.5
canvas: 64x64
palette: sweetie-16
light: top-left
outline: dark keyline
dither: none
---

## Subject
A test subject.
"""
        write(valid)
        header, problems, _notes = briefmod.validate(tmp)
        eq(problems, [], "a filled-in header validates clean")
        eq(briefmod.pipeline_for(header), "character", "class -> pipeline")

        write(valid.replace("class: character\n", ""))
        _, problems, _notes = briefmod.validate(tmp)
        ok(any("missing key: class" in p for p in problems), "missing key reported: %s" % problems)

        write(valid.replace("class: character", "class: vehicle"))
        _, problems, _notes = briefmod.validate(tmp)
        ok(any("class" in p for p in problems), "bad class value reported: %s" % problems)

        write(valid.replace("view: 3/4-topdown k=0.5", "view: 3/4-topdown"))
        _, problems, _notes = briefmod.validate(tmp)
        ok(any("3/4-topdown" in p for p in problems), "missing k= parameter reported: %s" % problems)

        write(valid.replace("canvas: 64x64", "canvas: 640x64"))
        _, problems, _notes = briefmod.validate(tmp)
        ok(any("canvas" in p for p in problems), "out-of-range canvas reported: %s" % problems)

        write(valid.replace("light: top-left", "light: everywhere"))
        _, problems, _notes = briefmod.validate(tmp)
        ok(any("light" in p for p in problems), "unknown light direction reported: %s" % problems)

        # canvas smaller than the reference subject's suggested canvas
        with open(os.path.join(tmp, "ref_study.json"), "w") as fh:
            json.dump({"references": [], "brief": {"suggested_canvas": "96x96"}}, fh)
        write(valid)
        _, problems, _notes = briefmod.validate(tmp)
        ok(any("smaller than the smallest reference subject" in p for p in problems),
           "small canvas vs ref_study.json reported: %s" % problems)

        write(valid.rstrip("\n") + "\n")  # (unchanged) sanity re-check still fails
        _, problems, _notes = briefmod.validate(tmp)
        ok(problems, "still invalid before the override")

        write(valid.replace("dither: none\n---", "dither: none\ncanvas-override: intentional icon size\n---"))
        _, problems, _notes = briefmod.validate(tmp)
        eq(problems, [], "canvas-override accepted: %s" % problems)
    finally:
        shutil.rmtree(tmp)


@test
def brief_gate_skips_a_canvas_floor_from_an_unconfident_reference_study():
    """A `scale_method: none` reference study means `px ref` never actually
    found a clean pixel grid -- `subject_size`/`suggested_canvas` are guesses,
    so a brief's canvas gate must not enforce them, and should say so instead
    of silently passing or failing."""
    tmp = tempfile.mkdtemp()

    def write(text):
        with open(os.path.join(tmp, "brief.md"), "w") as fh:
            fh.write(text)

    try:
        valid = """---
class: character
view: side
canvas: 32x32
palette: sweetie-16
light: top-left
outline: dark keyline
dither: none
---

## Subject
A test subject.
"""
        # a confident study still gates normally
        with open(os.path.join(tmp, "ref_study.json"), "w") as fh:
            json.dump({"references": [], "brief": {"minimum_canvas": "96x96",
                                                    "floor_confident": True}}, fh)
        write(valid)
        _, problems, notes = briefmod.validate(tmp)
        ok(any("smaller than the smallest reference subject" in p for p in problems),
           "a confident floor still gates: %s" % problems)
        eq(notes, [], "no skip note when the floor is confident")

        # an unconfident study (scale detection failed) must not gate --
        # instead it should explain why not
        with open(os.path.join(tmp, "ref_study.json"), "w") as fh:
            json.dump({"references": [], "brief": {"minimum_canvas": "96x96",
                                                    "floor_confident": False}}, fh)
        _, problems, notes = briefmod.validate(tmp)
        eq(problems, [], "an unconfident floor does not gate: %s" % problems)
        ok(any("scale" in n and "96x96" in n for n in notes),
           "a note explains the gate was skipped and tells the model to verify by eye: %s" % notes)
    finally:
        shutil.rmtree(tmp)


SCENE_BOX = """
@scene
name: test
view: %(view)s
k: %(k)s
unit: %(unit)s
light: %(light)s
%(extra)s

@materials
wall #d7c996
grass #8e8b2e

@objects
%(objects)s
"""


@test
def scene_parse_errors_carry_line_numbers():
    try:
        scenemod.parse("@scene\nname: x\nview: topdown\nunit: nope\n", base_dir=".")
        ok(False, "bad unit: should have raised")
    except scenemod.SceneError as exc:
        eq(exc.line, 4, "the bad line is reported")

    try:
        scenemod.parse("@scene\nname: x\n\n@objects\nsphere s at=0,0,0\n", base_dir=".")
        ok(False, "unknown object type should have raised")
    except scenemod.SceneError as exc:
        ok("unknown object type" in exc.message, "message names the problem: %s" % exc.message)
        eq(exc.line, 5, "unknown-type line is reported")


@test
def scene_topdown_box_faces_and_tones():
    sc = scenemod.parse(SCENE_BOX % {
        "view": "topdown", "k": 0.5, "unit": 4, "light": "top-left", "extra": "",
        "objects": "box body at=0,0,0 size=4,4,4 mat=wall",
    }, base_dir=".")
    r = scenemod.render(sc)
    faces = dict((f["face"], f) for f in r.faces)
    eq(set(faces), {"top", "front"}, "only top and front are visible in topdown")
    top, front = faces["top"], faces["front"]
    tx0, ty0, tx1, ty1 = top["bbox"]
    eq((tx1 - tx0 + 1, ty1 - ty0 + 1), (16, 8), "top face is 4*4 wide by 4*4*0.5 tall")
    fx0, fy0, fx1, fy1 = front["bbox"]
    eq((fx1 - fx0 + 1, fy1 - fy0 + 1), (16, 16), "front face is 16x16")
    eq(ty1 + 1, fy0, "the top face sits directly above the front face")
    eq(top["tone"], "light", "top-left light: top is lit")
    eq(front["tone"], "base", "top-left light: front is the base tone")


@test
def scene_iso_box_three_faces():
    sc = scenemod.parse(SCENE_BOX % {
        "view": "iso", "k": 0.5, "unit": 4, "light": "top-left", "extra": "",
        "objects": "box body at=0,0,0 size=4,4,4 mat=wall",
    }, base_dir=".")
    r = scenemod.render(sc)
    faces = dict((f["face"], f) for f in r.faces)
    eq(set(faces), {"top", "front", "right"}, "iso shows top, front and right")
    xs = [x for f in r.faces for x in (f["bbox"][0], f["bbox"][2])]
    eq(max(xs) - min(xs) + 1, (4 + 4) * 4, "silhouette is (sx+sy)*unit wide")
    ok(pxa.luminance(sc.materials["wall"].base) >= 0, "sanity: material colour parsed")
    ramp = scenemod._material_ramp(sc, "wall")
    front_lum = pxa.luminance(ramp[scenemod.TONE_IDX[faces["front"]["tone"]]])
    right_lum = pxa.luminance(ramp[scenemod.TONE_IDX[faces["right"]["tone"]]])
    ok(right_lum < front_lum, "the right face reads darker than the front for top-left light")


@test
def scene_gable_ridge_x_topdown_visible_set():
    sc = scenemod.parse(SCENE_BOX % {
        "view": "topdown", "k": 0.5, "unit": 4, "light": "top-left", "extra": "",
        "objects": "gable roof at=0,0,0 size=8,8,4 mat=wall ridge=x",
    }, base_dir=".")
    r = scenemod.render(sc)
    eq(set(f["face"] for f in r.faces), {"slope-front"},
       "only slope-front is visible: slope-back and both gable ends are edge-on or backfacing")


@test
def scene_cylinder_topdown():
    sc = scenemod.parse(SCENE_BOX % {
        "view": "topdown", "k": 0.5, "unit": 4, "light": "top-left", "extra": "",
        "objects": "cyl tower at=0,0,0 r=3 h=6 mat=wall sides=16",
    }, base_dir=".")
    r = scenemod.render(sc)
    sides = [f for f in r.faces if f["face"].startswith("side")]
    ok(len(sides) >= 5, "at least 5 side faces visible: got %d" % len(sides))
    top = [f for f in r.faces if f["face"] == "top"][0]
    y0, y1 = top["bbox"][1], top["bbox"][3]
    eq(y1 - y0 + 1, round(2 * 3 * 4 * 0.5), "the cap's screen bbox height matches 2*r*unit*k")


@test
def scene_texture_tiling_checker():
    tmp = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmp, "checker.tex"), "w") as fh:
            fh.write("#.\n.#\n")
        text = SCENE_BOX % {
            "view": "topdown", "k": 0.5, "unit": 4, "light": "top-left", "extra": "",
            "objects": "box body at=0,0,0 size=4,4,4 mat=wall",
        }
        text = text.replace("wall #d7c996", "wall #d7c996 texture=checker.tex")
        sc = scenemod.parse(text, base_dir=tmp)
        r = scenemod.render(sc)
        front = [f for f in r.faces if f["face"] == "front"][0]
        x0, y0, x1, y1 = front["bbox"]
        tex = sc.materials["wall"].texture
        ink_key = [s.key for s in r.doc.swatches if s.name == "ink"][0]
        # interior pixels (away from the silhouette outline) must follow the
        # tile the way the renderer samples it: floor(u)=local x, floor(v)=local y
        # for an axis-aligned topdown face where su==sv==unit.
        checked = 0
        for py in range(y0 + 2, y1 - 1):
            for px in range(x0 + 2, x1 - 1):
                lx, ly = px - x0, py - y0
                expect_ink = tex.rows[ly % tex.h][lx % tex.w] == "#"
                is_ink = r.doc.frame().get(px, py) == ink_key
                eq(is_ink, expect_ink, "pixel (%d,%d) texture ink mismatch" % (px, py))
                checked += 1
        ok(checked > 20, "checked a meaningful number of interior pixels (%d)" % checked)
    finally:
        shutil.rmtree(tmp)


@test
def scene_cast_shadow_away_from_light():
    # A real light-space depth pass, not a screen-space heuristic: a box on a
    # ground plane must throw a shadow on the side away from a top-left
    # light, and never on the side facing it.
    sc = scenemod.parse("""
@scene
name: test
view: topdown
k: 0.5
unit: 6
light: top-left
shadow: 1

@materials
wall #d7c996
grass #8e8b2e

@objects
ground yard at=-8,-8,0 size=24,20 mat=grass
box body at=0,0,0 size=6,6,5 mat=wall
""", base_dir=".")
    r = scenemod.render(sc)
    doc = r.doc
    shadow_keys = [s.key for s in doc.swatches if s.name in ("grass-shadow", "grass-dark")]
    ok(shadow_keys, "the cast shadow darkened some grass")
    body_faces = [f for f in r.faces if f["object"] == "body"]
    bx0 = min(f["bbox"][0] for f in body_faces)
    bx1 = max(f["bbox"][2] for f in body_faces)
    xs = [x for y, row in enumerate(doc.frame().rows) for x, c in enumerate(row) if c in shadow_keys]
    ok(any(x > bx1 for x in xs), "at least one shadowed pixel on the side away from the light")
    ok(not any(x < bx0 for x in xs), "no shadowed pixel on the side facing the light")


@test
def scene_eave_shadow_and_shadow_zero():
    # A roof that overhangs a narrower wall below it must darken the wall's
    # top row (real occlusion, via the light-space depth buffer) -- and
    # `shadow: 0` must produce no darkening anywhere.
    def render(shadow):
        sc = scenemod.parse("""
@scene
name: test
view: topdown
k: 0.5
unit: 6
light: top-left
shadow: %d

@materials
wallmat #d7c996
roofmat #4d94a7

@objects
box wall at=0,0,0 size=4,4,6 mat=wallmat
box roof at=-2,-2,6 size=8,8,1 mat=roofmat
""" % shadow, base_dir=".")
        return scenemod.render(sc)

    def wall_row_names(r, offset):
        doc = r.doc
        by_key = dict((s.key, s.name) for s in doc.swatches)
        front = [f for f in r.faces if f["face"] == "front" and f["object"] == "wall"][0]
        x0, y0, x1, y1 = front["bbox"]
        row = y0 + offset if offset >= 0 else y1 + offset
        return set(by_key[c] for c in doc.frame().rows[row][x0 + 1:x1])

    off = render(0)
    eq(wall_row_names(off, 1), {"wallmat"}, "shadow: 0 -- the row under the eave is undarkened")
    eq(wall_row_names(off, -1), {"wallmat"}, "shadow: 0 -- no darkening anywhere on the wall")

    for shadow in (1, 2):
        on = render(shadow)
        eq(wall_row_names(on, 1), {"wallmat-dark"},
           "shadow: %d -- the eave darkens the wall's top row" % shadow)
        eq(wall_row_names(on, -1), {"wallmat"},
           "shadow: %d -- the wall's bottom, far from the eave, is untouched" % shadow)


@test
def scene_outline_modes():
    for mode, expect_ink in (("ink", True), ("none", False)):
        sc = scenemod.parse(SCENE_BOX % {
            "view": "topdown", "k": 0.5, "unit": 4, "light": "top-left",
            "extra": "outline: %s" % mode,
            "objects": "box body at=0,0,0 size=4,4,4 mat=wall",
        }, base_dir=".")
        r = scenemod.render(sc)
        has_ink = any(s.name == "ink" for s in r.doc.swatches)
        eq(has_ink, expect_ink, "outline: %s -> ink present == %s" % (mode, expect_ink))
    # with outline: ink, every opaque pixel touching transparency must be ink
    sc = scenemod.parse(SCENE_BOX % {
        "view": "topdown", "k": 0.5, "unit": 4, "light": "top-left", "extra": "",
        "objects": "box body at=0,0,0 size=4,4,4 mat=wall",
    }, base_dir=".")
    r = scenemod.render(sc)
    doc = r.doc
    t = doc.transparent_key()
    ink_key = [s.key for s in doc.swatches if s.name == "ink"][0]
    f = doc.frame()
    for y in range(f.height):
        for x in range(f.width):
            if f.rows[y][x] == t:
                continue
            touches_bg = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < f.width and 0 <= ny < f.height) or f.get(nx, ny) == t:
                    touches_bg = True
                    break
            if touches_bg:
                eq(f.rows[y][x], ink_key, "silhouette pixel (%d,%d) is ink" % (x, y))


@test
def scene_render_roundtrips_through_pxa():
    sc = scenemod.parse(SCENE_BOX % {
        "view": "topdown", "k": 0.5, "unit": 4, "light": "top-left", "extra": "",
        "objects": "box body at=0,0,0 size=4,4,4 mat=wall",
    }, base_dir=".")
    sc.path = "barn.scene"
    r = scenemod.render(sc)
    text = pxa.serialize(r.doc)
    again = pxa.parse(text)
    eq(again.frames[0].rows, r.doc.frames[0].rows, "the grid survives a save/load round-trip")
    eq(again.validate(), [], "the round-tripped document validates")
    ok(again.meta.get("view", "").startswith("topdown"), "meta view: is present")
    eq(again.meta.get("scene"), "barn.scene", "meta scene: names the source file")
    # assign_keys_by_value was applied: darker colours get heavier characters
    opaque = again.opaque_swatches()
    order = [s.key for s in sorted(opaque, key=lambda s: pxa.luminance(s.rgba))]
    idx = [pxa.DENSITY_KEYS.index(k) for k in order if k in pxa.DENSITY_KEYS]
    eq(idx, sorted(idx), "dark colours got heavy characters")


@test
def scene_thickness_grows_silhouette_and_adds_edges():
    def render(thickness):
        sc = scenemod.parse("""
@scene
name: test
view: iso
unit: 6
light: top-left

@materials
roof #4d94a7

@objects
gable r at=0,0,0 size=8,8,4 mat=roof ridge=y thickness=%s
""" % thickness, base_dir=".")
        return scenemod.render(sc)

    flat = render(0)
    thick = render(0.5)
    ok(not any(f["face"].startswith("edge-") for f in flat.faces),
       "no edge faces at thickness=0")
    ok(any(f["face"].startswith("edge-") for f in thick.faces),
       "thickness=0.5 adds visible edge-* faces: %s" % sorted(f["face"] for f in thick.faces))

    def area(r):
        x0 = min(f["bbox"][0] for f in r.faces); x1 = max(f["bbox"][2] for f in r.faces)
        y0 = min(f["bbox"][1] for f in r.faces); y1 = max(f["bbox"][3] for f in r.faces)
        return (x1 - x0) * (y1 - y0)

    ok(area(thick) > area(flat), "the silhouette grows once the roof has thickness")


@test
def scene_tone_separation():
    sc = scenemod.parse("""
@scene
name: test
view: iso
unit: 6
light: top-left

@materials
wall #d7c996

@objects
box b at=0,0,0 size=4,4,4 mat=wall
""", base_dir=".")
    r = scenemod.render(sc)
    ramp = scenemod._material_ramp(sc, "wall")
    faces = dict((f["face"], f) for f in r.faces)
    eq(set(faces), {"top", "front", "right"}, "iso shows top, front and right")
    lums = dict((name, pxa.luminance(ramp[scenemod.TONE_IDX[faces[name]["tone"]]]))
               for name in faces)
    ok(lums["top"] > lums["front"] > lums["right"],
       "three distinct, correctly ordered values: %s" % lums)
    ok(lums["front"] - lums["right"] > 15, "the split is wide, not a near-miss: %s" % lums)

    # a plane pointed hard away from the light (a roof underside, an eave's
    # soffit) must read darker than a merely unlit wall, not the same tone
    light = scenemod._normalize(scenemod.LIGHT_DIRS["top-left"])
    wall_tone = scenemod._tone_for((0.0, 0.958, 0.287), light)     # a lightly grazed wall
    underside_tone = scenemod._tone_for((0.0, 0.0, -1.0), light)   # straight down, hard-shadowed
    eq(wall_tone, "shadow", "sanity: the example wall lands in the shadow bucket")
    eq(underside_tone, "dark", "sanity: the example underside lands in the dark bucket")
    ok(scenemod.TONE_IDX[underside_tone] < scenemod.TONE_IDX[wall_tone],
       "the underside ramp step is darker than the wall's")
    under_lum = pxa.luminance(ramp[scenemod.TONE_IDX[underside_tone]])
    wall_lum = pxa.luminance(ramp[scenemod.TONE_IDX[wall_tone]])
    ok(under_lum < wall_lum, "and it is actually darker in the built ramp: %.1f vs %.1f"
       % (under_lum, wall_lum))


@test
def scene_texture_jitter_is_deterministic():
    tmp = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmp, "t.tex"), "w") as fh:
            fh.write("-.-.-.-.\n........\n")

        def render(jitter):
            text = """
@scene
name: test
view: topdown
unit: 6
light: top-left

@materials
wall #d7c996 texture=t.tex jitter=%s

@objects
box b at=0,0,0 size=6,4,4 mat=wall
""" % jitter
            sc = scenemod.parse(text, base_dir=tmp)
            return scenemod.render(sc)

        a1, a2 = render(0), render(0)
        eq(a1.doc.frames[0].rows, a2.doc.frames[0].rows, "jitter=0 is a no-op, and repeatable")
        b1, b2 = render(2), render(2)
        eq(b1.doc.frames[0].rows, b2.doc.frames[0].rows,
           "jitter=2 is deterministic across two renders of the same scene")
        ok(a1.doc.frames[0].rows != b1.doc.frames[0].rows,
           "jitter=2 actually changes something versus jitter=0")
    finally:
        shutil.rmtree(tmp)


@test
def scene_camera_view_matches_presets():
    p_topdown = math.degrees(math.atan(0.5))
    ax_td = scenemod.camera_axes(p_topdown, 0.0)
    for got, want in zip(ax_td, ((1.0, 0.0), (0.0, -0.5), (0.0, -1.0))):
        for g, w in zip(got, want):
            ok(abs(g - w) < 1e-3, "camera_axes(pitch, 0) ~= topdown k=0.5: %s vs %s" % (ax_td, want))

    ax_iso = scenemod.camera_axes(p_topdown, 45.0)
    for got, want in zip(ax_iso, ((1.0, 0.5), (1.0, -0.5), (0.0, -1.0))):
        for g, w in zip(got, want):
            ok(abs(g - w) < 1e-3, "camera_axes(pitch, 45) ~= iso: %s vs %s" % (ax_iso, want))

    def render(view, extra):
        text = """
@scene
name: test
view: %s
%s
unit: 6
light: top-left

@materials
wall #d7c996
roof #4d94a7

@objects
ground g at=-3,-3,0 size=14,12 mat=wall
box b at=0,0,0 size=6,5,4 mat=wall
gable r at=-1,-1,4 size=8,7,3 mat=roof ridge=y
""" % (view, extra)
        sc = scenemod.parse(text, base_dir=".")
        return scenemod.render(sc)

    topdown = render("topdown", "k: 0.5")
    camtd = render("camera", "pitch: %s\nyaw: 0" % p_topdown)
    eq(camtd.doc.frames[0].rows, topdown.doc.frames[0].rows,
       "camera(pitch, yaw=0) renders pixel-identical to topdown k=0.5")

    iso = render("iso", "")
    camiso = render("camera", "pitch: %s\nyaw: 45" % p_topdown)
    eq(camiso.doc.frames[0].rows, iso.doc.frames[0].rows,
       "camera(pitch, yaw=45) renders pixel-identical to iso")


@test
def scene_view_meta_records_the_actual_projection_params():
    """A rendered .pxa's `@meta view:` must carry whatever actually determines
    the projection, so it can be reconstructed from the file alone -- for
    `camera` that is pitch/yaw (the source of the foreshortening), not the
    topdown-only `k` the renderer used to write for every view."""
    def render(view, extra):
        text = """
@scene
name: test
view: %s
%s
unit: 6
light: top-left

@materials
wall #d7c996

@objects
box b at=0,0,0 size=6,5,4 mat=wall
""" % (view, extra)
        sc = scenemod.parse(text, base_dir=".")
        return scenemod.render(sc)

    r_cam = render("camera", "pitch: 35.26\nyaw: 12.5")
    view_meta = r_cam.doc.meta["view"]
    ok(view_meta.startswith("camera "), "camera view meta starts with the view kind: %r" % view_meta)
    ok("k=" not in view_meta,
       "camera view no longer carries the misleading topdown k=: %r" % view_meta)
    m_pitch = re.search(r"\bpitch=([-0-9.]+)", view_meta)
    m_yaw = re.search(r"\byaw=([-0-9.]+)", view_meta)
    ok(m_pitch and m_yaw, "camera view records pitch= and yaw=: %r" % view_meta)
    got_axes = scenemod.camera_axes(float(m_pitch.group(1)), float(m_yaw.group(1)))
    want_axes = scenemod.camera_axes(35.26, 12.5)
    eq(got_axes, want_axes,
       "the recorded pitch/yaw round-trip to the same axes as the scene's own camera_axes")

    r_td = render("topdown", "k: 0.5")
    td_meta = r_td.doc.meta["view"]
    ok(td_meta.startswith("topdown "), "topdown view meta starts with the view kind: %r" % td_meta)
    m_k = re.search(r"\bk=([-0-9.]+)", td_meta)
    ok(m_k and abs(float(m_k.group(1)) - 0.5) < 1e-9, "topdown view still records its k: %r" % td_meta)


@test
def scene_dirty_slope_warning():
    def warnings_for(yaw):
        sc = scenemod.parse("""
@scene
name: test
view: camera
pitch: 26.57
yaw: %s
unit: 6
light: top-left

@materials
wall #d7c996

@objects
box b at=0,0,0 size=6,5,4 mat=wall
""" % yaw, base_dir=".")
        return scenemod.render(sc).warnings

    ok(warnings_for(20), "yaw 20 is a dirty slope and warns")
    eq(warnings_for(0), [], "yaw 0 is clean (fronted-on) and stays silent")
    eq(warnings_for(45), [], "yaw 45 is clean (isometric) and stays silent")


@test
def scene_cli_smoke():
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        px = os.path.join(ROOT, "bin", "px")
        scene_file = os.path.join(tmp, "barn.scene")

        def run(*args):
            r = subprocess.run([px] + list(args), capture_output=True, text=True)
            ok(r.returncode == 0, "px %s failed: %s%s" % (list(args), r.stdout, r.stderr))
            return r.stdout

        run("scene", "new", scene_file, "--view", "topdown", "--unit", "6")
        ok(os.path.exists(scene_file), "starter scene written")
        out = run("scene", "render", scene_file)
        ok(os.path.exists(os.path.join(tmp, "barn.pxa")), "scene render wrote the .pxa: %s" % out)
        ok(os.path.exists(os.path.join(tmp, "review", "barn_guide.png")), "guide PNG written")
        out = run("scene", "faces", scene_file)
        ok("OBJECT" in out and "BBOX" in out, "faces table printed: %s" % out)
    finally:
        shutil.rmtree(tmp)




@test
def hash_is_never_handed_out_as_a_palette_key():
    """A swatch keyed '#' writes a palette line that reads back as a comment,
    so the colour vanishes on the next load. The key alphabet must exclude it,
    and files written before that rule must still parse."""
    ok("#" not in pxa.DENSITY_KEYS, "'#' must not be a density key")
    ok("#" not in pxa.KEY_ALPHABET, "'#' must not be in the key alphabet")

    doc = pxa.blank(4, 4, "keys")
    for i in range(len(pxa.DENSITY_KEYS)):
        doc.add_swatch((i * 7 % 256, 30, 40, 255), "c%d" % i)
    pxa.assign_keys_by_value(doc)
    round_trip = pxa.parse(pxa.serialize(doc))
    eq(len(round_trip.swatches), len(doc.swatches), "every swatch survives a round trip")
    for sw in doc.swatches:
        ok(round_trip.swatch(sw.key) is not None, "swatch %r survived" % sw.key)

    legacy = "@meta\nname: old\n\n@palette\n. #00000000 transparent\n# #1a1c2c ink\n\n@frame main\n##\n##\n"
    old = pxa.parse(legacy)
    ok(old.swatch("#") is not None, "a legacy '#'-keyed swatch still parses")
    eq(old.swatch("#").rgba, (26, 28, 44, 255), "legacy ink colour")


# --------------------------------------------------------------------------
# structure lint rules (form-value, form-coverage, iso-slope, plane-drift)
# and the massing-aware review sheet / studio -- lint.STRUCTURE_RULES only
# runs when a painted .pxa's `@meta scene:` resolves against its own path.
# --------------------------------------------------------------------------

SCENE_ISO_BOX = """
@scene
name: test
view: iso
unit: 6
light: top-left

@materials
wall #d7c996

@objects
box body at=0,0,0 size=6,6,6 mat=wall
"""


@test
def structure_lint_form_value_flags_an_inverted_tone_not_a_clean_render():
    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "barn.scene")
        with open(spath, "w") as fh:
            fh.write(SCENE_ISO_BOX)
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        ppath = os.path.join(tmp, "barn.pxa")
        pxa.save(r.doc, ppath)

        clean = pxa.load(ppath)
        findings = lintmod.run(clean, animation=False, path=ppath)
        ok(not any(f.rule == "form-value" for f in findings),
           "a clean scene render does not invert any face's tone order: %s"
           % [f.message for f in findings if f.rule == "form-value"])

        # darken every painted pixel of the (lit) top face below the other faces
        faces = dict((f["face"], f) for f in r.faces)
        top = faces["top"]
        doc2 = pxa.load(ppath)
        dark = doc2.add_swatch((5, 5, 5, 255), "verydark")
        frame = doc2.frame()
        t = doc2.transparent_key()
        x0, y0, x1, y1 = top["bbox"]
        for y in range(y0, y1 + 1):
            row = list(frame.rows[y])
            for x in range(x0, x1 + 1):
                if row[x] != t:
                    row[x] = dark.key
            frame.rows[y] = "".join(row)

        findings2 = lintmod.run(doc2, animation=False, path=ppath)
        fv = [f for f in findings2 if f.rule == "form-value"]
        ok(fv, "darkening the light-toned top face below the others is caught: %s"
           % [f.rule for f in findings2])
        ok("top" in fv[0].message and "light" in fv[0].message,
           "the finding names the face and its massing tone: %s" % fv[0].message)
    finally:
        shutil.rmtree(tmp)


# three boxes at three sizes so their side faces land on three distinct
# painted-pixel areas: sliver's front/right are a handful of pixels (well
# below the 64-px pair-comparison floor), mid's are a few hundred, and body's
# (the tallest box, so its front/right faces are as large as its top) are the
# largest -- both mid's and body's clear the floor, with body's the larger.
SCENE_FORM_VALUE_AREAS = """
@scene
name: test
view: iso
unit: 6
light: top-left

@materials
wall #d7c996

@objects
box mid at=10,0,0 size=6,6,1 mat=wall
box body at=0,0,0 size=6,6,6 mat=wall
box sliver at=20,0,0 size=6,6,0.2 mat=wall
"""


@test
def structure_lint_form_value_ignores_slivers_and_sorts_by_area():
    """A tiny face inverted by one stray inked pixel must not read the same as
    a large face genuinely textured away: both faces of a compared pair now
    need at least 64 painted pixels (up from the 12-px floor that decides
    whether a face is measured at all), and the findings that survive are
    ordered by the smaller face's area, largest first."""
    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "areas.scene")
        with open(spath, "w") as fh:
            fh.write(SCENE_FORM_VALUE_AREAS)
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        ppath = os.path.join(tmp, "areas.pxa")
        pxa.save(r.doc, ppath)

        faces = dict(((f["object"], f["face"]), f) for f in r.faces)

        def darken(doc, obj, face_name):
            f = faces[(obj, face_name)]
            dark = doc.swatch("verydark") or doc.add_swatch((5, 5, 5, 255), "verydark")
            frame = doc.frame()
            t = doc.transparent_key()
            x0, y0, x1, y1 = f["bbox"]
            fid = f["id"]
            for y in range(y0, y1 + 1):
                row = list(frame.rows[y])
                for x in range(x0, x1 + 1):
                    if r.face_id[y][x] == fid and row[x] != t:
                        row[x] = dark.key
                frame.rows[y] = "".join(row)

        # sliver's front/right are far under the pair floor -- inverting its
        # top face against them must stay silent.
        doc_sliver = pxa.load(ppath)
        darken(doc_sliver, "sliver", "top")
        findings = lintmod.run(doc_sliver, animation=False, path=ppath)
        fv = [f for f in findings if f.rule == "form-value"]
        ok(not any("sliver" in f.message for f in fv),
           "a sub-64px face pair is not reported: %s" % [f.message for f in fv])

        # mid's and body's side faces both clear the 64-px floor -- body's
        # (the larger box) pair must sort ahead of mid's, even though mid is
        # declared first in the scene.
        doc_both = pxa.load(ppath)
        darken(doc_both, "mid", "top")
        darken(doc_both, "body", "top")
        findings2 = lintmod.run(doc_both, animation=False, path=ppath)
        fv2 = [f for f in findings2 if f.rule == "form-value"]
        ok(fv2, "the two above-floor inversions are reported: %s" % findings2)
        msg = fv2[0].message
        parts = msg.split("massing tone order: ", 1)[1].split("; ")
        ok(len(parts) == 4 and all(p.startswith("body:") for p in parts[:2])
           and all(p.startswith("mid:") for p in parts[2:]),
           "body's larger-area pairs sort ahead of mid's smaller ones "
           "despite mid being declared first: %s" % msg)
        body_px = [int(n) for n in re.findall(r"(\d+) px", parts[0])]
        mid_px = [int(n) for n in re.findall(r"(\d+) px", parts[2])]
        ok(body_px and mid_px and min(body_px) > 64 and min(mid_px) > 64,
           "each face's painted pixel count is stated, and both clear the floor: %s" % msg)
        ok(min(body_px) > min(mid_px),
           "body's face pair is reported as larger than mid's: %s" % msg)
    finally:
        shutil.rmtree(tmp)


@test
def structure_lint_form_coverage_flags_holes_and_drift_not_a_clean_render():
    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "barn.scene")
        with open(spath, "w") as fh:
            fh.write(SCENE_ISO_BOX)
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        ppath = os.path.join(tmp, "barn.pxa")
        pxa.save(r.doc, ppath)

        clean = pxa.load(ppath)
        findings = lintmod.run(clean, animation=False, path=ppath)
        ok(not any(f.rule == "form-coverage" for f in findings),
           "a clean scene render has no coverage findings: %s"
           % [f.message for f in findings if f.rule == "form-coverage"])

        # punch a hole well past the 6% threshold into the front face
        faces = dict((f["face"], f) for f in r.faces)
        front = faces["front"]
        doc2 = pxa.load(ppath)
        frame = doc2.frame()
        t = doc2.transparent_key()
        x0, y0, x1, y1 = front["bbox"]
        hx0, hy0 = x0 + 1, y0 + 1
        hx1, hy1 = min(x1 - 1, hx0 + 20), min(y1 - 1, hy0 + 20)
        for y in range(hy0, hy1 + 1):
            row = frame.rows[y]
            frame.rows[y] = row[:hx0] + t * (hx1 - hx0 + 1) + row[hx1 + 1:]
        findings_hole = lintmod.run(doc2, animation=False, path=ppath)
        cov = [f for f in findings_hole if f.rule == "form-coverage"]
        ok(cov and "left empty" in cov[0].message,
           "a punched hole is reported: %s" % [f.message for f in cov])

        # paint a blob well past the 10% threshold outside the massing silhouette
        doc3 = pxa.load(ppath)
        frame3 = doc3.frame()
        w, h = frame3.width, frame3.height
        sw = doc3.opaque_swatches()[0]
        for y in range(h):
            row = list(frame3.rows[y])
            for x in range(0, min(22, w)):
                if r.face_id[y][x] < 0:
                    row[x] = sw.key
            frame3.rows[y] = "".join(row)
        findings_drift = lintmod.run(doc3, animation=False, path=ppath)
        drift = [f for f in findings_drift if f.rule == "form-coverage"]
        ok(drift and "drifted" in drift[0].message,
           "paint outside the massing silhouette is reported: %s" % [f.message for f in drift])
    finally:
        shutil.rmtree(tmp)


@test
def structure_lint_iso_slope_flags_a_1to1_staircase_not_the_renderers_2to1():
    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "barn.scene")
        with open(spath, "w") as fh:
            fh.write(SCENE_ISO_BOX)

        # the renderer's own silhouette steps a clean 2 px across per 1 px down
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        ppath = os.path.join(tmp, "barn.pxa")
        pxa.save(r.doc, ppath)
        clean = pxa.load(ppath)
        findings = lintmod.run(clean, animation=False, path=ppath)
        ok(not any(f.rule == "iso-slope" for f in findings),
           "the renderer's own 2:1 diagonal is clean: %s"
           % [f.message for f in findings if f.rule == "iso-slope"])

        # a hand-made 1:1 staircase, tagged to the same iso scene
        doc = pxa.blank(40, 40, "stair")
        doc.add_swatch((200, 200, 200, 255), "wall")
        k = doc.opaque_swatches()[0].key
        f = doc.frame()
        for x in range(20):
            for y in range(x, 30):
                f.set(x, y, k)
        doc.meta["scene"] = "barn.scene"
        doc.meta["view"] = "iso k=0.5 unit=6 origin=0,0"
        stair_path = os.path.join(tmp, "stair.pxa")
        pxa.save(doc, stair_path)
        doc2 = pxa.load(stair_path)
        findings2 = lintmod.run(doc2, animation=False, path=stair_path)
        hits = [f for f in findings2 if f.rule == "iso-slope"]
        ok(hits, "a 1:1 staircase does not hold the isometric 2:1 diagonal: %s"
           % [f.rule for f in findings2])
    finally:
        shutil.rmtree(tmp)


@test
def structure_lint_missing_scene_file_is_one_info_finding_no_crash():
    tmp = tempfile.mkdtemp()
    try:
        doc = pxa.blank(8, 8, "orphan")
        doc.add_swatch((200, 200, 200, 255), "wall")
        k = doc.opaque_swatches()[0].key
        canvas.rect(doc.frame(), 1, 1, 6, 6, k, fill=True)
        doc.meta["scene"] = "missing.scene"
        ppath = os.path.join(tmp, "orphan.pxa")
        pxa.save(doc, ppath)
        doc2 = pxa.load(ppath)
        findings = lintmod.run(doc2, animation=False, path=ppath)
        # STATIC_RULES may or may not have something to say about this tiny
        # synthetic sprite; only the structure group's own finding is under
        # test here, and it must be the one and only thing it produces.
        structure = [f for f in findings if f.rule == "form-check"]
        eq(len(structure), 1,
           "exactly one structure finding for an unresolvable scene: %s" % [f.rule for f in findings])
        eq(structure[0].severity, "info", "the finding is informational, not an error")
        ok("missing.scene" in structure[0].message, "names the missing file: %s" % structure[0].message)
    finally:
        shutil.rmtree(tmp)


@test
def view_sheet_includes_massing_and_form_panels_when_scene_resolves():
    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "barn.scene")
        with open(spath, "w") as fh:
            fh.write(SCENE_ISO_BOX)
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        ppath = os.path.join(tmp, "barn.pxa")
        pxa.save(r.doc, ppath)
        doc = pxa.load(ppath)

        with_scene = render.review_sheet(doc, path=ppath, scene=True)
        without_scene = render.review_sheet(doc, path=ppath, scene=False)
        wa, ha = imaging.size_of(with_scene)
        wb, hb = imaging.size_of(without_scene)
        # the MASSING/FORM panels stack in the existing side column (taller,
        # same width) rather than growing it sideways, so the robust check is
        # total area, not a specific dimension.
        ok(wa * ha > wb * hb,
           "the scene-backed sheet has more area than the same sheet with --no-scene "
           "(%dx%d=%d vs %dx%d=%d)" % (wa, ha, wa * ha, wb, hb, wb * hb))

        # a character sprite (no scene: meta) renders identically either way
        char = pxa.blank(16, 16, "char")
        char.add_swatch((200, 200, 200, 255), "ink")
        canvas.rect(char.frame(), 4, 4, 11, 11, char.opaque_swatches()[0].key, fill=True)
        char_path = os.path.join(tmp, "char.pxa")
        pxa.save(char, char_path)
        with_scene2 = render.review_sheet(char, path=char_path, scene=True)
        without_scene2 = render.review_sheet(char, path=char_path, scene=False)
        eq(imaging.size_of(with_scene2), imaging.size_of(without_scene2),
           "no scene: meta -> the panel toggle is a no-op")
    finally:
        shutil.rmtree(tmp)


@test
def studio_handler_serves_the_page_and_a_massing_render():
    """Exercises studio.Handler.do_GET through BaseHTTPRequestHandler's own
    machinery, with a fake socket standing in for a real one (the same trick
    Python's own http.server tests use) -- no port is ever opened."""
    class _FakeSocket(object):
        def __init__(self, data):
            self._rfile = io.BytesIO(data)
            self._wfile = io.BytesIO()

        def makefile(self, mode, *a, **kw):
            return self._rfile if "r" in mode else self._wfile

        def sendall(self, data):
            self._wfile.write(data)

        def send(self, data):
            self._wfile.write(data)
            return len(data)

        def close(self):
            pass

        def shutdown(self, how):
            pass

    class _FakeServer(object):
        pass

    def do_request(state, raw):
        studiomod.Handler.state = state
        sock = _FakeSocket(raw)
        studiomod.Handler(sock, ("127.0.0.1", 0), _FakeServer())
        return sock._wfile.getvalue()

    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "barn.scene")
        with open(spath, "w") as fh:
            fh.write(SCENE_ISO_BOX)
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        pxa.save(r.doc, os.path.join(tmp, "barn.pxa"))

        state = studiomod.State(tmp)
        state.refresh(force=True)

        resp = do_request(state, b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        eq(resp.split(b"\r\n", 1)[0], b"HTTP/1.1 200 OK", "main page: %r" % resp[:120])

        resp2 = do_request(state, b"GET /render?p=barn.pxa&mode=massing&s=2 HTTP/1.1\r\n"
                                  b"Host: x\r\nConnection: close\r\n\r\n")
        eq(resp2.split(b"\r\n", 1)[0], b"HTTP/1.1 200 OK", "massing render: %r" % resp2[:200])
    finally:
        shutil.rmtree(tmp)


def _norm2(v):
    x, y = v
    l = math.hypot(x, y) or 1.0
    return (x / l, y / l)


@test
def structure_lint_plane_drift_flags_axis_aligned_detail_on_a_slanted_face():
    # a gable roof in iso: the wall faces have a vertical projected tangent
    # (yaw=0-style exemption), the roof slopes do not -- neither of their
    # tangents is horizontal or vertical.
    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "barn.scene")
        with open(spath, "w") as fh:
            fh.write("""
@scene
name: test
view: iso
unit: 8
light: top-left

@materials
wall #d7c996
roof #4d94a7

@objects
box body at=0,0,0 size=8,8,6 mat=wall
gable roof at=-1,-1,6 size=10,10,4 mat=roof ridge=x
""")
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        ppath = os.path.join(tmp, "barn.pxa")
        pxa.save(r.doc, ppath)
        faces = dict((f["face"], f) for f in r.faces)
        slope = faces["slope-front"]
        ok(not lintmod._face_has_axis_tangent(scenemod._axes(sc), slope["normal"]),
           "the roof slope has no axis-aligned tangent -- it is not exempt")
        front_wall = faces["front"]
        ok(lintmod._face_has_axis_tangent(scenemod._axes(sc), front_wall["normal"]),
           "an iso wall has a vertical tangent -- it is exempt")

        # find a window-sized rectangle fully inside the slope face
        fid = slope["id"]
        w, h = r.doc.width, r.doc.height
        mask = [[r.face_id[y][x] == fid for x in range(w)] for y in range(h)]
        x0b, y0b, x1b, y1b = slope["bbox"]
        window = None
        for ty in range(y0b + 5, y1b - 14):
            for tx in range(x0b + 5, x1b - 20):
                if all(mask[ty + dy][tx + dx] for dy in range(14) for dx in range(20)):
                    window = (tx, ty, tx + 19, ty + 13)
                    break
            if window:
                break
        ok(window, "found a spot on the slope to paint a window-sized rectangle")
        tx0, ty0, tx1, ty1 = window

        # 1) an axis-aligned window rectangle on the slope -- fires
        doc = pxa.load(ppath)
        sw = doc.add_swatch((240, 240, 240, 255), "window")
        canvas.rect(doc.frame(), tx0, ty0, tx1, ty1, sw.key, fill=True)
        findings = lintmod.run(doc, animation=False, path=ppath)
        pd = [f for f in findings if f.rule == "plane-drift"]
        ok(pd, "an axis-aligned window on an iso roof slope is caught: %s"
           % [f.rule for f in findings])
        ok("slope-front" in pd[0].message and ("horizontal" in pd[0].message or "vertical" in pd[0].message),
           "message names the face and the axis-aligned edge: %s" % pd[0].message)

        # 2) the same window sheared to follow the face's own e1/e2 tangents -- silent
        axes = scenemod._axes(sc)
        e1n, e2n = _norm2(lintmod._face_screen_tangents(axes, slope["normal"])[0]), \
                   _norm2(lintmod._face_screen_tangents(axes, slope["normal"])[1])
        base = (x0b + (x1b - x0b) * 0.35, y0b + (y1b - y0b) * 0.35)
        doc2 = pxa.load(ppath)
        frame2 = doc2.frame()
        sw2 = doc2.add_swatch((240, 240, 240, 255), "window")
        steps_u, steps_v, U, V = 90, 60, 18.0, 12.0
        for iu in range(steps_u + 1):
            for iv in range(steps_v + 1):
                u, v = U * iu / steps_u, V * iv / steps_v
                px = base[0] + u * e1n[0] + v * e2n[0]
                py = base[1] + u * e1n[1] + v * e2n[1]
                xi, yi = int(round(px)), int(round(py))
                if 0 <= xi < w and 0 <= yi < h and mask[yi][xi]:
                    row = frame2.rows[yi]
                    if row[xi] != sw2.key:
                        frame2.rows[yi] = row[:xi] + sw2.key + row[xi + 1:]
        findings2 = lintmod.run(doc2, animation=False, path=ppath)
        ok(not any(f.rule == "plane-drift" for f in findings2),
           "a window sheared along the face's own tangents is not flagged: %s"
           % [f.message for f in findings2 if f.rule == "plane-drift"])

        # 3) nothing fires on a yaw=0 topdown wall (an axis-aligned tangent face)
        spath2 = os.path.join(tmp, "flat.scene")
        with open(spath2, "w") as fh:
            fh.write("""
@scene
name: flat
view: topdown
k: 0.5
unit: 8
light: top-left

@materials
wall #d7c996

@objects
box body at=0,0,0 size=10,8,6 mat=wall
""")
        sc3 = scenemod.load(spath2)
        r3 = scenemod.render(sc3)
        ppath3 = os.path.join(tmp, "flat.pxa")
        pxa.save(r3.doc, ppath3)
        faces3 = dict((f["face"], f) for f in r3.faces)
        fr = faces3["front"]
        fx0, fy0, fx1, fy1 = fr["bbox"]
        doc3 = pxa.load(ppath3)
        sw3 = doc3.add_swatch((240, 240, 240, 255), "window")
        canvas.rect(doc3.frame(), fx0 + 3, fy0 + 3, fx0 + 15, fy0 + 15, sw3.key, fill=True)
        findings3 = lintmod.run(doc3, animation=False, path=ppath3)
        ok(not any(f.rule == "plane-drift" for f in findings3),
           "a flat, axis-aligned wall never fires: %s"
           % [f.message for f in findings3 if f.rule == "plane-drift"])
    finally:
        shutil.rmtree(tmp)


@test
def structure_lint_downgrades_craft_rules_on_a_machine_rendered_stage():
    tmp = tempfile.mkdtemp()
    try:
        spath = os.path.join(tmp, "barn.scene")
        with open(spath, "w") as fh:
            fh.write(SCENE_ISO_BOX)
        sc = scenemod.load(spath)
        r = scenemod.render(sc)
        ppath = os.path.join(tmp, "barn.pxa")
        pxa.save(r.doc, ppath)
        eq(pxa.load(ppath).meta.get("stage"), "massing", "the renderer stamps stage: massing")

        # punch a hole: a craft-rule finding (jaggies, at least) and a
        # structure finding (form-coverage) both have something to say
        faces = dict((f["face"], f) for f in r.faces)
        front = faces["front"]
        x0, y0, x1, y1 = front["bbox"]
        hx0, hy0 = x0 + 1, y0 + 1
        hx1, hy1 = min(x1 - 1, hx0 + 20), min(y1 - 1, hy0 + 20)

        def _punch(doc):
            frame = doc.frame()
            t = doc.transparent_key()
            for y in range(hy0, hy1 + 1):
                row = frame.rows[y]
                frame.rows[y] = row[:hx0] + t * (hx1 - hx0 + 1) + row[hx1 + 1:]
            return doc

        doc = _punch(pxa.load(ppath))
        findings = lintmod.run(doc, animation=False, path=ppath)
        craft_bad = [f for f in findings if f.rule in lintmod.CRAFT_RULE_NAMES and f.severity != "info"]
        eq(craft_bad, [], "no hand-craft rule reports warn/error on a massing-stage doc: %s"
           % [(f.rule, f.severity) for f in craft_bad])
        downgraded = [f for f in findings if f.rule in lintmod.CRAFT_RULE_NAMES and f.severity == "info"]
        ok(downgraded, "at least one craft rule fired, just muted to info")
        ok(all(f.message.startswith(lintmod.STAGE_DOWNGRADE_PREFIX) for f in downgraded),
           "the downgraded message is prefixed: %s" % [f.message[:40] for f in downgraded])
        structure_warn = [f for f in findings if f.rule == "form-coverage" and f.severity == "warn"]
        ok(structure_warn, "the structure finding (form-coverage) keeps its normal severity: %s"
           % [(f.rule, f.severity) for f in findings])

        # stage: cleanup -> the same findings return to full severity
        doc2 = _punch(pxa.load(ppath))
        doc2.meta["stage"] = "cleanup"
        findings2 = lintmod.run(doc2, animation=False, path=ppath)
        ok(any(f.rule in lintmod.CRAFT_RULE_NAMES and f.severity == "warn" for f in findings2),
           "stage: cleanup gets the craft rules back at normal severity: %s"
           % [(f.rule, f.severity) for f in findings2])

        # --strict (strict=True) restores full severity even at stage: massing
        findings3 = lintmod.run(doc, animation=False, path=ppath, strict=True)
        ok(any(f.rule in lintmod.CRAFT_RULE_NAMES and f.severity == "warn" for f in findings3),
           "strict=True restores full severity on a massing-stage doc: %s"
           % [(f.rule, f.severity) for f in findings3])
        ok(lintmod.stage_note(doc) is not None, "the stage note is present without --strict")
        eq(lintmod.stage_note(doc, strict=True), None, "strict suppresses the stage note")

        # any other stage (or none at all) behaves exactly as today
        doc4 = _punch(pxa.load(ppath))
        doc4.meta.pop("stage", None)
        findings4 = lintmod.run(doc4, animation=False, path=ppath)
        ok(any(f.rule in lintmod.CRAFT_RULE_NAMES and f.severity == "warn" for f in findings4),
           "no stage meta at all -> normal severity: %s" % [(f.rule, f.severity) for f in findings4])
    finally:
        shutil.rmtree(tmp)


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
