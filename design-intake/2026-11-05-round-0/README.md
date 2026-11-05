# Round 0: vector reconstruction of the art set v2 emblem (draft)

**Date:** 5 November 2026. **Status:** reviewed; see the outcome below
and [round 1](../2026-11-05-round-1/README.md). Nothing here is
used by the build, and `artwork/` and `branding/` are unchanged. Approved
masters move into `artwork/` only through a separate integration change
(the generator in `branding/tools/`, its tests and the port), after the
owner approves.

## What this is

A faithful vector rebuild of the current mark, not a redesign: the glossy
red orb with white "Be", two orbits, four electrons, as on art sheet v2
(`artwork/source/beryllium-art-sheet-v2.webp`). The raster masters cut
from that sheet top out at about 410 px; these SVGs scale to any size and
give the flat and one-colour versions the browser's vector icons need.

## Files

| File | What |
|---|---|
| `masters/beryllium-emblem-color.svg` | Full colour with gloss: orb (dark outline, red band, pale glass ring, deep-red body lit from the upper left, orange bounce lower right), two orbit tubes, four electrons, "Be" with a soft shadow |
| `masters/beryllium-emblem-flat.svg` | Solid fills only (rim red `#A00806`, orb red `#F40602`, white): the source for Chromium's colour `.icon` |
| `masters/beryllium-emblem-mono.svg` | One colour (`currentColor`), "Be" cut out, gaps where the front orbit and the orb pass over what is behind them: the source for theme-tinted and symbolic icons |
| `masters/beryllium-orb-{color,flat,mono}.svg` | The small mark: the orb with "Be", no orbits, filling the canvas with a 3% margin; for 16 to 32 px |
| `exports/beryllium-emblem-{color,flat,mono}-1024.png` | 1024 x 1024 renders, transparent |
| `previews/contact-sheet.png` | Current icons against the vector gloss and flat versions, 256 to 16 px, light and dark backgrounds |
| `previews/small-sizes-x4.png` | 32, 24, 22 and 16 px enlarged four times |
| `previews/original-vs-vector.png` | Original emblem, vector emblem, and the two overlaid |
| `tools/make-masters` | Writes all six SVGs (Python, fontTools); re-running it reproduces `masters/` exactly |
| `tools/render-svg.js` | Renders SVGs to PNG with the Chromium that Playwright provides |

All masters are 1024 x 1024 with a transparent background; letters are
outlines (Inter ExtraBold), so no font is needed to display them.

## How the geometry was measured

From `artwork/logo/beryllium-emblem.png` (414 x 466 px), in its pixels:

- **Orbits:** the visible band segments (outside the orb and the
  electrons) were reduced to their centre lines and each orbit fitted
  with a general ellipse (direct least squares) to its four segments.
  Both fits agree: semi-axes 234 and 81, tilted 54.2 degrees, centres 6 px
  either side of the mirror axis. The masters use the symmetric average.
  An ellipse with its tips at the electrons does not fit: the electrons
  sit just outside the tips and cover them.
- **Orb:** centre 13 px below the orbits' centre, radius 141.
- **Electrons:** top pair 162 px either side of the axis, bottom pair 169
  px (the art spreads the bottom pair a little wider); radius 36.
- **Tubes:** 28 px including the outline.
- **Letters:** cap height 0.71 of the orb radius, as in the art. Inter
  ExtraBold matches the art's letter weight better than Inter Bold (which
  the browser's vector icon uses today).
- **Colours:** sampled on a grid across the orb, its rim and an electron.

## Differences from the art, on purpose

- Exact mirror symmetry (the art drifts by a few pixels).
- "Be" centred on the orb; the art sets it about 12 px (0.09 of the radius)
  right of centre.
- The art's painted gloss is replaced by a few defined gradients, so the
  shine is cleaner and the same at every size.

## What the previews show

- From 48 px up, the flat version reads more clearly than either glossy
  one.
- At 16 px no version keeps "Be" legible: a pixel-fitted 16 px icon (and
  probably 22 and 24) has to be drawn by hand. That is the next stage.
- The one-colour emblem holds together because of the gaps.

## Decisions for the owner

1. Is this reconstruction faithful enough to be the master, or should a
   designer refine proportions (orbit width, electron size, letter size)
   first?
2. Small icons (16 to 32 px): glossy, or flat like the browser's own
   toolbar icons?
3. Inter ExtraBold for "Be" everywhere (the browser's vector icon would
   switch from Bold), or keep Bold?

## Licence

Copyright 2026 Beryllium Browser contributors, CC BY 4.0, like the rest of
the artwork. The Beryllium name and logo are reserved
([TRADEMARKS.md](../../TRADEMARKS.md)). Letter outlines are from Inter
(SIL Open Font License 1.1). The tools are GPL-3.0.

## Outcome (owner, 5 November 2026)

1. Faithful enough: this reconstruction is the master.
2. Small icons are flat.
3. Letters stay in Inter Bold; round 1 regenerates the masters with it.
