# harness_pixelart

A pipeline for making real, hand-crafted pixel art -- from reference images and a
description to a finished, craft-checked sprite or animation.

The whole thing is one skill plus one command. It works identically in Claude
Code, Codex CLI, and anything else that reads the Agent Skills standard.

## Layout

```
.agents/skills/          the skills themselves (the Agent Skills REPO scope)
  pixel-art/             the pipeline: SKILL.md, scripts/, references/, assets/
  pixel-art-studio/      the live viewer
.claude/skills           symlink -> ../.agents/skills
AGENTS.md                this file
CLAUDE.md                symlink -> AGENTS.md
bin/px                   the toolchain entry point
workspace/               projects: one folder per sprite
```

Nothing is duplicated between agents. `.claude/` holds symlinks only, so a change
to a skill is a change everywhere at once.

## Working here

When a request involves pixel art, sprites, spritesheets, retro game art,
limited palettes, dithering or sprite animation, **use the `pixel-art` skill**
and follow it. It is not a set of suggestions -- the stage order and the
review loop are what make the output look drawn rather than generated.

The short version of the contract:

1. Study the references with `px ref` before choosing anything.
2. Work in stages: silhouette, flats, shading, cleanup, animation.
3. After every editing pass, run `px view` and **open the resulting image**.
   Work you have not looked at is a guess.
4. Run `px lint` before calling anything finished. Address every finding or say
   why you kept it.
5. For animation, run `px anim drift` after every change.

## The toolchain

`bin/px` is the single command surface. `px doctor` checks the environment;
`px --help` lists everything. It runs on the Python standard library alone --
Pillow is optional and only needed to read JPEG/WebP references.

## The format

Sprites are `.pxa` files: a palette of one-character keys plus a character grid
per frame, as plain text. You edit them with ordinary file tools. Palette keys
are ordered by density so the raw text reads as a rough picture of the sprite.

```
@palette
. #00000000 transparent
@ #1a1c2c   ink
M #3b5dc9   cloth

@frame idle0
....@@@@....
...@MMMM@...
```

## Live viewer

`px studio --dir workspace --open` serves a page on 127.0.0.1 that re-renders on
every save, plays animations at their real timing, replays the stage history as a
time-lapse, shows the craft findings, and offers every export as a download.
Terminal on one half of the screen, page on the other.

## House rules

- Everything in this repository is written in English, including comments and
  documentation, regardless of the language of the conversation.
- Integer scaling only. Pixel art resampled to a non-integer size is destroyed.
- Never present output from `px import` (raster conversion) as finished pixel
  art. It is a draft to redraw.
- Bundled palettes carry their authors' credit in
  `.agents/skills/pixel-art/assets/palettes/ATTRIBUTION.md`. Keep it accurate.
