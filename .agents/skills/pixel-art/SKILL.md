---
name: pixel-art
description: Draw real, hand-crafted pixel art from reference images and a description -- characters, props, buildings, isometric and 3/4 top-down structures, tiles, and multi-frame animations (idle, walk, attack). Use whenever the request involves pixel art, sprites, spritesheets, retro/8-bit/16-bit game art, isometric or top-down game buildings, limited-palette illustration, dithering, sprite animation, Aseprite/Lospec/PICO-8/Game Boy work, or converting an image into true pixel art. Produces a text .pxa source, PNG/GIF/spritesheet exports, and a craft-checked result -- not a filtered photo, not a diagram of rectangles, and not a flat elevation when a 3/4 view was asked for.
license: MIT
compatibility: Python 3.8+ standard library only. Pillow is optional and only needed to read JPEG/WebP references. No network required except `px palette get lospec:<slug>`.
metadata:
  version: "2.0"
  entrypoint: bin/px
---

# Pixel art

You are drawing, not filtering. Every pixel is a decision. The tools here exist
so you can make those decisions in text, see the result, and be told when you
broke a rule of the craft.

## The one rule that decides quality

**Draw, render, look, critique, fix. Never skip the looking.**

A sprite is invisible to you as raw text alone and invisible as a raw PNG.
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

Live viewer for a human watching you work -- split the screen, terminal
left, browser right. Start it whenever a person is around:

```
px studio --dir workspace --open          # http://127.0.0.1:8765
```

It re-renders on every file save, plays the animation, replays your stage
history as a time-lapse, shows the craft findings, and offers every export as a
download.

## Two pipelines, one intake

Pixel art is not one craft. A character reads through its **silhouette**; a
building reads through its **volumes** -- three tones for three plane
orientations. Drawing a building silhouette-first is how you get a flat
elevation instead of a 3/4 view. So the intake is shared, and then the subject
class picks the pipeline:

| class | what it is | pipeline |
| --- | --- | --- |
| `character` | people, creatures, anything that poses and animates | **A. silhouette-first** |
| `prop` | items, icons, small flat objects, pickups | **A. silhouette-first** |
| `structure` | buildings, vehicles, furniture, machines -- anything with faces in space | **B. massing-first** |
| `scene` | a structure plus its props and ground (a farm, a shop front) | **B. massing-first**, props via A |

Tiles and terrain are a `structure` (a ground plane and its edges) or a `prop`
(a single decorative tile) depending on whether they have height.

## Intake (every job)

### 1. Read the references

```
px ref workspace/NAME/refs/* --out workspace/NAME
```

Prints, per reference: native resolution (it detects sprites that were scaled
up, including JPEG upscales), the **projection** measured from edge angles
(isometric 2:1 / axis-aligned side-or-top-down with the roof pitch / oblique),
the **subject size** at native scale and the minimum canvas that follows from
it, palette, ramps, value range, hue shift, dither density, outline convention.
Writes `ref_contact.png` -- **look at it**, and decide two things by eye that
the numbers cannot: is the subject a character or a structure, and if the
edges are axis-aligned, are top surfaces visible (3/4 top-down) or not (side
view)?

### 2. Write the brief, then pass the gate

Fill in `brief.md` from what you measured, not from what you assume. The file
starts with a header the tools read:

```
---
class: structure
view: camera pitch=26.57 yaw=0
canvas: 144x128
palette: custom (NAME_palette.hex)
light: top-left
outline: dark keyline
dither: none
---
```

