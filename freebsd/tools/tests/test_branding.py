# SPDX-License-Identifier: GPL-3.0-only
"""Checks for Beryllium's artwork (artwork/), the Chromium branding derived
from it (branding/), its licence notices, and how the port installs it."""

import importlib.machinery
import importlib.util
import os
import re
import struct
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BRANDING = os.path.join(REPO, "branding")
CHROMIUM = os.path.join(BRANDING, "chromium")
ARTWORK = os.path.join(REPO, "artwork")
ICONS = os.path.join(ARTWORK, "icons")
LOGO = os.path.join(ARTWORK, "logo")
WORDMARK = os.path.join(ARTWORK, "wordmark")
CUTOUTS = os.path.join(ARTWORK, "source", "cutouts")
SVG_NS = "{http://www.w3.org/2000/svg}"
PORT = os.path.join(REPO, "freebsd", "ports", "www", "beryllium")
TOOL = os.path.join(BRANDING, "tools", "make-chromium-branding")

def load_tool(name, module):
    loader = importlib.machinery.SourceFileLoader(
        module, os.path.join(BRANDING, "tools", name))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(module, loader))
    loader.exec_module(mod)
    return mod


mcb = load_tool("make-chromium-branding", "mcb")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


def resource_source(src):
    """A resource list source, as sync-port lays them out in the port."""
    if src.startswith("icons/"):
        return os.path.join(ICONS, src[len("icons/"):])
    return os.path.join(CHROMIUM, src)


def resource_lines(path):
    with open(path, encoding="utf-8") as f:
        return [l.split() for l in f if l.strip() and not l.startswith("#")]


class ResourceListTests(unittest.TestCase):
    def setUp(self):
        self.lines = resource_lines(os.path.join(CHROMIUM, "beryllium_resources.txt"))

    def test_format_and_sources_exist(self):
        for parts in self.lines:
            self.assertEqual(len(parts), 2, parts)
            self.assertTrue(os.path.isfile(resource_source(parts[0])), parts[0])

    def test_no_duplicate_destinations(self):
        dests = [d for _, d in self.lines]
        self.assertEqual(len(dests), len(set(dests)))

    def test_list_matches_generator(self):
        self.assertEqual([tuple(p) for p in self.lines], list(mcb.RESOURCES))

    @unittest.skipUnless(os.path.exists(os.path.join(REPO, "helium", "resources")),
                         "helium submodule not checked out")
    def test_every_helium_logo_is_replaced(self):
        ours = {d for _, d in self.lines}
        helium = resource_lines(os.path.join(REPO, "helium", "resources",
                                             "helium_resources.txt"))
        missing = [d for s, d in helium if not s.startswith("favicons/") and d not in ours]
        self.assertEqual(missing, [], "Helium logos Beryllium does not replace")


class AssetTests(unittest.TestCase):
    def test_vector_icons_parse(self):
        for name in ("product_logo.icon", "product_logo_color.icon"):
            with open(os.path.join(CHROMIUM, name), encoding="utf-8") as f:
                canvas, paths = mcb.parse_icon(f.read())
            self.assertEqual(canvas, 256)
            self.assertTrue(paths)

    def test_mono_icon_has_no_fixed_colour(self):
        # Chromium tints the monochrome icon with the theme colour.
        with open(os.path.join(CHROMIUM, "product_logo.icon"), encoding="utf-8") as f:
            self.assertNotIn("PATH_COLOR_ARGB", f.read())

    def test_no_clear_mode(self):
        # PATH_MODE_CLEAR would erase what is under the icon when painted
        # directly onto a view; the letters are holes by even-odd fill.
        for name in ("product_logo.icon", "product_logo_color.icon"):
            with open(os.path.join(CHROMIUM, name), encoding="utf-8") as f:
                self.assertNotIn("PATH_MODE_CLEAR", f.read())

    def test_svgs_are_well_formed_and_self_contained(self):
        # The emblem is embedded as a data: PNG; nothing is fetched.
        for name in ("product_logo.svg", "onboarding_logo.svg"):
            root = ET.parse(os.path.join(CHROMIUM, name)).getroot()
            self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg", name)
            hrefs = [e.get("href") for e in root.iter() if e.get("href")]
            self.assertTrue(hrefs, name)
            for h in hrefs:
                self.assertTrue(h.startswith("data:image/png;base64,"), name)

    def test_lockups_keep_chromium_and_helium_sizes(self):
        expected = {
            "product_logo.png": (140, 32), "product_logo_white.png": (140, 32),
            "product_logo_200.png": (280, 64), "product_logo_white_200.png": (280, 64),
            "product_logo_name_22.png": (97, 22), "product_logo_name_22_white.png": (97, 22),
            "product_logo_name_22_200.png": (194, 44),
            "product_logo_name_22_white_200.png": (194, 44),
            "product_logo_22_mono.png": (22, 22),
        }
        for name, size in expected.items():
            self.assertEqual(png_size(os.path.join(CHROMIUM, name)), size, name)

    def test_app_icons_are_square_at_each_size(self):
        self.assertEqual(sorted(os.listdir(ICONS)),
                         sorted(f"beryllium-{s}.png" for s in mcb.ICON_SIZES))
        for s in mcb.ICON_SIZES:
            self.assertEqual(png_size(os.path.join(ICONS, f"beryllium-{s}.png")), (s, s))


