# Round 1: masters with Inter Bold, hand-fitted small icons, vector wordmark

**Date:** 5 November 2026. **Status:** for review. Nothing here is used by
the build; `artwork/` and `branding/` are unchanged.

## Owner's decisions on round 0 (5 November 2026)

1. The round-0 reconstruction is faithful enough to be the master.
2. Small icons are flat.
3. The letters "Be" stay in Inter Bold (round 0 used ExtraBold), as in the
   browser's built-in vector icon.

## What changed from round 0

- **Letters:** Inter Bold, cap height still 0.71 of the orb radius.
- **Orb highlight:** the small hard white spot at the upper left is
  replaced by a soft reflection along the inner rim. At wordmark and
  icon sizes the spot sat just above the "B" and read as an apostrophe.
- **New:** hand-fitted small icons, the full proposed icon set, and the
  wordmark.

## Files

| File | What |
|---|---|
| `masters/beryllium-emblem-{color,flat,mono}.svg` | The emblem, 1024 x 1024: gloss, flat, one colour (`currentColor`, "Be" cut out) |
| `masters/beryllium-orb-{color,flat,mono}.svg` | The small mark (orb with "Be", no orbits) |
| `masters/beryllium-wordmark-on-light.svg` | Lockup with near-black lettering (`#060606`), for light backgrounds |
| `masters/beryllium-wordmark-on-dark.svg` | The same with white lettering, for dark backgrounds |
| `icons/beryllium-{16,22,24,32}.png` | Hand-fitted flat icons |
| `icons/beryllium-{48,64,128,256}.png` | The colour emblem rendered from its master |
| `exports/beryllium-emblem-{color,flat,mono}-1024.png` | 1024 px renders, transparent |
| `exports/beryllium-wordmark-on-{light,dark}-924.png` | Wordmark at 924 x 272 (twice the README header size), transparent |
| `previews/icon-set.png` | Current icon set against round 1, 256 to 16 px, light and dark |
| `previews/small-icons-x8.png` | 32, 24, 22 and 16 px enlarged eight times, and at actual size on white, dark, and KDE Breeze light and dark |
| `previews/wordmark.png` | Current README lockups (top) against the vector wordmark (bottom) |
| `tools/make-masters` | Writes all eight SVGs (Python: fontTools, uharfbuzz; Inter Bold and Regular) |
| `tools/make-small-icons` | Writes the four hand-fitted icons (Python: Pillow) |
| `tools/render-svg.js` | Renders SVGs to PNG with Playwright's Chromium |

Both tools reproduce the committed files exactly. The 48 to 256 px icons
and the exports are `render-svg.js` renders of the masters.

## Small icons (16, 22, 24 and 32 px)

Flat, as decided: rim `#A00806`, orb `#F40602`, white letters. The orb is
drawn smooth; the letters are drawn pixel by pixel, following Inter Bold's
shapes at each size, with vertical stems on whole pixels so they stay
sharp:

| Size | Cap height | Letters |
|---|---|---|
| 16 | 7 px | 2 px stems; at this size the letters are slightly heavier than Bold, for legibility |
| 22 | 8 px | 2 px stems, half-white pixels on the curves |
| 24 | 9 px | as 22 |
| 32 | 11 px | as 22 (hand-fitted too: the vector render was soft next to the 24) |

From 48 px the icons show the full emblem in colour, as today.

## Wordmark

The layout of the current lockup (`artwork/wordmark/beryllium-lockup.png`):
emblem, a thin vertical rule, then "Beryllium" in Inter Bold over
"Browser" in Inter Regular, left edges aligned. Text is outlines, shaped
with HarfBuzz so Inter's kerning applies. Natural size 462 x 136 px; it
scales freely.

Differences from the current lockup:

- **Typeface:** the art's lettering is not Inter. Inter is wider in bold
  and narrower in regular, so the two lines are left-aligned at natural
  spacing instead of being set to the same width, and the text is a
  little smaller (cap heights 47 and 40 against 51 and 43).
- **Emblem:** the vector master, slightly narrower than the art's lockup
  emblem.
- **Dark version:** no white specks around the emblem (the current dark
  lockup kept some from the art sheet's checkerboard).

## Next: integration (a separate change, after approval)

- `artwork/`: add the vector masters, replace `icons/` and `wordmark/` with
  these renders; record the masters' provenance in `artwork/source/README.md`.
- `branding/tools/make-chromium-branding`: take the icons from here
  instead of scaling the raster masters; derive the Chromium lockups
  (140 x 32, 97 x 22) from the wordmark masters, and the `.icon` glyphs
  from the flat and one-colour masters.
- `freebsd/tools/tests/test_branding.py`: the layout rules for `artwork/`.
- README header: the wordmark (SVG or the 924 px PNGs).
- Rebuild the port; check the window and taskbar icon, About page,
  address bar, menus, notifications and the onboarding page in KDE Plasma.

## Licence

Copyright 2026 Beryllium Browser contributors, CC BY 4.0, like the rest of
the artwork. The Beryllium name and logo are reserved
([TRADEMARKS.md](../../TRADEMARKS.md)). Letter outlines are from Inter
(SIL Open Font License 1.1). The tools are GPL-3.0.
