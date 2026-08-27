---
name: pixel-art-studio
description: Start the live pixel-art viewer -- a local web page that shows the sprite being drawn, updating on every save, with animation playback, a stage time-lapse, craft findings, and download links. Use when the user wants to watch the work happen, wants a split screen with the drawing on one side, asks for a preview or a demo, or wants to download the finished PNG/GIF/spritesheet from a page.
license: MIT
compatibility: Python 3.8+ standard library only. Binds to 127.0.0.1; no external network access.
---

# Pixel-art studio

A local viewer for work done with the `pixel-art` skill. The user keeps the
terminal on one half of the screen and this page on the other; the page
re-renders every time a `.pxa` file is saved.

## Start it

```
px studio --dir workspace --open
```

`--dir` is the folder to watch (it recurses), `--port` defaults to 8765,
`--open` launches the browser. It prints the URL and how many sprites it found.

Run it in the background so it does not block your work:

```
px studio --dir workspace --port 8765 &
```

Tell the user the URL. Then draw as usual -- every `pxa.save` / file edit shows
up within about a third of a second.

## What the page gives them

- the current frame at 1-24x, nearest-neighbour, with an optional pixel grid
- view modes: normal, onion skin, value study, silhouette
- animation playback at the file's real per-frame timing, plus frame thumbnails
  and keyboard control (space, arrows, `g`)
- **replay history** -- plays through the `history/` snapshots as a time-lapse of
  how the sprite was built, which is what makes it a demo rather than a preview
- the palette with per-key pixel counts
- the live craft-check findings, updating as you fix them
- downloads: PNG at 1x/4x/8x, the `.pxa` source, the review sheet, and for
  animations the GIF and the spritesheet

## Make the time-lapse worth watching

The history panel is populated by snapshots, so take one at every stage:

```
px snapshot FILE --stage silhouette --note "shape only"
px snapshot FILE --stage flats      --note "local colours"
px snapshot FILE --stage shading    --note "one light, upper-left"
px snapshot FILE --stage cleanup    --note "jaggies and orphans"
px snapshot FILE --stage animation  --note "4-frame idle"
```

Each writes a PNG, a `.pxa` copy and the note into `history/` next to the sprite.

## Notes

- It watches `.pxa` files only, and skips `out/`, `review/`, `history/`,
  `.venv`, `node_modules`, `__pycache__`.
- Several sprites under the watched folder appear in the project dropdown.
- A `.pxa` that fails to parse shows its error on the page instead of the sprite.
- `brief.md` next to a sprite is displayed on the page, so the art direction sits
  beside the artwork.
- Stop it with ctrl-c, or `kill` the background job.
