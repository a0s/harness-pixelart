# Craft

The rules a pixel artist would state in a critique. Each one is a real
constraint with a real reason, and most of them are what `px lint` measures.
Break any of them on purpose; never by accident.

---

## 1. The silhouette carries the read

At 32 px a viewer identifies a sprite by its outline before they see a single
interior pixel. Everything else is decoration on top of a shape that already
worked.

**Test it:** the `SILHOUETTE` panel in `px view`. Fill it with one colour and ask
whether you would recognise the subject. If not, no amount of shading saves it.

**How to fix a silhouette that does not read:**

- Cut negative space *into* the shape. Gap between the arm and the ribs, gap
  between the legs, notch under the chin, space between the weapon and the body.
  Holes are what make a shape describable.
- Exaggerate the one feature that identifies the subject. A wizard is a hat. A
  knight is pauldrons. A frog is the crouch. At small sizes, characteristic beats
  accurate every time.
- Break symmetry. A perfectly mirrored figure looks dead and gives the eye
  nothing to travel along. Shift a shoulder, angle the head, let one arm hang
  differently.
- Avoid filling the bounding box. Above ~90% filled you have drawn a rectangle;
  the linter flags this as `blocky-silhouette`.

**Rule of thumb for a character:** the widest part should be roughly 1.5-2 head
widths, and there should be at least two clear holes in the silhouette.

---

## 2. Lines are made of clusters, not strokes

You do not draw a line and then fix it. You place runs of pixels whose lengths
form a rhythm.

A clean pixel line is a sequence of runs with a consistent or smoothly changing
length:

```
good  3-3-3-3        a steady 3:1 slope
good  4-3-2-1        a curve accelerating away
bad   3-1-3          a dent -- this is a JAGGY
bad   1-1-2-1-1      a stutter -- this is a DOUBLE in a 45-degree line
bad   2-3-2-4-2      noise; the eye cannot find the slope
```

**Jaggy** -- one short run stranded among longer ones. The eye reads it as damage
to the line. `px lint` reports `jaggies` with coordinates.

**Double** -- a two-pixel run inside an otherwise one-pixel-per-step diagonal.
The 45-degree slope stutters. Reported as `doubles`.

The fix is always the same: adjust the run lengths so the sequence is monotone
or constant. Usually that means moving one pixel, not redrawing the line.

**Curves:** a good pixel curve is a run-length sequence that changes by one at a
time -- `5-4-3-2-1-1-2-3-4-5` for a circle quadrant and back. Two consecutive
equal runs at the tightest part of a curve is where curves usually go wrong.

---

## 3. Clusters, not confetti

Isolated single pixels of a colour read as dirt. The eye cannot integrate them
into a form, so they register as noise and the sprite looks unresolved.

Group pixels of the same colour into clusters of at least 2-3, in shapes that
describe something: a plane turning away from the light, a fold, a strap.

Legitimate single pixels: an eye, a specular glint on metal, a spark, a rivet,
a nostril. All of them deliberate, all of them few.

`px lint` reports `orphan-pixel`; `px fix FILE --orphans` absorbs them
mechanically, which is right for cleanup noise and wrong for eyes -- check
before running it.

---

## 4. One light direction, held everywhere

Declare it in `@meta light:` and obey it on every form: the same side lit, the
same side dark, on the head, the torso, the boots, the sword, the cape.

**Pillow shading** is the failure: brightness that follows the silhouette
inward, so everything looks inflated and nothing looks lit. It happens when you
shade each region by "darker near the edge" instead of by where the light is.

`px lint` measures it two ways -- the distance between the centre of mass of the
light pixels and that of the dark pixels, and the correlation between brightness
and distance-from-edge. If it reports `pillow-shading`, the fix is structural:

- Pick the light. Say, upper-left.
- On every form, the upper-left facing planes get the light value, the
  lower-right facing planes get the shadow value, and the terminator between
  them runs across the form, not around it.
- Let the shadow side reach the silhouette edge. A rim of light all the way
  around is what makes pillow shading look like pillow shading.
