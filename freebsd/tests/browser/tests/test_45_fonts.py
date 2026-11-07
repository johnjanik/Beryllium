# SPDX-License-Identifier: GPL-3.0-only
"""Fonts under the renderer lockdown (S-SHM-03): text in nine scripts is set
in the same platform fonts whether or not renderers are in capability mode.
A confined renderer cannot open font files by path; it must get them from
the browser, as the unconfined one does, or it falls back to other fonts."""

import unittest

from berytest import capsicum, context
from berytest.browser import Browser

SCRIPTS = {
    "latin": "The quick brown fox jumps over the lazy dog",
    "greek": "Ελληνικό αλφάβητο",
    "cyrillic": "Съешь же ещё этих мягких французских булок",
    "cjk": "日本語のテキスト。中文文本。한국어 텍스트.",
    "arabic": "نص عربي",
    "hebrew": "טקסט בעברית",
    "devanagari": "हिन्दी पाठ",
    "thai": "ภาษาไทย",
    "emoji": "😀 🎉 🦊",
}


def page_html():
    spans = "".join(f'<p><span id="{k}">{v}</span></p>' for k, v in SCRIPTS.items())
    return f'<!doctype html><meta charset="utf-8"><title>fonts</title>{spans}'


def platform_fonts(page):
    """{script: [(family, glyphs)]} as the renderer reports them (CDP CSS.getPlatformFontsForNode)."""
    page.send("DOM.enable")
    page.send("CSS.enable")
    root = page.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    out = {}
    for script in SCRIPTS:
        node = page.send("DOM.querySelector", {"nodeId": root, "selector": f"#{script}"})["nodeId"]
        fonts = page.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
        out[script] = sorted((f["familyName"], f["glyphCount"]) for f in fonts)
    return out


class Fonts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = context.get()
        if not cls.ctx.is_freebsd():
            raise unittest.SkipTest("FreeBSD only (the lockdown exists only there)")
        cls.url = cls.ctx.add_fixture("fonts.html", page_html())

    def fonts_with(self, name, switch):
        browser = Browser(self.ctx, name,
                          args=[f"--{switch}-features=BerylliumCapsicumRenderer"]).start()
        try:
            page = browser.new_page(self.url)
            procs = browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
            modes = {capsicum.capability_mode(p["id"]) for p in procs if p["type"] == "renderer"}
            return platform_fonts(page), modes
        finally:
            browser.stop()

    def test_same_platform_fonts_with_and_without_lockdown(self):
        """Each script is set in the same fonts in a confined renderer as in
        an unconfined one (the lockdown switched on and off explicitly)."""
        off, off_modes = self.fonts_with("fonts-off", "disable")
        on, on_modes = self.fonts_with("fonts-on", "enable")
        self.ctx.note(self.id(), "\n".join(
            f"{s}: " + (", ".join(f"{f} ({n} glyphs)" for f, n in on[s]) or "no platform font")
            for s in SCRIPTS))
        if on_modes != {True} or off_modes != {False}:
            self.skipTest("could not get one browser confined and one not "
                          f"(with the lockdown: {on_modes}, without: {off_modes})")
        for s in SCRIPTS:
            self.assertTrue(on[s], f"{s}: the confined renderer reports no platform font")
        self.assertEqual(on, off, "a confined renderer sets text in other fonts than an unconfined one")
