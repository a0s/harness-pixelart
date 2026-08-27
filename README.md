# harness_pixelart

A pipeline for making **real pixel art** with an AI agent -- the kind a person
would draw, not a downscaled photo and not a picture assembled out of rectangles.

Give it reference images and a description; get back a craft-checked sprite or
animation, its text source, and game-ready exports.

Works identically in **Claude Code** and **Codex CLI** (and anything else that
reads the [Agent Skills](https://agentskills.io) standard), from one copy of the
skill.

---

## Why it is built this way

Published experiments in having language models draw pixel art hand them
primitive drawing tools -- `draw_pixel`, `draw_line`, `fill` -- and the results
come out blocky and basic. The conclusion of the best-known write-up is that
*tool granularity fundamentally constrains output quality*.

So this pipeline does not give the model a brush. It gives it three things:

1. **A text format.** A sprite is a palette plus a grid of characters. The model
   edits it the way it edits code -- precisely, in place, seeing the whole thing
   at once. Palette keys are ordered by visual density, so the raw text reads as
   a rough picture of the sprite.

2. **Eyes.** Every editing pass ends with a review sheet: the sprite blown up
   with a coordinate grid, next to its actual 1x size, its silhouette, and its
   value study. The model opens that image and critiques its own work. This loop
   is where the quality comes from.

3. **A craft linter.** The rules of pixel art -- jaggies, doubles, orphan
   pixels, banding, pillow shading, dead ramps, dither spray, and for animation
   volume drift and anchor drift -- are geometric and measurable. The linter
   measures them and says where. It catches exactly what the model cannot see.

---

## Quick start

```bash
px doctor                                        # check the environment
px project workspace/knight --name knight        # brief.md, refs/, history/, out/
cp ~/some/refs/*.png workspace/knight/refs/

# then, in Claude Code or Codex:
#   "draw me a 32x32 knight in the style of these references,
#    with a 4-frame idle where he shifts his weight"
```

The agent studies the references, writes the brief, and works through
silhouette → flats → shading → cleanup → animation, looking at its own work at
every stage.

### Watch it happen

```bash
px studio --dir workspace --open
```

Terminal on one half of the screen, browser on the other. The page re-renders on
every save, plays the animation at its real timing, replays the build history as
a time-lapse, shows the live craft findings, and hands over every export as a
download.

---

## Layout

```
.agents/skills/          skills (the standard's REPO scope -- Codex reads this natively)
  pixel-art/
    SKILL.md             the pipeline
    references/          craft, colour, animation, format, workflow, troubleshooting
    scripts/             the toolchain (standard library only)
    assets/palettes/     14 bundled palettes + attribution
    assets/studio.html   the live viewer
  pixel-art-studio/      starting the viewer
.claude/skills           symlink -> ../.agents/skills
AGENTS.md                repo rules
CLAUDE.md                symlink -> AGENTS.md
bin/px                   one command for everything
workspace/               one folder per sprite
```

One copy of everything. `.claude/` contains a symlink and nothing else.

---

## The toolchain

```
px ref IMG...                  study references: native size, palette, ramps,
                               value range, hue shift, dither density, outline
px new FILE --size 32x32 --palette sweetie-16
px view FILE                   the review sheet you must actually look at
px grid FILE --palette         the grid as text with a coordinate ruler
px lint FILE --verbose         the craft check
px fix FILE --orphans --dedupe --prune
px palette list|extract|ramp|get lospec:SLUG|apply
px import IMG --out FILE       raster -> draft (a draft, never a deliverable)
px sheet IMG --frame-size 32x32 --out FILE
px anim add|timing|drift|stats|gif
px strip FILE                  filmstrip     px onion FILE --frame N
px diff A B --image OUT.png    px snapshot FILE --stage NAME
px export FILE --fps 8         PNGs, spritesheet + JSON, GIF, .hex, .gpl, Aseprite .lua
px studio --dir workspace      the live viewer
```

Python 3.8+, standard library only. Pillow is optional and only needed to read
JPEG/WebP references (`px doctor --install` sets it up). No account, no API key,
no network -- except `px palette get lospec:<slug>`.

---

## The format

```
@meta
name: swordsman
size: 32x32
light: top-left
fps: 6

@palette
. #00000000 transparent
@ #1a1c2c   ink
% #29366f   cloth-shadow
M #3b5dc9   cloth
X #ef7d57   skin
+ #ffcd75   hair

@frame idle0
............@@@@@...............
...........@+++++@..............
...........@+@X@N@..............
```

Plain text: diffable, greppable, editable with any tool, readable by eye.

---

## Example

`workspace/swordsman/` is a worked example -- a 32x32 swordsman with a 4-frame
idle (weight shift, breath, planted sword), built through the full pipeline with
snapshots at each stage. Open it in the studio to watch the time-lapse.

---

## Tests

```bash
python3 tests/run_tests.py
```

Exercises the format round-trip, the renderer, every linter rule, the palette
maths, the animation checks, the GIF encoder, and the exports.

---

## Credits

Bundled palettes belong to their authors -- see
`.agents/skills/pixel-art/assets/palettes/ATTRIBUTION.md`. Everything else is
MIT.