- Bounce light is a *small* lift on the lower-right edge, one value step, used
  sparingly, and it never equals the key light.

---

## 5. Banding

Two adjacent values running parallel along the same contour for a long stretch.
It reads as a painted stripe rather than a surface turning.

```
bad                     better
MMMMMMMMM               MMMMMMMMM
%%%%%%%%%               %%M%%%M%%
@@@@@@@@@               @@@@%@@@@
```

Fix by staggering the boundary, letting the two values interlock, or by making
the transition happen over a different length on each part of the form. The
linter reports `banding` with the coordinate where a run of 5+ starts.

Related: **doubling the outline**. An outline immediately followed by the
darkest shade of the fill produces the same stripe effect. Let the fill's dark
value touch the outline only where the form genuinely turns.

---

## 6. Outlines

Three conventions, pick one and stay with it:

- **Full dark outline.** Every silhouette edge gets the darkest colour. Reads on
  any background, standard for small game sprites. Safest choice.
- **Selective outline.** Outline present on the shadow side, absent or lighter
  on the lit side. More painterly, better for larger sprites, needs a confident
  light direction.
- **No outline.** Only when the sprite lives on a known background.

Whichever you choose: an outline is a *colour*, not a black border. A dark
version of the material underneath (dark blue under blue cloth, dark brown under
leather) sits in the image; pure black cuts a hole in it.

Interior lines -- where two materials meet inside the silhouette -- should
usually be one value step darker, not the outline colour. Using the outline
colour inside chops the sprite into stickers.

---

## 7. Anti-aliasing

AA means placing an intermediate value on the *inside* of a corner to soften a
transition the eye would otherwise read as a step.

Rules:

- AA the corners of a curve, not the straight runs.
- One intermediate pixel per corner. Two is already a blur.
- The intermediate value must exist in the ramp. Do not invent a colour for it.
- **Never AA the outer silhouette of a sprite with a transparent background.**
  You do not know what is behind it; those pixels become a dirty fringe over
  whatever the sprite lands on. Interior AA only. `px lint` reports `outer-aa`.
- At very small sizes (16 px and under) skip AA almost entirely -- there is not
  enough room, and it just makes the sprite muddy.

---

## 8. Dithering

Dithering mixes two values in a pattern to suggest an intermediate one, and to
give a surface texture. It is a decision, not a filter.

Use it for:

- a gradient across a large surface with a small palette (sky, metal, ground)
- texture that says "rough" (stone, bark, cloth weave)
- a soft terminator where a form turns very gradually

Do not use it:

- as a uniform 50% checkerboard over the whole sprite -- that is the signature of
  an automatic conversion, and `px lint` reports it as `dither-spray`
- on small sprites where a checkerboard reads as noise rather than texture
- across a boundary you want to read as sharp

The good patterns have *density*: dense near the shadow, thinning toward the
light, so the eye reads a gradient rather than a texture patch.

```
solid  ########      dense  #.#.#.#.      sparse  #...#...      light  ........
```

`px palette apply FILE --palette X --dither bayer4` is available when you truly
want an ordered pattern applied mechanically, but hand-placed dithering is
almost always better on a sprite.

---

## 9. Detail budget

Small canvases have room for very few ideas. A 16x16 sprite holds one: a
silhouette and a colour. A 32x32 holds three or four: silhouette, one costume
element, a face, a weapon. A 64x64 can carry material distinctions and folds.

Symptoms of overspending the budget:

- more colours than the canvas can distinguish (`colour-density`)
- colours used on one or two pixels each (`stray-colour`)
- detail smaller than the eye can resolve at 1x -- check the `1X ACTUAL` panel;
  if you cannot see it there, delete it and spend those pixels on the silhouette

---

## 10. Reading the linter

`px lint` is advisory. It is right about geometry and blind about intent.

- `error` -- the file is broken. Fix it.
- `warn` -- probably a mistake. Look at the coordinates and decide.
- `info` -- an observation. Often it is telling you something you did on purpose.

When you keep a finding, say so in your report and say why. "12 orphan pixels
kept: they are the sparks on the anvil" is a good answer. Silently ignoring the
output is not.