- `view` is stated as a camera: `pitch` tilts it down from the horizon,
  `yaw` turns it around the vertical axis. Both in degrees.

  | | |
  | --- | --- |
  | `pitch=0` | side view, no top surfaces |
  | `pitch=26.57` | the RPG tilt -- the ground foreshortens 1:2 |
  | `pitch=35.26` | a higher camera |
  | `pitch=90` | straight down, no walls |
  | `yaw=0` | the front wall faces the viewer |
  | `yaw=45` | the building stands corner-on |

  So `camera pitch=26.57 yaw=0` is the RPG / 3/4 top-down look of most
  reference art, and `camera pitch=26.57 yaw=45` is pixel isometric 2:1.
  A small yaw (15-25) shows a sliver of side wall and reads as a camera
  placed off to one side. The aliases `side`, `iso`, `oblique`,
  `3/4-topdown k=<0.4..0.7>` and `custom axes=...` still work.

  Match the references: `px ref` measures whether their edges are
  axis-aligned (yaw 0) or 2:1 diagonal (yaw 45), and prints the roof pitch.
- `canvas` is **never smaller than the subject at the references' native
  scale** unless the user asked for a specific size. `px ref` prints the
  floor. A 64x64 canvas cannot hold a building that was 180 px in the
  reference; the volumes collapse into blocks.

```
px brief workspace/NAME            # refuses to pass until the header is complete
```

Run it before you create anything. It prints the pipeline you are on.

Ask the user only what you cannot decide: intended use (game sprite / icon /
illustration), a size they need, and whether the palette is fixed. Decide
everything else yourself and say what you decided.

---

## Pipeline A -- characters and props (silhouette-first)

### A1. Silhouette

```
px new workspace/NAME/NAME.pxa --size 32x32 --palette sweetie-16 --light top-left
```

Write the shape in one colour. Test it: the `SILHOUETTE` panel of the review
sheet must be identifiable with no interior detail at all. Cut negative space
into it -- between arm and torso, between legs, under a hat brim. A silhouette
that fills more than ~90% of its bounding box is a rectangle, not a character,
and the linter will say so.

### A2. Flats

Block in local colours, no shading. Every material gets exactly one colour.
Check that each region is separable in the `VALUE` panel -- two materials with
the same value will merge into a blob at real size.

### A3. Shading

Pick one light direction and put it in `@meta light:`. Then hold it everywhere.

- Two extra values per material at most: a shadow and a highlight. Not five.
- Shade along the **form**, not along the outline. Shading that follows the
  silhouette inward is pillow shading; the linter measures it and will tell you.
- Hue-shift the ramp: shadows rotate cool, highlights rotate warm.
  `px palette ramp '#b13e53' --steps 5` generates one.
- Leave one side of every form fully dark, all the way to the edge.

Then continue with **Cleanup**, **Animation**, **Deliver** below.

---

## Pipeline B -- structures and scenes (massing-first)

A building is built, not outlined. You block it out as boxes, roofs and
cylinders in world units; the renderer projects them with the declared view and
gives you a flat-shaded sprite where every visible face already has the right
slope, the right tone and the right texture direction. Then you paint on top of
it. You never compute an isometric slope by hand.

Read `references/structures.md` before your first structure. It has the
projection cheatsheet, the roof types, and the worked farm example.

### B1. Massing

```
px scene new workspace/NAME/NAME.scene --view topdown --unit 6
px scene render workspace/NAME/NAME.scene        # -> NAME.pxa + review/NAME_guide.png
```

Edit the `.scene` until the **guide image** reads as the building at 1x with no
detail at all: the roof mass, the wall mass, the door void, the chimney. Judge
it against the reference contact sheet. Adjust the `unit` so the building's
screen size matches the subject size `px ref` measured. Rules of thumb:

- Roofs are bigger than the walls they cover (overhang by one unit).
- Everything that sticks out gets its own object, with its own name.
- A `ground` object under the building is what carries the contact shadows.
- Lock the view here. Changing `view` later means redrawing everything.

The rendered `.pxa` carries `@meta view:` and `scene:`; the linter reads them.
Snapshot as stage `massing`.

### B2. Surfaces

Assign textures to materials in the `.scene` (`texture=bricks.tex`; the
bundled tiles live in `assets/textures/`, and you can write your own tile in
seconds). Re-render. The tile is projected onto each face, so brick courses run
along the wall, shingles compress on the far slope, and the same tile shades
darker on the shadow face. This is the stage that used to be done by hand and
came out flat. Look at the result at 1x: texture should read as *material*, not
as noise. Reduce contrast in the tile if it fights the face tones.

