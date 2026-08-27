# stable -- art direction brief

## Subject
A cute little horse stable, front three-quarter view: stone-block foundation,
timber-frame walls, a steep straw-thatch roof, double barn doors, one shuttered
window, and a small hay bale leaning by the door. Same warm-craft-illustration
style as `refs/reference.png`, but with a straw roof instead of that
reference's blue tile roof, since the thatch is what animates.

## Read at 1x
The triangular thatched roofline and the dark double doors. If the silhouette
reads as "small barn" with no interior colour, the sprite works.

## Canvas & palette
- canvas: 64x64, base of the building sits on the ground line at y=63
- palette: custom, extracted/tuned from the reference and locked in
  `stable_palette.hex` (12 colours + transparent)
- colour budget: all 12 -- 4 materials, 3 tones each except the accent (2)

## Light
- direction: top-left
- the left roof slope, the left wall face and the left half of every log end
  take the key; the right side of each form falls to its shadow value and
  reaches the outline. Roof ridge is the single brightest edge.

## Style rules taken from the reference
- outline: dark keyline, `#1a1420` (the palette's darkest, warm near-black
  matching the reference's `#040409`/`#1f1718` ink)
- dither: none -- reference measured 0.0 dither density, flat cel shading
- hue shift: shadows rotate toward the cool/blue side, highlights toward warm
  gold, mirroring the reference's measured 15.4deg hue-shift
- level of detail: four materials only -- timber, stone, straw-thatch, and one
  cool accent (window shutter) for contrast against all the warm tones

## Animation
- frames: 3-frame ping-pong idle (thatch0 -> thatch1 -> thatch0), ~300/220 ms
- loop type: ping-pong, gentle and slow -- a breeze, not a storm
- what moves, what holds: only the loose straw tufts along the roof ridge and
  eaves sway 1px and swap a shadow/highlight pixel or two; the roof volume,
  the walls, the doors and the window hold completely still every frame

## Out of scope
Interior, characters, animals, background, the reference's barrel/crates/pig
motif, second roof material (tile), day/night lighting variants.
