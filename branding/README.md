# Beryllium branding

## Contents

- `kit/`: the Beryllium branding kit v1, supplied by the project owner on
  2 November 2026, unchanged except that `source/beryllium-emblem.svg` is
  left out (it only wraps `master/beryllium-emblem-master-2048.png` in an
  SVG, 3 MB). See `kit/README.md` for the kit's own notes and palette.
- `chromium/`: the files the browser build uses, generated from the kit by
  `tools/make-chromium-branding` and committed. The build does not run the
  generator.
- `tools/make-chromium-branding`: the generator (needs Pillow, fontTools
  and Inter Bold). Run it after changing the kit, then
  `freebsd/tools/sync-port`. `--check` confirms the committed files match.

## Where each asset is used

| Asset | Source | Used for |
|---|---|---|
| Product icons, 16 to 256 px | kit `application/png/`, unchanged | window and taskbar icon, About page, `favicon_product` |
| Desktop icons, 16 to 256 px | kit `desktop/hicolor/`, unchanged | installed under `share/icons/hicolor/` by the port |
| Lockups: emblem + "Beryllium" | kit emblem, Inter Bold, kit wordmark colour `#9F0710` (white for dark backgrounds) | `product_logo*.png` (140 x 32) and `product_logo_name_22*.png` (97 x 22), at 100% and 200% |
| Vector glyph: orb, horns, "Be" | drawn from the kit emblem (orb radius and horn positions measured on the 2048 px master), letters from Inter Bold | Chromium `.icon` files (address bar, menus, notifications), `product_logo.svg`, the onboarding page logo, the 22 px monochrome PNG |

Chromium needs vector icons in the `.icon` places, and the kit's emblem is
raster artwork, so the glyph is a simplified redraw without the orbit
rings. The kit's README recommends exactly that for small sizes. The
monochrome glyph takes the theme colour; the colour glyph uses the kit
palette.

The port applies `chromium/beryllium_resources.txt` with Helium's
`utils/replace_resources.py` after Helium's own list, so every Helium logo
is replaced (a unit test checks this against Helium's list on each Helium
update). Helium's generic page favicons (bookmarks, history, settings and
similar) are kept; they carry no Helium mark.

## Open items

- **Small sizes.** At 16 to 32 px the kit's icons (which include the orbit
  rings) are hard to read. The generator can use the simplified glyph for
  those sizes instead; this is the owner's choice.
- **Vector master.** The kit notes that the emblem is raster and recommends
  a true vector redraw before shipping.
- **Resemblance to the FreeBSD logo.** The red orb with horns resembles the
  FreeBSD logo, a trademark of the FreeBSD Foundation. Before any public
  distribution, check the Foundation's trademark usage terms and ask for
  permission if they require it.
- **Licence.** State the licence of the kit artwork (the repository is
  GPL-3.0; logos are often licensed separately). Inter is under the SIL
  Open Font License 1.1, which permits its use in logos.
- Chromium's `product_logo_animation.svg` is not replaced; where Chromium
  uses it on Linux has not been checked.
