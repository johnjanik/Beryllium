# Beryllium branding

## Contents

- `kit/`: Beryllium art set v2 (3 November 2026): the art sheet as
  supplied, and the masters cut from it. See `kit/README.md`.
- `chromium/`: the files the browser build uses, generated from the
  masters by `tools/make-chromium-branding` and committed. The build does
  not run the tools.
- `tools/extract-art-sheet`: cuts the masters out of the sheet and removes
  the painted checkerboard (needs Pillow, numpy and scipy).
- `tools/make-chromium-branding`: generates `chromium/` (needs Pillow,
  fontTools and Inter Bold). Run it after changing the masters, then
  `freebsd/tools/sync-port`. Both tools take `--check` to confirm the
  committed files match.

## Where each asset is used

| Asset | Source | Used for |
|---|---|---|
| Product and desktop icons, 48 to 256 px | colour emblem (orb, "Be", two orbits) | window and taskbar icon, About page, `share/icons/hicolor/` |
| Product and desktop icons, 16 to 32 px | plain colour orb with "Be" | the same places at small sizes, `favicon_product`; the orbits would blur into the orb |
| Lockups: emblem + "Beryllium" | colour emblem, Inter Bold, near-black or white lettering | `product_logo*.png` (140 x 32) and `product_logo_name_22*.png` (97 x 22), at 100% and 200% |
| `product_logo.svg`, onboarding page logo | colour emblem, embedded as PNG | Chromium WebUI pages accept `data:` images |
| Vector glyph: plain orb with "Be" | drawn to the plain orb's proportions, letters from Inter Bold | Chromium `.icon` files (address bar, menus, notifications; colour and theme-tinted monochrome), the 22 px monochrome PNG |
| Repository README header | `kit/masters/lockup-color.png` and `lockup-color-dark.png` | GitHub light and dark themes |

The port applies `chromium/beryllium_resources.txt` with Helium's
`utils/replace_resources.py` after Helium's own list, so every Helium logo
is replaced (a unit test checks this against Helium's list on each Helium
update). Helium's generic page favicons (bookmarks, history, settings and
similar) are kept; they carry no Helium mark.

## Open items

- **Vector master.** The art is raster (the emblem is about 410 px
  across): enough for the browser, not for print or very large displays.
- **Licence.** State the licence of the artwork (the repository is
  GPL-3.0; logos are often licensed separately). Inter is under the SIL
  Open Font License 1.1, which permits its use in logos.
- Chromium's `product_logo_animation.svg` is not replaced; where Chromium
  uses it on Linux has not been checked.
