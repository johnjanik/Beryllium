# Beryllium branding for the browser build

The artwork itself is in [`artwork/`](../artwork/README.md). This
directory holds the tools that make it and the Chromium-specific files
the build uses. The build runs none of them: their outputs are committed.

## The chain

```
art sheet v2 (artwork/source/) --extract-art-sheet--> cut-outs (artwork/source/cutouts/)
        measured once (5 November 2026) into the geometry in make-masters
make-masters ------------> artwork/logo/*.svg, artwork/wordmark/*.svg   (vector masters)
render-artwork ----------> artwork/icons/beryllium-{48..256}.png,
                           artwork/logo/beryllium-emblem-color.png      (Chromium renders)
make-small-icons --------> artwork/icons/beryllium-{16..32}.png         (drawn pixel by pixel)
make-chromium-branding --> branding/chromium/                           (from the two above)
freebsd/tools/sync-port -> the port's files/beryllium/branding/
```

- `tools/make-masters`: the emblem and the small orb mark in colour,
  flat and one colour, and the "Beryllium Browser" wordmark for light and
  dark backgrounds, as SVG with outlined letters (needs fontTools,
  uharfbuzz, Inter Bold and Regular).
- `tools/render-artwork`: renders the colour emblem master with Chromium
  (through Playwright), the engine the browser uses: the 48 to 256 px
  icons and a 1024 px emblem (needs Node.js and Playwright).
- `tools/make-small-icons`: the flat 16, 22, 24 and 32 px icons, with the
  letters drawn pixel by pixel after Inter Bold (needs Pillow).
- `tools/make-chromium-branding`: lockups, WebUI logos, the vector
  `.icon` glyphs and the resource list (needs Pillow, fontTools and Inter
  Bold).
- `tools/extract-art-sheet`: cuts the art sheet into the cut-outs, the
  provenance of the masters' geometry (needs Pillow, numpy and scipy).
- All but `render-artwork` take `--check` to confirm the committed files
  match. Renders can differ by a few levels between Chromium versions, so
  they are reviewed by eye when they change.

After changing the artwork: `make-masters`, `render-artwork`,
`make-small-icons`, `make-chromium-branding`, then
`freebsd/tools/sync-port`, which copies `chromium/` and `artwork/icons/`
into the port. The unit tests (`freebsd/tools/tests/test_branding.py`)
check the layout, the masters and the generated files on every push.

The masters were rebuilt from art set v2 and approved by the owner on 5
November 2026; the review rounds are in
[`design-intake/`](../design-intake/README.md).

## Licences

- The files in `chromium/` (except the list `beryllium_resources.txt`) are
  artwork derived from `artwork/`, and like it are licensed under
  [CC BY 4.0](../LICENSES/CC-BY-4.0.txt), copyright © 2026 Beryllium
  Browser contributors. The same applies to their copies in
  `freebsd/ports/www/beryllium/files/beryllium/branding/`. The Beryllium
  name and logo are reserved as described in
  [TRADEMARKS.md](../TRADEMARKS.md).
- The letters of the masters, the wordmark, the lockups and the vector
  glyph are outlines of Inter, under the SIL Open Font License 1.1, which
  permits its use in artwork and logos.
- The tools are part of the software and are GPL-3.0, like the rest of the
  code.

## Where each asset is used

| Asset | Source | Used for |
|---|---|---|
| App and desktop icons, 48 to 256 px | the colour emblem master (orb, "Be", two orbits), rendered | window and taskbar icon, About page, `share/icons/hicolor/` |
| App and desktop icons, 16 to 32 px | the flat orb with "Be", drawn pixel by pixel | the same places at small sizes, `favicon_product`; the orbits would blur into the orb |
| Lockups: emblem + "Beryllium" | the 1024 px emblem render, Inter Bold, near-black or white lettering | `product_logo*.png` (140 x 32) and `product_logo_name_22*.png` (97 x 22), at 100% and 200% |
| `product_logo.svg`, onboarding page logo | the emblem render, embedded as PNG | Chromium WebUI pages accept `data:` images |
| Vector glyph: orb with "Be" | the geometry of the flat and one-colour orb masters | Chromium `.icon` files (address bar, menus, notifications; colour and theme-tinted monochrome), the 22 px monochrome PNG |
| Repository README header | `artwork/wordmark/beryllium-wordmark-on-{light,dark}.svg` | GitHub light and dark themes |

The port applies `chromium/beryllium_resources.txt` with Helium's
`utils/replace_resources.py` after Helium's own list, so every Helium logo
is replaced (a unit test checks this against Helium's list on each Helium
update). Helium's generic page favicons (bookmarks, history, settings and
similar) are kept; they carry no Helium mark.

## Open items

- Chromium's `product_logo_animation.svg` is not replaced; where Chromium
  uses it on Linux has not been checked.
