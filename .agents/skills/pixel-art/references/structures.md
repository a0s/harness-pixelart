# Structures and scenes

How to draw buildings, vehicles, furniture and whole little scenes so they read
as volumes in space instead of as a front elevation. This is pipeline B of
`SKILL.md`; read this once before your first structure.

## Why buildings fail

The text grid makes horizontal and vertical edges free and every slanted edge
expensive: a 2:1 line across forty rows is forty hand-counted offsets. Left to
itself, a model draws what is cheap -- a rectangle for the wall, a triangle for
the roof -- and gets a diagram of a house seen dead-on. Texture painted on
those rectangles makes them look *more* flat, not less, because the thatch
rows and brick courses are all horizontal.

The references you are matching do the opposite. Look at any 3/4 top-down or
isometric building and the read comes from three things:

1. **Three tones for three planes.** Top surfaces are lightest, the face
   towards the light is the base tone, the face away from it is the shadow
   tone. Material colour is secondary; plane orientation is what says "box".
2. **Texture that follows the plane.** Shingles compress on the far slope,
   log ends show on the gable, brick courses run along the wall direction.
3. **Contact shadow and eave shadow.** A dark band under every overhang --
   roof onto wall, wall onto ground, rim onto tower -- is what separates the
   volumes from each other.

None of these can be improvised pixel by pixel. So you build first.

## Projections

Every view here is a linear map from world space (X right, Y away from the
viewer, Z up) to the screen. The renderer takes the map; you pick it from the
references. `px ref` measures the edge angles and tells you which family a
reference belongs to; you confirm by eye.

| `view:` | screen axes (per world unit) | visible faces of a box | looks like |
| --- | --- | --- | --- |
| `3/4-topdown k=0.5` | X→(1,0) Y→(0,-k) Z→(0,-1) | top (squashed by k) and front | Stardew, Moonlighter, most "RPG" buildings. Fronts face you straight on; you see the roof plane from above. k=0.5 is typical; 0.6–0.7 is a higher camera. Side walls of an axis-aligned box are invisible -- depth is read from roof slopes, eaves and shadows. |
| `iso` | X→(1,½) Y→(1,-½) Z→(0,-1) | top, front (-Y) and right (+X) | Classic pixel isometric 2:1. Every horizontal edge steps 2 px across per 1 px down. Three faces of every box show. |
| `oblique` | X→(1,0) Y→(½,-½) Z→(0,-1) | top, front and right | Cabinet/military projection. Fronts are undistorted, depth recedes at 45°. |
| `side` | -- | front only | Pipeline A. A side-scroller building is a prop. |
| `custom axes=...` | any three vectors | depends | A touch of side wall in a top-down game: `axes: 1,0 0.25,-0.5 0,-1`. |
| `camera pitch=P yaw=Y` | `camera_axes(P, Y)` -- computed, not fixed | depends on P, Y | Stated the way a person thinks about a camera: tilt down by pitch, turn by yaw. `pitch=26.57 yaw=0` is the same projection as `3/4-topdown k=0.5`; `pitch=26.57 yaw=45` is the same as `iso`; `pitch=35.264 yaw=45` is true 30-degree isometry. `px scene render` warns (without blocking) when an axis lands on a dirty, non-stepping ratio and suggests the nearest clean yaw. |

Which face is lit follows from the map and `light:`. With `light: top-left`
and `3/4-topdown` you get: top = light, front = base, the left roof slope
lighter than the right, anything facing +X in shadow. That is what the
references show: pick the light direction from the reference, not from habit.

The `unit` is how many screen pixels one world unit is. Choose it so the
building's screen size matches the subject size `px ref` measured. A house of
10x8x6 units at `unit: 6` in `3/4-topdown k=0.5` is 60 px wide and
6·6 + 8·6·0.5 = 60 px tall before the roof. Coarser units (4–6 px) keep the
massing honest; fine units (1–2 px) invite fiddling.

## The scene file

```
@scene
name: barn
view: topdown          # topdown | iso | oblique | custom
k: 0.5                 # topdown foreshortening
unit: 6                # px per world unit
light: top-left
canvas: 144x128        # optional; default auto-fits
outline: ink           # ink | none
shadow: 2              # 0=off, 1=cast shadows, 2=+ambient occlusion at object creases (default)

@materials
# name   base     [shadow  light]      [texture=tile.tex] [space=screen|world]
grass    #8e8b2e
wall     #d7c996
timber   #b77e3c  #7a4e22 #e0a35c
roof     #4d94a7  #2f6b86 #7fc0d0    texture=shingles.tex
stone    #7f7f7f                      texture=bricks.tex

@objects
# type    name    at=x,y,z    size=sx,sy,sz   mat=NAME   extras
ground    yard    at=-3,-3,0  size=22,16      mat=grass
box       body    at=0,0,0    size=10,8,6     mat=wall
gable     roof    at=-1,-1,6  size=12,10,4    mat=roof   ridge=x
box       porch   at=3,-2,0   size=4,2,3      mat=timber
shed      awning  at=3,-2,3   size=4,3,1      mat=roof   high=+y
cyl       silo    at=14,3,0   r=2.5 h=7       mat=stone  sides=16
cone      cap     at=14,3,7   r=3 h=3         mat=roof
```