class ArtworkTests(unittest.TestCase):
    def test_layout(self):
        self.assertEqual(sorted(os.listdir(ARTWORK)),
                         ["README.md", "icons", "logo", "source", "wordmark"])
        self.assertEqual(sorted(os.listdir(os.path.join(ARTWORK, "source"))),
                         ["README.md", "beryllium-art-sheet-v2.webp", "cutouts"])
        self.assertEqual(sorted(os.listdir(LOGO)),
                         sorted([f"beryllium-{m}-{v}.svg" for m in ("emblem", "orb")
                                 for v in ("color", "flat", "mono")]
                                + ["beryllium-emblem-color.png"]))
        self.assertEqual(sorted(os.listdir(WORDMARK)),
                         ["beryllium-wordmark-on-dark.svg", "beryllium-wordmark-on-light.svg"])

    def test_no_v1_artwork(self):
        # Art set v2 (3 November 2026) replaced v1, whose horned emblem
        # resembled the FreeBSD logo; nothing of v1 may come back.
        for gone in ("branding/kit", "freebsd/branding"):
            self.assertFalse(os.path.exists(os.path.join(REPO, gone)), gone)

    def test_extractor_outputs_present(self):
        # The art sheet cut-outs are provenance: the masters were measured
        # from them.
        with open(os.path.join(BRANDING, "tools", "extract-art-sheet"), encoding="utf-8") as f:
            text = f.read()
        names = re.findall(r'^    "([a-z-]+\.png)": \(\d', text, re.M)
        names += re.findall(r'"([a-z-]+-dark\.png)"', text)
        self.assertIn("beryllium-emblem.png", names)
        self.assertEqual(sorted(os.listdir(CUTOUTS)), sorted(set(names)))
        for n in names:
            png_size(os.path.join(CUTOUTS, n))  # a PNG

    def test_artwork_licence_and_trademark_notice(self):
        with open(os.path.join(ARTWORK, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("Creative Commons Attribution 4.0 International license", readme)
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", readme)
        self.assertIn("does not grant trademark rights", readme)
        with open(os.path.join(REPO, "LICENSES", "CC-BY-4.0.txt"), encoding="utf-8") as f:
            legal = f.read()
        self.assertTrue(legal.startswith("Attribution 4.0 International"))
        for n in range(1, 9):
            self.assertIn(f"Section {n} -- ", legal)
        self.assertTrue(os.path.isfile(os.path.join(REPO, "TRADEMARKS.md")))
        with open(os.path.join(REPO, "LICENSE"), encoding="utf-8") as f:
            self.assertIn("GNU GENERAL PUBLIC LICENSE", f.read(200))

    def test_mono_icon_follows_theme_and_colour_icon_has_art_palette(self):
        with open(os.path.join(CHROMIUM, "product_logo_color.icon"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("PATH_COLOR_ARGB, 0xFF, 0xF4, 0x06, 0x02,", text)


def svg_masters():
    return sorted([os.path.join(LOGO, n) for n in os.listdir(LOGO) if n.endswith(".svg")]
                  + [os.path.join(WORDMARK, n) for n in os.listdir(WORDMARK)])


class MasterTests(unittest.TestCase):
    """The vector masters (branding/tools/make-masters) and what is made from them."""

    def test_self_contained_outlines(self):
        # Letters are outlines, nothing is fetched or run, and every url(#id)
        # points into the same file.
        for path in svg_masters():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            root = ET.fromstring(text)
            self.assertEqual(root.tag, SVG_NS + "svg", path)
            tags = {e.tag.replace(SVG_NS, "") for e in root.iter()}
            for bad in ("text", "image", "script", "foreignObject", "style", "use"):
                self.assertNotIn(bad, tags, path)
            ids = {e.get("id") for e in root.iter() if e.get("id")}
            for ref in re.findall(r"url\(#([^)]+)\)", text):
                self.assertIn(ref, ids, path)
            self.assertNotIn("href", text, path)
            self.assertIn("CC BY 4.0", text, path)

    def test_logo_masters_are_1024_square(self):
        for path in svg_masters():
            if os.path.dirname(path) == LOGO:
                root = ET.parse(path).getroot()
                self.assertEqual((root.get("width"), root.get("height"), root.get("viewBox")),
                                 ("1024", "1024", "0 0 1024 1024"), path)
        self.assertEqual(png_size(os.path.join(LOGO, "beryllium-emblem-color.png")), (1024, 1024))

    def test_flat_and_mono_masters(self):
        # Flat: the palette only, no gradients. One colour: currentColor, so
        # a theme or a stylesheet decides the colour.
        for path in svg_masters():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if "-flat." in path:
                self.assertNotIn("Gradient", text, path)
                self.assertEqual(set(re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]{6})"', text)),
                                 {"#A00806", "#F40602", "#FFFFFF"}, path)
            if "-mono." in path:
                self.assertNotIn("Gradient", text, path)
                self.assertIn('fill="currentColor"', text, path)

    def test_masters_reproduce(self):
        try:
            mm = load_tool("make-masters", "make_masters")
            import uharfbuzz  # noqa: F401  (imported by make-masters when shaping)
        except ImportError as e:
            self.skipTest(f"make-masters needs {e.name}")
        if not mm.FONT or not mm.FONT_REGULAR:
            self.skipTest("Inter Bold and Regular not installed")
        for name, text in mm.outputs().items():
            with open(os.path.join(ARTWORK, name), encoding="utf-8") as f:
                self.assertEqual(f.read(), text, name)

    def test_small_icons_reproduce(self):
        try:
            msi = load_tool("make-small-icons", "make_small_icons")
            from PIL import ImageChops, Image
        except ImportError as e:
            self.skipTest(f"make-small-icons needs {e.name}")
        self.assertEqual(sorted(msi.GLYPHS), [s for s in mcb.ICON_SIZES if s <= mcb.SMALL_ICON_MAX])
        for s in msi.GLYPHS:
            ours = Image.open(os.path.join(ICONS, f"beryllium-{s}.png")).convert("RGBA")
            self.assertIsNone(ImageChops.difference(msi.icon(s), ours).getbbox(), s)

    def test_readme_header_uses_the_wordmark_masters(self):
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
            head = f.read(800)
        self.assertIn('srcset="artwork/wordmark/beryllium-wordmark-on-dark.svg"', head)
        self.assertIn('src="artwork/wordmark/beryllium-wordmark-on-light.svg"', head)


class PortTests(unittest.TestCase):
    def test_desktop_icons_match_artwork_makefile_and_plist(self):
        with open(os.path.join(PORT, "Makefile"), encoding="utf-8") as f:
            m = re.search(r"^BERYLLIUM_ICON_SIZES=\s*(.+)$", f.read(), re.M)
        sizes = sorted(int(s) for s in m.group(1).split())
        self.assertEqual(sizes, sorted(mcb.ICON_SIZES))
        with open(os.path.join(PORT, "pkg-plist"), encoding="utf-8") as f:
            plist = f.read().split("\n")
        for s in sizes:
            self.assertTrue(os.path.isfile(os.path.join(ICONS, f"beryllium-{s}.png")))
            self.assertIn(f"share/icons/hicolor/{s}x{s}/apps/beryllium.png", plist)

    def test_port_applies_branding_after_helium(self):
        with open(os.path.join(PORT, "Makefile"), encoding="utf-8") as f:
            text = f.read()
        helium = text.index("resources/helium_resources.txt")
        ours = text.index("branding/beryllium_resources.txt")
        self.assertLess(helium, ours)


if __name__ == "__main__":
    unittest.main()
