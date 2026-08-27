---
name: pixel-art
description: Draw real, hand-crafted pixel art from reference images and a description -- characters, sprites, tiles, items, and multi-frame animations (idle, walk, attack). Use whenever the request involves pixel art, sprites, spritesheets, retro/8-bit/16-bit game art, limited-palette illustration, dithering, sprite animation, Aseprite/Lospec/PICO-8/Game Boy work, or converting an image into true pixel art. Produces a text .pxa source, PNG/GIF/spritesheet exports, and a craft-checked result -- not a filtered photo and not a diagram of rectangles.
license: MIT
compatibility: Python 3.8+ standard library only. Pillow is optional and only needed to read JPEG/WebP references. No network required except `px palette get lospec:<slug>`.
metadata:
  version: "1.0"
  entrypoint: bin/px
---

# Pixel art

You are drawing, not filtering. Every pixel is a decision. The tools here exist
so you can make those decisions in text, see the result, and be told when you
broke a rule of the craft.

## The one rule that decides quality

**Draw, render, look, critique, fix. Never skip the looking.**

A 32x32 sprite is invisible to you as raw text alone and invisible as a raw PNG.
`px view` produces a sheet -- big grid with coordinates, 1x actual size,
silhouette, value study, palette -- and you must open that image with your image
reading tool after every editing pass. Work that was never looked at is not
finished work; it is a guess. Two review cycles per stage is the floor.

## Setup

`px` is the whole toolchain. It lives at `bin/px` in this project (or
`.agents/skills/pixel-art/scripts/cli.py` if you are running the skill from
somewhere else). Run `px doctor` once to confirm the environment.

```
px project workspace/NAME --name NAME     # brief.md, refs/, history/, out/
```

Optional live viewer for a human watching you work -- split the screen, terminal
left, browser right:

```
px studio --dir workspace --open          # http://127.0.0.1:8765
```

It re-renders on every file save, plays the animation, replays your stage
history as a time-lapse, shows the craft findings, and offers every export as a
download.

## Workflow

Follow the stages in order. Each one ends with a render, a look, a lint, and a
snapshot. Do not start shading something whose silhouette does not read.

### 1. Read the references

```
px ref workspace/NAME/refs/*.png --out workspace/NAME
```

Prints, per reference: native resolution (it detects sprites that were scaled up),
palette, ramps, value range, measured hue shift, dither density, outline
convention. Writes `ref_contact.png` -- **look at it**. Fill in `brief.md` from
what you measured, not from what you assume. If the user gave no references,
still write the brief: canvas, palette, light direction, colour budget.

Ask the user only what you cannot decide: intended use (game sprite / icon /
illustration), canvas size if it matters to them, and whether the palette is
fixed. Decide everything else yourself and say what you decided.

### 2. Silhouette

```
px new workspace/NAME/NAME.pxa --size 32x32 --palette sweetie-16 --light top-left
```

Write the shape in one colour. Test it: the `SILHOUETTE` panel of the review
sheet must be identifiable with no interior detail at all. Cut negative space
into it -- between arm and torso, between legs, under a hat brim. A silhouette
that fills more than ~90% of its bounding box is a rectangle, not a character,
and the linter will say so.

### 3. Flats

Block in local colours, no shading. Every material gets exactly one colour.
Check that each region is separable in the `VALUE` panel -- two materials with
the same value will merge into a blob at real size.

### 4. Shading

Pick one light direction and put it in `@meta light:`. Then hold it everywhere.

- Two extra values per material at most: a shadow and a highlight. Not five.
- Shade along the **form**, not along the outline. Shading that follows the
  silhouette inward is pillow shading; the linter measures it and will tell you.
- Hue-shift the ramp: shadows rotate cool, highlights rotate warm.
  `px palette ramp '#b13e53' --steps 5` generates one.
- Leave one side of every form fully dark, all the way to the edge.

### 5. Cleanup

```
px lint FILE --verbose
```

