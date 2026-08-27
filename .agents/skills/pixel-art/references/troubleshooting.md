# Troubleshooting

## "It looks like a diagram, not art"

You drew shapes with `px edit` instead of placing pixels. The tool operations are
for mechanical work -- a rectangle of ground, a mirror, a shift. The parts that
carry the read (silhouette edges, faces, hands, the terminator) have to be
placed by hand in the grid text.

Also check: is there any hue shift at all in the ramps? Pure lighten/darken is
the single biggest tell.

## "It reads as a blob at 1x"

Look at the `VALUE` panel. Almost certainly the values are bunched. Push the
darkest darker and the lightest lighter, and check that the silhouette has holes
in it. `low-value-range` and `blocky-silhouette` in the linter are the same
complaint from two directions.

## "It looks inflated / like a balloon"

Pillow shading. You shaded by distance from the edge instead of by light
direction. Pick a direction, put it in `@meta light:`, and redo the shadow side
so it reaches the silhouette edge on one side. See `craft.md` section 4.

## "The lines look wobbly"

Run `px lint` and go to the `jaggies` and `doubles` coordinates. Fix the run
lengths so the sequence is constant or monotone. Most wobble is one pixel in a
staircase.

## "It looks noisy / dirty"

Too many single pixels, too many colours, or dither used as texture. In order:
`px fix FILE --orphans --dedupe --prune`, then look again, then cut colours by
hand until every colour describes a plane rather than a speck.

## "The animation stutters"

- `px anim drift` -- is something drifting?
- `px strip` -- do consecutive frames differ by a sensible amount? Look for the
  `dead-frame` and `pose-jump` findings.
- `px onion --frame N` -- in a smooth motion the ghosts are evenly spaced.
- Check the timing. Equal frame durations read mechanically; extremes should be
  held longer than passing poses.

## "The character grows between frames"

`volume-drift`. You redrew a frame instead of moving parts of the previous one.
Start again from `px anim add --copy-from` and translate bands of pixels.

## "The character slides on the ground"

`anchor-drift`. Set `anchor: bottom` in `@meta` and keep the feet line fixed on
every frame. The body moves over the feet, not with them.

## "Colours changed when I applied a palette"

`px palette apply` snaps every pixel to the nearest palette entry perceptually.
If two of your materials mapped to the same entry, they were already close in
colour -- pick a different entry for one of them by hand, or choose a palette
with more separation.

## "px import produced mush"

Expected. Downsampling averages; art decides. Use the import for the value
structure and redraw the read-carrying parts. If the source was upscaled pixel
art, check that `pixel_scale` in `px ref` detected it -- if it did, the import
recovers the original grid exactly and there is nothing to redraw.

## "Reading a JPEG reference fails"

Pillow is not installed. `px doctor --install` creates a project venv with it, or
`python3 -m pip install --user Pillow`. PNG references work without it.

## "The studio page is blank / not updating"

- The server prints how many sprites it found; if zero, point `--dir` at a folder
  that contains a `.pxa`.
- It watches `.pxa` files only, and ignores `out/`, `review/`, `history/`,
  `.venv`, `node_modules`.
- The live dot goes grey when the event stream drops; the page also polls every
  four seconds as a fallback.
- A parse error in a `.pxa` shows on the page instead of the sprite. Run
  `px lint FILE` to see it in full.

## "The lint output contradicts what I intended"

It often will. It measures geometry and knows nothing about intent. Keep the
finding, say which one you kept and why, and move on. What you must not do is
run it and ignore the result silently.
