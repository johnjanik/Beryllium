# Beryllium branding for the browser build

The artwork itself is in [`artwork/`](../artwork/README.md). This
directory holds the tools that prepare it and the Chromium-specific files
the build uses.

- `tools/extract-art-sheet`: cuts the logo and wordmark masters out of the
  art sheet (`artwork/source/`) into `artwork/logo/` and
  `artwork/wordmark/`, removing the painted checkerboard (needs Pillow,
  numpy and scipy).
- `tools/make-chromium-branding`: scales the masters to `artwork/icons/`
  and generates `chromium/` (needs Pillow, fontTools and Inter Bold).
- Both take `--check` to confirm the committed files match. The build does
  not run them: after changing the artwork, run them, then
  `freebsd/tools/sync-port`, which copies `chromium/` and `artwork/icons/`
  into the port.

## Licences

- The files in `chromium/` (except the list `beryllium_resources.txt`) are
  artwork derived from `artwork/`, and like it are licensed under
  [CC BY 4.0](../LICENSES/CC-BY-4.0.txt), copyright © 2026 Beryllium
  Browser contributors. The same applies to their copies in
  `freebsd/ports/www/beryllium/files/beryllium/branding/`. The Beryllium
  name and logo are reserved as described in
  [TRADEMARKS.md](../TRADEMARKS.md).
- The lockup lettering and the letters of the vector glyph are set in
  Inter, under the SIL Open Font License 1.1, which permits its use in
  artwork and logos.
- The tools are part of the software and are GPL-3.0, like the rest of the
  code.

## Where each asset is used

| Asset | Source | Used for |
|---|---|---|
| App and desktop icons, 48 to 256 px | `artwork/logo/beryllium-emblem.png` (orb, "Be", two orbits) | window and taskbar icon, About page, `share/icons/hicolor/` |
| App and desktop icons, 16 to 32 px | `artwork/logo/beryllium-orb.png` (plain orb with "Be") | the same places at small sizes, `favicon_product`; the orbits would blur into the orb |
| Lockups: emblem + "Beryllium" | emblem, Inter Bold, near-black or white lettering | `product_logo*.png` (140 x 32) and `product_logo_name_22*.png` (97 x 22), at 100% and 200% |
| `product_logo.svg`, onboarding page logo | emblem, embedded as PNG | Chromium WebUI pages accept `data:` images |
| Vector glyph: plain orb with "Be" | drawn to the plain orb's proportions | Chromium `.icon` files (address bar, menus, notifications; colour and theme-tinted monochrome), the 22 px monochrome PNG |
| Repository README header | `artwork/wordmark/beryllium-lockup.png` and `-dark.png` | GitHub light and dark themes |

The port applies `chromium/beryllium_resources.txt` with Helium's
`utils/replace_resources.py` after Helium's own list, so every Helium logo
is replaced (a unit test checks this against Helium's list on each Helium
update). Helium's generic page favicons (bookmarks, history, settings and
similar) are kept; they carry no Helium mark.

## Open items

- **Vector master.** The art is raster (the emblem is about 410 px
  across): enough for the browser, not for print or very large displays.
- Chromium's `product_logo_animation.svg` is not replaced; where Chromium
  uses it on Linux has not been checked.
