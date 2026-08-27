# Colour

## Why a limited palette

Not nostalgia. A small palette forces every colour to carry meaning, keeps
values separable at small sizes, and makes the sprite hold together as one
object. Fewer colours consistently look *more* professional than more colours.

Budgets that work:

| canvas | colours (excl. transparent) |
| --- | --- |
| 16x16 icon | 4-6 |
| 32x32 character | 8-14 |
| 64x64 character | 12-24 |
| tileset | 16-32 shared across every tile |

More than that and you are usually not making distinctions the eye can see.
`px lint` warns at `colour-density` when the count is high for the filled area.

---

## Ramps

A **ramp** is an ordered run of 3-5 colours describing one material from its
darkest shadow to its brightest light. Sprites are built from a handful of
ramps, and ramps are shared: leather and hair can use the same warm ramp; steel
and sky can share the cool one.

A ramp changes three things at once:

1. **Value** -- evenly spaced, and covering a real range. If your darkest and
   lightest are 20 points apart on a 0-100 scale, the sprite will read as a flat
   blob. `px lint` reports `low-value-range` under 35.
2. **Hue** -- shadows rotate toward the cool end (blue/violet), lights toward the
   warm end (yellow/orange). This is what makes pixel art look painted instead
   of plastic. A ramp that only changes value is reported as `flat-ramp`.
3. **Saturation** -- highest in the middle of the ramp, falling off at both ends.
   Fully saturated darks look like plastic; fully saturated lights look like
   neon.

Generate one:

```
px palette ramp '#b13e53' --steps 5
#3d1a2e  h330 s 39 l 17
#7c2b41  h348 s 48 l 32
#b7495a  h352 s 45 l 50
#dc9088  h  8 s 51 l 70
#f4e4d8  h 24 s 52 l 90
```

Tune the rotation with `--hue-shift` (degrees, 15-30 is normal, 40+ is stylised),
`--shadow-hue` and `--light-hue`.

**Shared darkest value.** Letting every ramp converge on one near-black at the
bottom unifies the sprite and gives you a single outline colour. This is why
16-colour palettes have exactly one very dark entry.

---

## Value first

Design the sprite in values before you commit to hues. The `VALUE` panel in
`px view` is the check: convert to greyscale and confirm that every part you
want separable *is* separable.

Common failure: a red tunic and green trousers that look great in colour and
merge into one grey mass in value. Two materials that touch must differ by at
least one clear value step.

Plan roughly:

- background / darkest: the outline and the deepest shadow
- 25-40%: shadow planes
- 45-60%: the local colour of most materials -- the bulk of the sprite
- 70-85%: lit planes
- 90%+: specular highlights only, a handful of pixels

If most of your sprite sits in the top third, it will glow and lose form. If
most sits in the bottom third, it will be a hole.

---

## Working inside a locked palette

When the user names a palette (or you extracted one from references), it is a
constraint, not a suggestion.

```
px palette list                       # bundled sets
px palette get lospec:slug --out p.hex
px palette apply FILE --palette p.hex  # snap an existing sprite
```

Inside a fixed palette:

- Find the ramps that already exist in it: `px ref` prints them, and
  `palettes.ramps_of()` computes them. Most curated palettes are built as 4-6
  ramps plus a few accents.
- Assign one ramp per material before drawing. Write the assignment into the
  `@palette` names (`% #29366f cloth-shadow`) so the file documents itself.
- Do not fight the palette. If it has no true green, the character does not wear
  green.
- Accent colours (the one hot pink in a mostly blue palette) are for the single
  element that must draw the eye. Spend them once.

---

## Extracting a palette from references

```
px ref refs/*.png --colors 16 --out .
```

Gives you, per reference: the palette, the ramps it clusters into, the value
range, the measured average hue shift, dither density, and whether it uses a
dark keyline. Use these numbers to write the brief. If three references disagree,
the `brief` section merges them -- but prefer one reference's discipline over an
average of three, since an averaged palette usually has no ramps at all.

`px palette extract IMG --colors 12 --out p.hex` when you only want the colours.

---

## Colour choices that consistently work

- **Warm light, cool shadow** (or the reverse for moonlight/underwater). Never
  neutral both ways -- that is the plastic look.
- **Ambient occlusion** where forms meet: one step darker than the shadow value,
  a single pixel wide, under the chin, in the armpit, where the boot meets the
  ground. Cheap and very effective.
- **Skin** needs at least three values and a hue shift toward red in the shadow,
  toward yellow in the light. Two-value skin looks like a mask.
- **Metal** is high contrast with a hard terminator and a tiny near-white
  specular. Cloth is low contrast with a soft terminator and no specular. Getting
  these two backwards is the most common material mistake.
- **Black** is rarely #000000. Use the palette's darkest colour, which almost
  always has a hue.
