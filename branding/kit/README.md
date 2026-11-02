# Beryllium Browser — Branding Kit v1

## Contents
- `master/beryllium-emblem-master-2048.png`: transparent, high-resolution master raster.
- `master/beryllium-emblem-monochrome-2048.png`: grayscale derivative with transparency.
- `source/beryllium-emblem.svg`: SVG container embedding the master PNG (raster artwork, **not** a true vector trace).
- `source/beryllium-wordmark.svg`: editable-text wordmark; convert text to paths before production if font consistency is required.
- `application/png/`: common application icon exports.
- `desktop/hicolor/`: FreeDesktop/KDE hicolor PNG icon hierarchy.
- `web/`: favicon, Apple touch icon and PWA icon exports.

## Important production notes
1. The emblem artwork is a raster image. The SVG wrapper does not make its internal artwork resolution-independent.
2. This package is a practical first build asset set. Before shipping, commission or create a true vector redraw of the emblem, especially the orb, horns, rings and nodes.
3. At 16–32 px, fine orbital details may merge. A purpose-drawn simplified glyph is recommended for toolbar and favicon use.
4. The generated monochrome file is a grayscale derivative, not a one-color silhouette.
5. Verify icon naming and destination paths against the exact Chromium revision and FreeBSD packaging layout being built.

## Suggested FreeBSD desktop install
Install the matching `desktop/hicolor/<size>x<size>/apps/beryllium.png` files under:
`/usr/local/share/icons/hicolor/<size>x<size>/apps/beryllium.png`

Install the desktop entry separately as:
`/usr/local/share/applications/beryllium.desktop`

## Color direction
Primary palette sampled conceptually from the supplied mark:
- Deep red: `#76000B`
- Orb red: `#F20B13`
- Orange highlight: `#FF7A13`
- Warm highlight: `#FFF0D4`
- Lettering: `#FFFFFF`
