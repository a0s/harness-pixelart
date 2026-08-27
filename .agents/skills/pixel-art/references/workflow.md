# Workflow, in full

The stage list from SKILL.md with the reasoning and the commands spelled out.
Each stage ends the same way: render, look, lint, snapshot.

---

## 0. Set up

```
px project workspace/knight --name knight
cp ~/refs/*.png workspace/knight/refs/
px studio --dir workspace --open      # optional, for a watching human
```

`px project` creates `brief.md`, `refs/`, `review/`, `history/`, `out/`.

---

## 1. Reference intake

```
px ref workspace/knight/refs/*.png --out workspace/knight
```

Read the output and **open `ref_contact.png`**. You are looking for:

- **native resolution** -- if it says `scale x8`, the reference is a 32x32 sprite
  displayed at 256 px, and 32x32 is your canvas, not 256
- **palette and ramps** -- how many colours, how they group
- **value range** -- narrow means a soft, muted style; wide means high contrast
- **hue shift** -- 0 degrees means flat lighten/darken; 25+ means a painterly ramp
- **dither density** -- above ~0.05 the style uses visible dithering
- **outline** -- whether there is a dark keyline convention

Then fill in `brief.md`. Concretely, not aspirationally:

```markdown
## Subject
Armoured knight, three-quarter front, standing at rest, greatsword planted.

## Read at 1x
The pauldrons and the sword. Everything else can be mush.

## Canvas & palette
- canvas: 32x32
- palette: sweetie-16, locked
- colour budget: 12

## Light
- direction: upper-left
- key on the left pauldron and helmet crown; right side falls to the outline

## Style rules from the references
- outline: full dark keyline, palette darkest
- dither: none
- hue shift: ~22 degrees, shadows to violet
- detail: three materials only (steel, cloth, leather)

## Animation
- 4-frame ping-pong idle, 260/180/260/180 ms
- moving: chest, hips, cloak hem, unweighted heel
- holding: sword, feet, head silhouette

## Out of scope
Face detail, background, damage states.
```

Ask the user only what the brief cannot answer: intended use, hard size
constraints, whether the palette is negotiable. Everything else you decide, and
you tell them what you decided.

---

## 2. Silhouette

```
px new workspace/knight/knight.pxa --size 32x32 --palette sweetie-16 --light top-left
```

Then write the shape into the grid in a single colour -- the darkest one. Big
forms first: head mass, torso mass, leg masses, weapon. No interior detail at
all.

```
px view workspace/knight/knight.pxa --scale 12
```

**Open the PNG.** Look only at the `SILHOUETTE` panel and ask: would I know what
this is? Then look at `1X ACTUAL` and ask the same question again.

```
px lint workspace/knight/knight.pxa
px snapshot workspace/knight/knight.pxa --stage silhouette
```

Do not proceed until the silhouette reads. This is where the sprite is won or
lost, and it is cheap to fix here and expensive later.

---

## 3. Flats

Replace regions of the silhouette with the local colour of each material. One
colour per material. Keep the outline.

Check in the `VALUE` panel that the materials separate. Two touching materials
at the same value will merge at 1x -- change one now, before you build a ramp on
top of it.

```
px view FILE ; px lint FILE ; px snapshot FILE --stage flats
```

---

## 4. Shading

Work one material at a time, always in the same light.

1. Decide where the terminator falls on that form -- the line where it turns away
   from the light. It runs *across* the form.
2. Fill the away-side with the shadow value, all the way to the silhouette.
3. Add the lit value only on the planes directly facing the light. Less area than
   you expect.
4. Add ambient occlusion where forms meet: one pixel of the next value down,
   under the chin, in the armpit, at the boot line.
5. Specular highlights last, on metal only, a few pixels.

Generate ramps rather than guessing:

```
px palette ramp '#3b5dc9' --steps 4 --hue-shift 24
```

Then `px view`, look, and specifically check the linter for `pillow-shading` and
`banding`.

```
px snapshot FILE --stage shading
```

---

## 5. Cleanup

```
px lint FILE --verbose
```

Work the list. Typical order:

1. `invalid-document` -- always first
2. `jaggies` / `doubles` -- go to the coordinates and fix the run lengths
3. `banding` -- stagger the boundary
4. `orphan-pixel` -- absorb, or confirm they are eyes and glints
5. `redundant-colour` / `stray-colour` -- `px fix FILE --dedupe --prune`
6. `outer-aa` -- harden the silhouette

Then look again. Cleanup changes the read more than you expect.

```
px snapshot FILE --stage cleanup
```

---

## 6. Animation

See `references/animation.md`. Short version:

```
px anim add FILE idle1 --copy-from idle0
# edit the frame
px anim drift FILE
px onion FILE --frame 1     # open it
px strip FILE               # open it
px anim timing FILE --ms 260,180,260,180
px anim gif FILE            # open it
px snapshot FILE --stage animation
```

---

## 7. Delivery

```
px export FILE --fps 8
```

Then report:

- what you drew, at what size, in how many frames
- the palette and its size, and where it came from
- which craft findings remain and why you kept them
- the paths of the outputs

If the studio is running, tell the user it is showing the finished loop and that
every export is downloadable from the page.

---

## Converting an existing image

`px import` is a starting point, never a deliverable:

```
px import refs/concept.png --out knight.pxa --size 48 --colors 12
```

It area-averages down, snaps to a palette, and hands you a draft. Machine
downsampling does not know which pixel carries the read, so the draft will have
mush where the eyes should be and a silhouette full of jaggies. Treat it as a
value study: fix the silhouette by hand, redraw the face, rebuild the ramps.
Then run the normal cleanup stage.

State plainly in your report that the result began as a conversion.