Fix jaggies, doubles, orphan pixels, banding, redundant colours. Anti-alias only
where you know what is behind the pixel -- interior edges, yes; the outer
silhouette of a game sprite, no. Read `references/craft.md` before this stage
the first time.

### 6. Animation

Only after the base pose is finished.

```
px anim add FILE walk1 --copy-from idle
px anim timing FILE --ms 260,180,260,180
px anim drift FILE            # volume, height, anchor, dropped colours
px onion FILE --frame 1       # previous frame in blue, next in red
px strip FILE                 # every frame side by side
px anim gif FILE --fps 8
```

The failure mode of every model that animates pixel art is losing volume and
proportion between frames. `px anim drift` measures it. Run it after every frame
you touch, and look at the filmstrip -- a loop that reads frame by frame can
still stutter in motion.

Read `references/animation.md` before your first animation.

### 7. Deliver

```
px snapshot FILE --stage final --note "what changed"
px export FILE --fps 8
```

Report what you made, the palette size, the frame count, and anything the linter
still flags that you kept on purpose -- with the reason.

## The .pxa format

Palette plus one character grid per frame. Keys are assigned so heavy characters
mean dark colours and light ones mean light colours: the raw text reads as a
rough picture of the sprite, so you can see what you are editing.

```
@meta
name: swordsman
size: 32x32
stage: shading
light: top-left
fps: 6

@palette
. #00000000 transparent
@ #1a1c2c   ink
% #29366f   cloth-shadow
M #3b5dc9   cloth
X #ef7d57   skin

@frame idle0
................................
............@@@@@...............
...........@+++++@..............
```

Edit the grid directly with your file editing tools -- that is the primary way
to draw. `px edit` covers only the mechanical operations (rect, line, ellipse,
fill, mirror, shift, outline, crop, resize, patch); reach for it when you would
otherwise be counting pixels by hand, not for the parts that carry the read.

`px grid FILE` prints the grid with a coordinate ruler when you need exact
positions.

## Command reference

| goal | command |
| --- | --- |
| study references | `px ref IMG... --out DIR` |
| new sprite | `px new FILE --size 32x32 --palette NAME` |
| see it | `px view FILE` **then open the PNG** |
| exact coordinates | `px grid FILE --palette` |
| craft check | `px lint FILE --verbose` |
| mechanical cleanup | `px fix FILE --orphans --dedupe --prune` |
| palettes | `px palette list \| extract \| ramp \| get lospec:SLUG \| apply` |
| image to draft | `px import IMG --out FILE --size 48 --colors 12` |
| slice a sheet | `px sheet IMG --frame-size 32x32 --out FILE` |
| animation | `px anim add\|timing\|drift\|stats\|gif` |
| review animation | `px strip FILE`, `px onion FILE --frame N` |
| compare versions | `px diff A B --image OUT.png` |
| stage snapshot | `px snapshot FILE --stage NAME --note "..."` |
| ship it | `px export FILE --fps 8` |
| live viewer | `px studio --dir workspace --open` |

## Deeper references

Load these when the stage calls for them, not up front:

- `references/craft.md` -- jaggies, doubles, clusters, AA, dithering, outlines,
  the readability rules the linter checks and why they exist.
- `references/colour.md` -- palettes, ramps, hue shifting, value planning,
  working inside a locked palette.
- `references/animation.md` -- idle/walk/attack construction, timing, anchors,
  secondary motion, what the drift checker means.
- `references/format.md` -- the .pxa specification and the Python API.
- `references/workflow.md` -- the long form of the stages, with worked examples.
- `references/troubleshooting.md` -- what to do when the result looks wrong.

## Non-negotiables

1. Look at every render. No exceptions.
2. One light direction per sprite, declared in the file.
3. Lock the palette before shading; add colours only with a reason.
4. Integer scaling only. Never resample pixel art to a non-integer size.
5. `px lint` before you call anything finished, and address or justify each finding.
6. `px anim drift` after every animation change.
7. Never present a machine conversion (`px import`) as finished pixel art -- it
   is a draft to be redrawn.