Shapes: `box`, `ground` (a box with no height), `gable` (two slopes, ridge
centred along `ridge=x|y`), `hip` (four slopes; `ridge_len=0` is a pyramid),
`pyramid`, `shed` (one slope, `high=` names the tall edge), `cyl`, `cone`.
`at` is the minimum corner for box-like shapes and the base centre for round
ones. Per-face material overrides: `top=`, `front=`, `left=` and so on.

`gable`, `hip`, `pyramid` and `shed` take `thickness=N` (world units, default
0): it extrudes the slope into a slab, so the eave shows a visible edge face
(`edge-0`, `edge-1`, ...) instead of a paper-thin roof, plus an `underside`
face that usually falls in shadow. A roof without it reads as folded paper.

Materials get a five-step ramp automatically (darkest, shadow, base, light,
lightest), spaced by fixed L* offsets from the base colour itself (shadow
~22 L* below, light ~18 L* above) so the steps stay separated even when the
base is already dark or light, with a cool shift into shadow and a warm shift
into light. A face's tone is one of four buckets, not three: `light`, `base`,
`shadow`, and -- for a plane pointed hard away from the light, like the
underside of an eave or the far slope of a roof -- `dark`, which reads darker
than a merely unlit wall. Give explicit `shadow light` colours when you are
matching a reference palette exactly. `jitter=N` (0..3, a percent) breaks up
mechanical texture repetition: that fraction of texture-marked pixels are
dropped or nudged one tile cell, deterministically, so the same scene always
renders the same jitter.

`px scene render FILE.scene` writes `FILE.pxa` (flat-shaded, outlined, with
real cast shadows from a light-space depth pass -- the barn throws a shadow on the grass, the eave darkens the wall under it) and `review/FILE_guide.png` (the render at 4x with the
wireframe and object names). `px scene faces` prints every visible face with
its tone and screen bounding box, which is how you find where to put a window.

## Textures

A texture is a tiny text tile in face space:

```
####....
-..+....
-..+....
....####
....-..+
....-..+
```

`.` face tone, `-` one step darker, `+` one step lighter, `=` / `*` two steps,
`#` ink. The tile repeats across the face, oriented along the face's own axes
(across the wall and down it; along the ridge and down the slope; around the
cylinder and down). On a slanted face the rows shear with the face; on a
squashed top face they squash with it. The same tile on a shadow face shades
around the shadow tone, so one `bricks.tex` serves the whole building.

Rules of thumb:

- Keep tile contrast low: mostly `.` with a `-` seam and an occasional `+`.
  A tile that is half ink turns a wall into a grille.
- Tile period 4–8 px. Smaller reads as noise at 1x, larger reads as stripes.
- Make the courses *irregular* by hand after rendering (drop a seam, widen a
  stone). Perfect repetition is the tell of a generated texture.
- Big flat materials (plaster, painted wood) get no tile at all; let the tone
  and one or two hand-placed marks carry them.

Bundled tiles live in `assets/textures/`: `bricks.tex`, `shingles.tex`,
`planks.tex`, `thatch.tex`. Copy one next to your scene and edit it.

## The stage order for a structure

1. **Massing** -- scene only, no textures. The guide image must read as the
   building at 1x. Compare with the reference silhouettes on the contact
   sheet: same proportions, same roof pitch, same overhang. Fix the scene, not
   the pixels.
2. **Surfaces** -- textures on, render once more, then leave the scene alone.
   Snapshot. From here on the `.pxa` is the source of truth.
3. **Openings and features** -- door, windows, shutters, beams, chimney,
   sign. All by hand in the grid, using `px scene faces` for the face bounds
   and `px grid` for coordinates. A recessed opening has a dark line on its
   light side and a light line on its shadow side.
4. **Props** -- each prop is a small pipeline-A sprite in its own file
   (`px new`, silhouette, flats, shading, lint), then `px edit FILE patch`
   into the scene at the right position. Same light, same ink.
5. **Outline and light** -- the keyline pass, the highlight pass
   (one lighter row on every top-left edge that faces the light), the
   deepened contact shadows, selective anti-aliasing on long slants.
