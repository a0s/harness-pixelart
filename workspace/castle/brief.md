---
class: scene
view: camera pitch=35.26 yaw=0
canvas: 192x144
palette: custom (castle_palette.hex)
light: top-left
outline: dark keyline
dither: none
---

## Subject
A small stone keep on a grass field, seen front-on from a raised camera: a broad
rectangular fort with a crenellated parapet all round, two fat round towers at
the front corners, an arched gate with a wooden portcullis and a short flight of
steps, an open timber-roofed hall visible over the front wall, and two small
guards standing on the grass in front for scale.

## Intake notes

### Pixel scale
`px ref` with no override reports `scale x1, no clean pixel grid found` and a
638x448 canvas floor -- that is wrong; the reference is an upscaled sprite that
was resampled smoothly, so the grid cannot be recovered by autocorrelation (a
period search over the JPEG lands on the 8x8 DCT block grid, not on the art
grid). Measured by eye instead, on 6x nearest-neighbour crops of the gate, the
left tower and the left character: the ink keyline around the gate arch is
consistently 3 screen pixels thick, single-pixel eye dots on the characters are
3x3, and the hair blocks step in 3s. **Scale x3.** Re-run with `--scale 3`:
native 212x155, subject 178x115, canvas floor 192x128.

### Projection -- decided by eye
`px ref` at the corrected scale reports `projection: unclear -- decide by eye`.
The three tests:

- **Are long horizontal edges flat or stepping?** Flat. The front wall's base,
  both parapet bands and the courses on the front wall all run dead horizontal
  with no 2:1 staircase anywhere. The dominant edge peak is 179 deg. So this is
  **not** isometric: **yaw = 0**, the front wall faces the camera.
- **Are top surfaces visible?** Strongly. The parapet walkway ring is visible
  all the way round, the far parapet is drawn *above* the roof, and the whole
  timber roof of the interior hall is shown over the top of the front wall. So
  the pitch is well above 0 -- this is not a side elevation.
- **Are the tower cylinders' top ellipses squashed?** Yes, but only moderately.
  The crenellated ring on each front tower reads as an ellipse roughly 3 wide
  to 2 tall, and the tower's base curve sags about 0.7 of the tower radius
  below the shaft's side extremes. A circle on the ground projects to an
  ellipse whose minor/major ratio is exactly the renderer's `k`, so both
  measurements read k = 0.6-0.7 directly. The characters still show their
  faces rather than the tops of their heads, which rules out anything
  approaching a plan view.

**Conclusion: `camera pitch=35.26 yaw=0`** -- the higher of the two standard
RPG cameras. Because vertical edges are kept 1:1 in this renderer, the depth
foreshortening is k = tan(pitch): tan(35.26) = 0.707, which brackets the
0.6-0.7 measured off the tower ellipses. The shallower pitch=26.57 (k = 0.5)
would not show as much roof and walkway as the reference does; 45 deg or more
would flatten the tall front wall that carries the gate.

## Read at 1x
Fort silhouette with two fat round towers pushing forward at the front corners,
a toothed crenellated crown, a dark arched hole in the middle of a pale wall,
and an orange roof mass filling the space behind the parapet. Two dark specks
on the grass in front say how big it is.

## Light
- direction: top-left
- key/shadow logic: tops of walls and parapets are lightest; the front wall face
  is the base tone; the right side of each tower cylinder and every right-facing
  face drops to shadow. Under every overhang -- parapet onto wall, tower rim
  onto shaft, roof onto the walkway, wall onto grass -- a deep dark band. The
  gate mouth and the inside of every crenelle are ink or near-ink.

## Style rules taken from the references
- outline: a single dark warm-ink keyline round the whole object and between
  overlapping volumes (tower against wall, roof against parapet). No keyline
  between two faces of one volume -- there the tone change is the edge.
- dither: none (measured 0.0).
- hue shift: 18 deg measured. Shadows rotate cool/green, highlights rotate warm.
- level of detail: stone courses are irregular and hand-broken, never a grid;
  each cylinder gets a 3-4 step value gradient around it; the roof is drawn as
  radiating timber planks with dark gaps.

## Palette
Five materials, three to four tones each, one ink, plus two small accents.
- grass (olive, 4)
- sandy stone, the upper wall and tower shafts (4)
- green-grey battlement stone, parapets and gate voussoirs (4)
- mossy dark stone, the wall footings (2)
- roof timber, orange-brown (4)
- accents: portcullis teal (2), skin (2)
- ink (2: keyline and a softer interior dark)

## Animation
- frames: 1. Static scene.
- loop type: none.
- what moves, what holds: nothing.

## Out of scope
No flag, no banner, no smoke, no moat, no animation. No background beyond the
grass field.

## What was drawn on top of the massing
Everything past `surfaces` is hand-drawn in the `.pxa` grid: the crenellations
on both parapets and around both tower crowns, the timber caps down inside the
towers, the mossy stone footing with a hand-broken top edge, the arched gate
with its voussoir ring and portcullis, the flight of steps, the eave shadow,
the base keyline, the highlight rows, the two guards, and the grass tufts.
The scene file was not re-rendered after the `surfaces` snapshot.
