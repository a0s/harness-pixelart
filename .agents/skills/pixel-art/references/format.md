# The .pxa format

A pixel image as plain text: a palette of one-character keys, and one grid of
those characters per frame. Diffable, greppable, editable with ordinary text
tools, and readable by eye.

```
@meta
name: swordsman
size: 32x32
stage: shading
light: top-left
anchor: bottom
fps: 6
timing: 260,180,260,180
note: idle loop, sword stays planted

@palette
. #00000000 transparent
@ #1a1c2c   ink
% #29366f   cloth-shadow
M #3b5dc9   cloth
X #ef7d57   skin
+ #ffcd75   hair

@frame idle0
................................
............@@@@@...............
...........@+++++@..............
...

@frame idle1
...
```

## Rules

- Sections start with `@meta`, `@palette`, `@frame NAME` (`@grid` is accepted as
  a synonym). Order is free; `@frame` blocks run to the next section.
- Every grid row must be exactly `width` characters. Every frame must be the same
  size. `px lint` reports violations as `invalid-document`.
- Palette lines are `KEY #hex [name]`. The key is exactly one character. Hex may
  be `#rgb`, `#rrggbb` or `#rrggbbaa`.
- `.` is transparent by convention; any swatch with alpha 0 counts as
  transparent.
- Inside `@meta` and `@palette`, lines starting with `#` are comments. Inside a
  grid, only `# ` (hash followed by a space) is a comment -- a row may start with
  `#` as a palette key.
- Blank lines are ignored everywhere.

## Meta keys the tools understand

| key | used by | meaning |
| --- | --- | --- |
| `name` | exports, studio | base filename for output |
| `size` | lint | cross-checked against the grid |
| `stage` | snapshots, studio | where you are in the workflow |
| `light` | you | the declared light direction; hold it |
| `anchor` | `px anim drift` | `bottom` or `center` -- what must not move |
| `fps` | gif, export | frame rate when `timing` is absent |
| `timing` | gif, export | per-frame durations in ms, comma separated |
| `note` | studio | free text |

Anything else is preserved untouched.

## Why the keys look the way they do

`px new` and `px import` assign palette keys from a density-ordered alphabet
(`@ # % $ & 8 B M W N H K R E X S A o u c = + - : ; ' \``) in order of
luminance. Heavy characters land on dark colours, light ones on bright colours,
so the raw grid text is a rough ASCII picture of the sprite. You can see what you
are editing without rendering.

You may re-key by hand -- rename the palette entry and replace the character
throughout -- if a mnemonic serves you better. Keep `.` for transparency.

## Editing

Editing the grid text directly is the primary interface. Use your normal file
tools. `px grid FILE --palette` prints the grid with a coordinate ruler and the
palette with per-key pixel counts when you need exact positions.

`px edit` handles the mechanical operations:

```
px edit FILE rect   -x 4 -y 4 --x2 12 --y2 20 --key M --fill
px edit FILE line   -x 4 -y 4 --x2 12 --y2 9  --key @
px edit FILE ellipse -x 15 -y 8 --x2 5 --y2 6 --key X --fill   # x2/y2 are radii
px edit FILE fill   -x 15 -y 12 --key M
px edit FILE replace --key-from M --key A
px edit FILE outline --key @ --mode inside
px edit FILE silhouette --key @
px edit FILE mirror --axis x --source left
px edit FILE shift  -x 1 -y 0
px edit FILE crop --margin 1
px edit FILE resize --size 48x48 --anchor bottom
px edit FILE scale --factor 2
px edit FILE patch -x 10 -y 6 --rows '..@@..|.@XX@.|@XXXX@' --passthrough '~'
```

Add `--frame NAME` to target one frame, `--all-frames` for all of them,
`--out OTHER.pxa` to write elsewhere.

## Python API

Everything the CLI does is available directly. `sys.path` must include
`.agents/skills/pixel-art/scripts`.

```python
import pxa, canvas, render, lint, anim, palettes, export

doc = pxa.load("sprite.pxa")
f = doc.frame("idle0")

f.get(12, 7)                    # character at a coordinate
f.set(12, 7, "@")
f.counts()                      # {key: pixel count}
doc.rgba("@")                   # (26, 28, 44, 255)
doc.add_swatch((255, 205, 117, 255), "hair")

canvas.outline(doc, f, "@", mode="inside")
canvas.clean_orphans(doc, f)
canvas.mirror(f, axis="x")

for finding in lint.run(doc):
    print(finding.severity, finding.rule, finding.message, finding.at)

anim.add_frame(doc, "idle1", source="idle0")
anim.drift(doc, anchor="bottom")
anim.stats(doc, f)              # area, bbox, centre of mass, colour counts

pxa.write_png("out.png", render.render_frame(doc, f, scale=8))
pxa.write_png("sheet.png", render.review_sheet(doc))
export.bundle(doc, "out/")
pxa.save(doc, "sprite.pxa")
```

Useful colour helpers in `pxa`: `parse_hex`, `format_hex`, `rgb_to_hsl`,
`hsl_to_rgb`, `luminance`, `contrast_ratio`, `color_distance` (perceptual, CIE76),
`nearest_color`.

`palettes` has `extract`, `ramp`, `ramps_of`, `sort_palette`, `snap_pixels`,
`load_palette`, `save_hex`.

## Interop

- `px import IMG --out FILE` -- any raster image to a draft .pxa. Detects
  upscaled pixel art and recovers its native resolution.
- `px sheet IMG --frame-size 32x32 --out FILE` -- slice an existing spritesheet
  into frames.
- `px export FILE` -- PNGs at several scales, spritesheet plus JSON manifest,
  GIF, .hex and .gpl palettes, and an Aseprite .lua rebuild script.
- Aseprite itself is optional. If it is installed, `aseprite -b -script out/NAME.lua`
  reconstructs the sprite with its frames, timing and palette for hand editing.