6. **Cleanup** -- `px lint --verbose`. For structures it adds:
   - `form-value`: a face's painted mean value must keep the tone rank the
     massing gave it (light > base > shadow within one object). If you broke
     it, you textured the form away.
   - `form-coverage`: the painting must still cover the massing and not much
     more. Holes or blobs mean you drifted from the construction.
   - `iso-slope` (iso only): long silhouette edges must step 2:1.

   `px scene guide FILE.scene --over FILE.pxa` draws the wireframe over the
   painting for the same check by eye.

## Matching the reference style

What the good 3/4 references have in common, so you can check yours:

- **Chunky keyline.** A dark outline (near-black, slightly warm or cool, not
  pure black) around the whole object and between overlapping objects; thick
  where a shape is in shadow, broken by a highlight where it catches light.
- **Rounded timber.** Beams and posts are not rectangles: they have a lighter
  top row, a darker bottom row, and rounded end caps with a ring.
- **Roof courses.** Shingles/thatch/tiles drawn as irregular rows that follow
  the slope, each row with one darker seam; the rows get thinner towards the
  far edge in `3/4-topdown` (the renderer does this; keep it when you edit).
- **Eave shadow.** A two- to four-pixel dark band on the wall right under the
  roof, darker at the corners.
- **Openings are dark.** Door and window interiors are the ink or the darkest
  ramp step; a doorway is a hole, not a rectangle of brown.
- **Ground is part of the object.** A tuft of grass, a step, a fence post, a
  patch of hay, a shadow: the building sits *on* something.
- **Scale reference.** A person, an animal or a barrel next to the building
  tells the eye how big it is.
- **Palette discipline.** Four or five materials, three tones each, one ink,
  one or two accents (a blue roof against warm walls, a red door). Count the
  reference's colours with `px ref` and do not exceed them.

## Common mistakes and the fix

| symptom | cause | fix |
| --- | --- | --- |
| Looks like a front elevation | drew silhouette-first / no `view:` | go back to massing; `px scene render` |
| Roof is a flat triangle | gable rendered in `side` view, or slopes textured with horizontal rows | `3/4-topdown` gable: the front slope shows as a trapezoid, the ridge is a highlight line |
| Box looks like a cross-section | side faces all the same tone | check `light:`; the far face must be the shadow tone |
| Walls float | no contact shadow, no ground | add a `ground` object, keep `shadow: 2`, deepen by hand at corners |
| Texture reads as noise | tile too contrasty or too small | mostly `.`, period ≥ 4, drop the `+` |
| Iso edges wobble | hand-edited a 2:1 edge | `px lint` `iso-slope` points at the run; restore 2-px steps |
| Windows look pasted on | drawn axis-aligned on a slanted face | read the face slope from `px scene faces`; shear the window with it |
| Everything is the same value | texture removed the tone difference between faces | `form-value` finding; restore the face tone as the majority colour of each face |
| A palette remap swapped whole materials -- a wooden roof on blue fence posts | the remap keyed on the palette character | `px scene render` re-assigns keys by luminance on *every* render, so any geometry change reshuffles them. Key the remap on the swatch **name** (`roof`, `timber`, `wool`), never on the character |
| An open lean-to bay renders as empty air under the roof | `shed` draws only its slope plus the thickened edges -- it has no front, side or back faces | mass a `box` under the shed whose height matches the roof's **lowest** edge, or paint the void by hand in the grid |

## Worked example: a sheep farm in 3/4 top-down

Reference: a barn with an open hay loft, a gabled house with a cow sign, a
sheep pen with a trough. Measured: native scale x2, subject 250x240, edges
axis-aligned with a ~35° roof pitch, dark warm keyline, 20-odd colours in
five ramps, no dither. So:

```
---
class: scene
view: 3/4-topdown k=0.5
canvas: 160x160
palette: custom (farm_palette.hex)
light: top-left
outline: dark keyline
dither: none
---
```

Massing: `ground` for the yard, `box` + `gable ridge=y` for the house (ridge
towards the viewer so the gable faces you, like the reference), `box` +
`gable ridge=x` for the barn with a lower wall so the loft is open, a `box`
for the hay inside the loft, small boxes for the fence posts. Surfaces:
`shingles.tex` on both roofs, `planks.tex` on the barn wall, nothing on the
plaster. Then by hand: the door arch, the round sign, the log corner posts,
the hay pile. Props: three sheep (one 12x10 sprite, mirrored and shifted), a
trough, a pitchfork. Keyline, highlights, eave shadows. Lint. Done -- and at
every step, the guide and the review sheet were opened and compared with the
contact sheet.
