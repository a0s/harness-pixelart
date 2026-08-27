# Animation

Multi-frame work is where pixel art usually falls apart -- not because the poses
are wrong, but because the character quietly changes size, mass or ground
contact between frames. Everything here is aimed at that.

---

## Before the first extra frame

Finish the base pose. Silhouette, flats, shading, cleanup, lint. Animating an
unfinished sprite means fixing every mistake N times.

Then decide three things and write them into `@meta`:

- **anchor** -- what must not move. `anchor: bottom` for anything standing
  (feet stay on the ground line), `center` for something spinning or floating.
  `px anim drift` enforces it.
- **loop type** -- cycle (walk, idle), ping-pong (breathing, hover), or one-shot
  (attack, hit).
- **frame count** -- fewer than you think. 2 frames make a convincing idle,
  4 a good one. 4-6 for a walk cycle, 5-8 for an attack.

---

## Frames are made by moving parts, not by redrawing

Copy the previous frame, then move specific bands of the body:

```
px anim add FILE idle1 --copy-from idle0
```

Then edit. A 32x32 idle frame typically differs from its neighbour by 20-100
pixels, not by everything. `px anim drift` prints the change ratio: below 0.4%
the frame is dead and should be deleted or given real motion; above 42% you have
drawn an unrelated pose and the loop will jump.

---

## Idle

The request "a standing swordsman shifting his weight and moving his hips" is
the canonical idle. It is built from four ingredients, and you rarely need all
four:

1. **Breath.** The chest band rises and falls one pixel. The head follows one
   frame later, or the neck compresses instead.
2. **Weight shift.** The hips translate 1 px toward the supporting leg; the
   shoulders counter-translate the other way. This is the single most
   life-giving thing you can do, and it costs two pixels of movement.
3. **Ground contact.** The unweighted heel lifts by one pixel, or the toe does.
   Never both feet at once on a standing idle -- that reads as a hop.
4. **Secondary motion.** Cape, hair, scarf, a hanging strap: these follow the
   body one frame *late* and overshoot slightly before settling. Late-and-
   overshoot is what makes cloth look like cloth.

A four-frame ping-pong idle:

```
f0  neutral
f1  hips +1 right, body sinks 1, left heel up      (weight on the right leg)
f2  neutral
f3  hips -1 left,  body sinks 1, right heel up     (weight on the left leg)
```

Held objects stay put. A sword planted on the ground does not move while the
body breathes around it -- that contrast is what sells the weight.

Timing: hold the extremes longer than the passing poses. `260,180,260,180` ms
reads as breathing; four equal frames read as a machine.

```
px anim timing FILE --ms 260,180,260,180
px anim timing FILE --fps 8
```

---

## Walk

Six frames is the standard budget. Order matters more than drawing quality:

```
1 contact      forward foot lands, body at its lowest
2 down         weight passes onto it, body lowest, knee bent
3 passing      free leg passes the standing one, body at its HIGHEST
4 contact      mirrored
5 down         mirrored
6 passing      mirrored
```

Rules:

- The body bobs vertically. Highest on the passing pose, lowest on the down
  pose. Without this the character skates.
- Arms swing opposite to legs. Always.
- The head stays within 1-2 px vertically -- more and the character looks like it
  is jumping.
- Frames 4-6 are usually frames 1-3 mirrored *if* the character is symmetric.
  If it is not (sword on one hip, cape on one side), draw them properly.
- Test the ground contact: `px anim drift FILE` reports `anchor-drift` when the
  feet line wanders.

---

## Attack

Three phases, unequal timing:

```
anticipation   1-2 frames, slow (~200 ms). Wind up AWAY from the target.
strike         1-2 frames, fast (~40-60 ms). The pose the player remembers.
recovery       2-3 frames, medium (~120 ms), settling back to idle.
```

The anticipation frame is what makes a hit feel heavy. Skipping it is the most
common mistake. On the strike frame, exaggerate: the arm can leave correct
proportion, the weapon can smear into a wide arc shape, the body can lean past
its balance point. One frame of exaggeration is invisible individually and
essential in motion.

A smear frame -- the weapon drawn as a translucent arc rather than an object --
is a legitimate technique and costs one frame.

---

## The drift check

```
px anim drift FILE
```

Compares every frame to the first:

| finding | meaning | fix |
| --- | --- | --- |
| `volume-drift` | filled pixel count moved more than 12% | the character is gaining or losing mass; you redrew instead of moving |
| `height-drift` | bounding box height changed more than 2 px | squash and stretch must be deliberate |
| `width-drift` | bounding box width changed | usually an arm drifting outward frame by frame |
| `anchor-drift` | the ground contact line moved | the character is sliding or floating |
| `colour-dropped` | a colour covering 8+ px on frame 1 is missing here | you forgot to carry a material across |
| `dead-frame` | fewer than 0.4% of pixels change | the frame does nothing |
| `pose-jump` | more than 42% of the canvas changes | needs a breakdown frame between |

Deliberate squash and stretch will trigger `height-drift`. That is fine -- say so
and move on.

---

## Reviewing motion

You cannot judge animation from a filmstrip alone; you also cannot judge it from
a GIF you never look at. Do both:

```
px strip FILE --scale 8          # every frame, side by side, numbered
px onion FILE --frame 2          # frame 2 over its neighbours: prev blue, next red
px anim gif FILE --fps 8         # then open the GIF
```

Onion skin is how you catch a limb that jumps: in the onion render a smooth
motion shows evenly spaced ghosts, a broken one shows a gap.

If a human is watching, `px studio` plays the loop live at its real timing and
updates as you save.

---

## Spritesheet output

```
px export FILE --fps 8
```

Writes individual PNGs at 1x/2x/4x, a spritesheet with a JSON manifest (frame
rectangles and per-frame durations), a GIF, the palette in .hex and .gpl, and an
Aseprite .lua rebuild script. `px anim gif` alone if the GIF is all you need.