Snapshot as stage `surfaces`. From here on you edit the `.pxa` grid directly
and **stop re-rendering the scene** -- a re-render overwrites your painting.
If the massing must change, change the scene, re-render to a new file and
`px diff` the two to carry your work across.

### B3. Openings and features

Doors, windows, shutters, beams, signs, chimneys: edit the grid. Windows are
holes in a face, so they take the face's slope -- read the slope from the
guide's wireframe or `px scene faces`. Frame every opening with one darker
line on its light side and one lighter line on its shadow side (it is recessed).
Trim beams and posts with a highlight pixel row on the light-facing edge.

### B4. Props

Sheep, fences, hay, barrels, people: each one is a **Pipeline A** sprite drawn
in its own small `.pxa` (silhouette, flats, shading), then placed with
`px edit FILE patch` or by pasting rows. Keep them on the same light and the
same ink. Props are what make a scene look inhabited; do not skip them because
the building took long.

### B5. Outline and light

Now the pass the references get their punch from:

- One dark keyline around the whole silhouette and where an object sits in
  front of another one. Not between faces of the same object -- there the tone
  change is the edge.
- One highlight row along every top-left edge that faces the light (roof ridge,
  the top of every beam, the rim of a tower).
- Contact shadow under every overhang: eaves onto walls, walls onto ground.
  The renderer drew a first pass; deepen and extend it by hand where two
  objects touch.
- Anti-alias only the long slanted edges, one pixel of the intermediate tone,
  and only on interior edges.

```
px scene guide workspace/NAME/NAME.scene --over workspace/NAME/NAME.pxa
```

overlays the wireframe on your painting. If a wall no longer follows its
plane, fix the wall, not the wireframe.

Then continue with **Cleanup**, **Animation**, **Deliver**.

---

## Cleanup (both pipelines)

```
px lint FILE --verbose
```

Fix jaggies, doubles, orphan pixels, banding, redundant colours. For
structures the linter also checks that every face still keeps its tone rank
(`form-value`), that the painting still covers the massing (`form-coverage`),
and for `iso` that long edges step 2:1 (`iso-slope`). Anti-alias only where you
know what is behind the pixel -- interior edges, yes; the outer silhouette of a
game sprite, no. Read `references/craft.md` before this stage the first time.

## Animation (both pipelines)

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
still stutter in motion. For structures, animate *parts* (smoke, flags, water,
a windmill) and hold the massing still.

Read `references/animation.md` before your first animation.

## Deliver

```
px snapshot FILE --stage final --note "what changed"
px export FILE --fps 8
```

Report what you made, the view, the canvas, the palette size, the frame count,
and anything the linter still flags that you kept on purpose -- with the reason.

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
| pass the brief gate | `px brief DIR` |
| new sprite (pipeline A) | `px new FILE --size 32x32 --palette NAME` |
| new massing (pipeline B) | `px scene new FILE.scene --view topdown\|iso` |
| render massing | `px scene render FILE.scene` **then open the guide** |
| wireframe over painting | `px scene guide FILE.scene --over FILE.pxa` |
| face table | `px scene faces FILE.scene` |
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

- `references/structures.md` -- projections, the `.scene` format, roofs,
  textures, props, the reference-style checklist for 3/4 and isometric art.
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
2. `px brief` passes before the first pixel. Class, view and canvas are
   decisions, and they are made from the references, not from habit.
3. A structure is massed before it is drawn. Never draw a building
   silhouette-first; never compute a projected slope by hand.
4. The canvas is never smaller than the subject at the references' native
   scale unless the user asked for that size.
5. One light direction per sprite, declared in the file.
6. Lock the palette before shading; add colours only with a reason.
7. Integer scaling only. Never resample pixel art to a non-integer size.
8. `px lint` before you call anything finished, and address or justify each finding.
9. `px anim drift` after every animation change.
10. Never present a machine conversion (`px import`) as finished pixel art -- it
    is a draft to be redrawn.
