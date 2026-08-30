---
class: scene
view: camera pitch=26.57 yaw=0
canvas: 184x164
canvas-override: the reference is a x2 upscale whose native subject is 258x257, but its detail density is a ~180 px asset -- courses, rails and sheep all read at that size. Working at 184x164 (0.72x) keeps every material at 3 tones without inventing detail the reference does not have, and keeps the sprite usable as a game asset. The 184x164 shape follows the real subject, which measures 244x212 once the JPEG noise around the cut-out is excluded. Nothing in it needs more width to stay separable.
palette: custom (farm_palette.hex)
light: top-left
outline: dark keyline
dither: none
---

## Subject
A cosy sheep farm seen front-on and slightly from above: a tall plaster-and-timber
gable-front house with a steep blue shingled roof, a cow-head sign and an arched
door; a lean-to hay barn against its left side with an open loft and straw
spilling out; a log fence penning three sheep, with a feeding trough.

## Camera
`camera pitch=26.57 yaw=0`. `px ref` measured the reference's edge histogram at
91 deg (0.34) and 179 deg (0.21) -- overwhelmingly axis-aligned, with no 2:1
diagonal family, so yaw is 0, not 45. Top surfaces *are* visible (both roof
slopes of the house show as foreshortened planes either side of a vertical ridge,
and the barn's shed roof shows as a full plane), so the pitch is a real tilt, not
a side view. 26.57 makes the ground foreshorten 1:2, which matches how far the
roof planes recede behind the gable in the reference. Yaw stays at 0 because the
reference shows no side wall at all on either building -- adding one would be a
different picture, not the same craft.

## Read at 1x
House silhouette: steep dark-edged triangle over a pale block, with a black
door hole. Barn: a blue slab with a black void under it. Three white blobs with
dark heads on the left. That must survive at 1x with no interior detail.

## Light
- direction: top-left
- key/shadow logic: roof top planes are the lightest tone of their material; the
  left roof slope is one step lighter than the right. Walls take the base tone
  with a 3 px eave shadow band under every overhang and a darker band down the
  right edge. Every opening (door, loft, window) is ink or the darkest ramp
  step -- a hole, not a brown rectangle. Timber is rounded: light row on top,
  ink row underneath. No cast shadows on the ground because there is no ground:
  the reference is a transparent-background cut-out asset, so contact shadow is
  carried by the keyline and by darkening the object it lands on.

## Style rules taken from the references
- outline: a chunky dark keyline (#171a2b, cool navy, not black) around the whole
  silhouette and between every pair of overlapping objects. `px ref` reported "no
  strong outline convention" because it measured against pure black; by eye the
  reference is keylined everywhere.
- dither: none (measured 0.0).
- hue shift: 12 deg, cool into shadow, warm into light -- matched in the ramps.
- level of detail: shingle courses hand-broken (no two rows identical), plaster
  left almost flat with two or three scuff marks, timber grain as short dark
  ticks. Four structural materials (plaster, timber, roof, straw) plus wool and
  one ink.

## Props
Three sheep (a 33x23 pipeline-A sprite in workspace/farm/sheep.pxa, three seeded
variants rather than one mirrored copy), a log fence in two runs with rails, a
plank trough heaped with straw, loose straw on the barn floor, a chimney pot.
The pitchfork was drawn and then cut: at this scale it read as a smear across
the hay rather than a tool.

## Animation
- frames: 1. This is a static scene asset, as the reference is.
- loop type: n/a
- what moves, what holds: n/a

## Out of scope
Ground plane, sky, cast shadows onto grass, weather, characters, day/night
variants, the castle reference (studied for style only).
