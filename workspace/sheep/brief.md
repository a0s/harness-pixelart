---
class: character
view: camera pitch=0 yaw=0
canvas: 40x32
canvas-override: reason the reference subject 268x259 is the whole farm image; the subject here is one sheep out of it, ~38x30 px at that native scale, and the user asked for ~40x32
palette: extracted 8 (sheep_palette.hex)
light: top-left
outline: dark keyline
dither: none
---

## Subject
A single sheep in the style of the farm reference, seen from the side, standing
still and idling -- a fat cloud of cream fleece with soft rounded lobes, a small
dark blue-grey face and one ear poking out of the right side, thin dark legs
with a dark hoof line.

Canvas note: the whole reference image is 268x259 at native scale, but the
subject here is a single sheep out of it, which measures ~38x30 px in that
reference. 40x32 clears that floor and gives the fleece lobes and the face the
extra room the request asked for.

## Read at 1x
The lobed fleece cloud, the dark wedge of the head low on the right, four thin
legs under a wide body. If those three read, the sheep reads.

## Light
- direction: top-left
- key/shadow logic: fleece lit white on the top-left lobes, warm cream through
  the middle, cool grey-blue under the belly. The head is a dark mass with a
  single light rim on its top-left. No light bounces back up from the ground.

## Style rules taken from the references
- outline: one dark ink keyline (#141727) around the whole silhouette, and
  between the head and the fleece where they overlap.
- dither: none -- the reference measures 0.0 dither density.
- hue shift: warm in the light (cream), cool in the shadow (grey-blue/teal).
  ~12 deg in the reference.
- level of detail: very low. No individual wool curls; the lobes of the
  silhouette are the wool texture.

## Animation
- frames: 12
- loop type: true cycle (a full breath in and out)
- what moves: body rises/falls 1 px on the breath; fleece lobes settle a pixel
  at offset moments; head dips and lifts for a chew with a 1 px jaw on a faster
  sub-rhythm; one ear flick on a single frame; a blink on one frame; the tail
  and one hind leg shift weight once per loop.
- what holds: the hooves. The ground line never moves.

## Out of scope
Grass, fence, shadow on the ground, a second sheep.
