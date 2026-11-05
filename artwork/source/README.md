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

## From the sheet to the masters

1. **Cut-outs** (`cutouts/`, 3 November 2026):
   `branding/tools/extract-art-sheet` cuts these out and removes the
   checkerboard (`--check` confirms they match the sheet).
2. **Vector masters** (5 November 2026): the geometry of
   `cutouts/beryllium-emblem.png` was measured (orbit ellipses fitted to
   the visible bands, orb, electrons, tube thickness, colours sampled) and
   rebuilt as SVG by `branding/tools/make-masters`, which writes
   `../logo/` and `../wordmark/`. The owner approved the rebuild as the
   master on 5 November 2026; the review rounds, with comparisons against
   the cut-outs, are in `design-intake/`.

Since then the build uses only the masters and what is made from them
(see `branding/README.md`). The cut-outs stay as the record of where the
geometry came from.

| Cut-out | On the sheet | Was used for, until 5 November 2026 |
|---|---|---|
| `cutouts/beryllium-emblem.png` (414 x 466) | top left: orb with "Be", two orbits, four electrons | icons from 48 px, lockups, WebUI logos; now the reference the masters were measured from |
| `cutouts/beryllium-orb.png` (282 x 274) | top, third from left: plain orb with "Be" | icons at 16 to 32 px; proportions of the vector glyph |
| `cutouts/beryllium-orb-grey.png`, `cutouts/beryllium-emblem-mono.png` | right column: grey orb, black silhouette | not used |
| `cutouts/beryllium-lockup.png`, `cutouts/beryllium-lockup-dark.png` | middle row, left: emblem, rule, "Beryllium Browser" | repository README header; the wordmark master keeps its layout |

## Not used

- The ten rounded-square icons at the lower right: they show three orbits;
  the design has two (owner's instruction, 3 November 2026).
- The size ramps at the lower left: the small icons are drawn for each
  size instead.
- The second colour emblem (top middle) and the second and third lockups:
  variants of the ones above.
- The grey emblem (right column, top): its glossy highlights are the same
  light greys as the painted checkerboard and cannot be separated cleanly.

## Differences between the masters and the sheet

Made on purpose and approved with the masters: exact mirror symmetry,
"Be" centred on the orb (the sheet sets it slightly right), a few defined
gradients in place of the painted gloss, letters in Inter Bold, and in
the wordmark the two lines left-aligned at Inter's natural spacing (the
sheet's lettering is another typeface, set to equal widths).
