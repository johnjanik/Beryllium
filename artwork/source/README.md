# Source: Beryllium art set v2

Supplied by the project owner on 3 November 2026. It replaces art set v1,
whose emblem (a red orb with horns) resembled the FreeBSD logo; v2 has no
horns, so Beryllium's mark cannot be mistaken for FreeBSD's own branding.
Licensed like the rest of `artwork/` (see `../README.md`).

`beryllium-art-sheet-v2.webp` is the art sheet exactly as supplied
(1536 x 1024, SHA-256
`9383e6b3da4c59dd55de59a95a2f0c42af46bc4b7c0582fb3b16c8db43b893f9`).
The checkerboard behind the artwork is painted into the image; it is not
transparency.

## What is taken from it

`branding/tools/extract-art-sheet` cuts these out and removes the
checkerboard (`--check` confirms the committed files match the sheet):

| File | On the sheet | Used for |
|---|---|---|
| `../logo/beryllium-emblem.png` (414 x 466) | top left: orb with "Be", two orbits, four electrons | icons from 48 px, lockups, `product_logo.svg`, onboarding page |
| `../logo/beryllium-orb.png` (282 x 274) | top, third from left: plain orb with "Be" | icons at 16 to 32 px; proportions of the vector glyph |
| `../logo/beryllium-orb-grey.png`, `../logo/beryllium-emblem-mono.png` | right column: grey orb, black silhouette | monochrome variants (not used by the build yet) |
| `../wordmark/beryllium-lockup.png`, `../wordmark/beryllium-lockup-dark.png` | middle row, left: emblem, rule, "Beryllium Browser" | repository README (dark variant: white lettering) |

`branding/tools/make-chromium-branding` then scales the logo masters to
`../icons/` (16 to 256 px).

## Not used

- The ten rounded-square icons at the lower right: they show three orbits;
  the design has two (owner's instruction, 3 November 2026).
- The size ramps at the lower left: the masters are scaled instead, which
  gives the exact sizes the browser needs.
- The second colour emblem (top middle) and the second and third lockups:
  variants of the ones above.
- The grey emblem (right column, top): its glossy highlights are the same
  light greys as the painted checkerboard and cannot be separated cleanly.

## Notes

The sheet is raster artwork at moderate resolution (the colour emblem is
about 410 px across). That covers the browser's largest icon (256 px); a
vector master would be needed for larger uses such as print.
