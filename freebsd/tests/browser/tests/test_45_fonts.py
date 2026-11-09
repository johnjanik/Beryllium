# SPDX-License-Identifier: GPL-3.0-only
"""Fonts: text in eleven scripts is drawn with fonts that have its glyphs,
and with the same fonts whether or not renderers are in capability mode.

Chromium draws each character with whatever installed font has a glyph for
it: the browser's FontService asks fontconfig and hands the renderer the
font file. When no installed font has the glyph, the text is drawn with the
page's own font as boxes or blanks (tofu). The first test catches that with
the fontconfig the browser asked (fc-list by charset) and names the FreeBSD
package that brings a font for the script; noto-basic, the one font package
every Chromium port depends on, covers Latin, Greek and Cyrillic only.

A confined renderer cannot open font files by path; it must get them from
the browser, as the unconfined one does, or it falls back to other fonts
(S-SHM-03): the second test compares both."""

import re
import subprocess
import unicodedata
import unittest

from berytest import capsicum, context
from berytest.browser import Browser

SCRIPTS = {
    "latin": "The quick brown fox jumps over the lazy dog",
    "greek": "Ελληνικό αλφάβητο",
    "cyrillic": "Съешь же ещё этих мягких французских булок",
    "chinese": "中文文本，简体与繁體。",
    "japanese": "日本語のテキスト、ひらがなとカタカナ。",
    "korean": "한국어 텍스트입니다.",
    "arabic": "نص عربي",
    "hebrew": "טקסט בעברית",
    "devanagari": "हिन्दी पाठ",
    "thai": "ภาษาไทย",
    "emoji": "😀 🎉 🦊",
}

# The FreeBSD package that brings a font with the script's glyphs. The port
# depends on noto-basic, noto-sans-sc and noto-emoji by default (its FONTS
# options); the others are the user's to install (noto-extra has them all).
PACKAGES = {
    "latin": "noto-basic",
    "greek": "noto-basic",
    "cyrillic": "noto-basic",
    "chinese": "noto-sans-sc",
    "japanese": "noto-sans-sc",
    "korean": "noto-sans-sc",
    "arabic": "noto-sans-arabic",
    "hebrew": "noto-sans-hebrew",
    "devanagari": "noto-sans-devanagari",
    "thai": "noto-sans-thai",
    "emoji": "noto-emoji",
}


def page_html():
    spans = "".join(f'<p><span id="{k}">{v}</span></p>' for k, v in SCRIPTS.items())
    return f'<!doctype html><meta charset="utf-8"><title>fonts</title>{spans}'


def letters(text):
    """The characters of text a font must have a glyph for: letters and
    symbols (emoji), not spaces, punctuation or combining marks, which a
    font that has the base letters shapes with them. Each once, in order."""
    return list(dict.fromkeys(
        c for c in text if unicodedata.category(c) in ("Lu", "Ll", "Lo", "So")))


def fc_list(pattern, element):
    """fontconfig's answer to `fc-list PATTERN ELEMENT`, one font per line."""
    try:
        return subprocess.run(["fc-list", pattern, element], capture_output=True,
                              text=True, check=False, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def families_with(char, fc_list=fc_list):
    """The installed font families with a glyph for char, by fontconfig.
    fc-list prints every name of a family on one line, separated by commas,
    with commas and hyphens in a name escaped by a backslash."""
    families = set()
    for line in fc_list(f":charset={ord(char):x}", "family").splitlines():
        for name in re.split(r"(?<!\\),", line):
            name = re.sub(r"\\(.)", r"\1", name).strip()
            if name:
                families.add(name)
    return families


def missing_glyphs(fonts, text, families_with=families_with):
    """[(char, [families that have it])] for each letter of text that none
    of the fonts (family names the renderer reported) has a glyph for."""
    fonts = set(fonts)
    missing = []
    for c in letters(text):
        have = families_with(c)
        if not have & fonts:
            missing.append((c, sorted(have)))
    return missing


def tofu(fonts_by_script, families_with=families_with):
    """One line per script whose text the renderer set in fonts without its
    glyphs, saying what has them or which package brings them."""
    problems = []
    for script, text in SCRIPTS.items():
        fonts = [family for family, _ in fonts_by_script.get(script, [])]
        missing = missing_glyphs(fonts, text, families_with)
        if not missing:
            continue
        chars = "".join(c for c, _ in missing)
        have = sorted({f for _, families in missing for f in families})
        if have:
            why = ("installed fonts that have them, which the browser did not use: "
                   + ", ".join(have))
        else:
            why = f"no installed font has them: pkg install {PACKAGES[script]}"
        problems.append(f"{script}: set in {', '.join(fonts) or 'no platform font'}, "
                        f"without a glyph for {chars}; {why}")
    return problems


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


def describe(fonts_by_script):
    return "\n".join(
        f"{s}: " + (", ".join(f"{f} ({n} glyphs)" for f, n in fonts_by_script[s]) or "no platform font")
        for s in SCRIPTS)


class Fonts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = context.get()
        if not cls.ctx.is_freebsd():
            raise unittest.SkipTest("FreeBSD only (the lockdown exists only there)")
        cls.url = cls.ctx.add_fixture("fonts.html", page_html())
        cls.seen = {}

    @classmethod
    def fonts_with(cls, switch):
        """({script: fonts}, {renderer capability modes}) from a browser with
        the lockdown explicitly switched on or off; each started once."""
        if switch not in cls.seen:
            name = {"enable": "fonts-on", "disable": "fonts-off"}[switch]
            browser = Browser(cls.ctx, name,
                              args=[f"--{switch}-features=BerylliumCapsicumRenderer"]).start()
            try:
                page = browser.new_page(cls.url)
                procs = browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
                modes = {capsicum.capability_mode(p["id"]) for p in procs if p["type"] == "renderer"}
                cls.seen[switch] = (platform_fonts(page), modes)
            finally:
                browser.stop()
        return cls.seen[switch]

    def test_every_script_is_drawn_with_a_font_that_has_its_glyphs(self):
        """No script's text is set in a font without glyphs for it (boxes or
        blanks); with the lockdown off and on. Names the package to install."""
        off, _ = self.fonts_with("disable")
        on, _ = self.fonts_with("enable")
        self.note(describe(off))
        problems = tofu(off)
        for line in tofu(on):
            if line not in problems:
                problems.append(f"with the lockdown, {line}")
        self.assertEqual(problems, [], "text drawn without its glyphs:\n" + "\n".join(problems))

    def test_same_platform_fonts_with_and_without_lockdown(self):
        """Each script is set in the same fonts in a confined renderer as in
        an unconfined one (the lockdown switched on and off explicitly)."""
        off, off_modes = self.fonts_with("disable")
        on, on_modes = self.fonts_with("enable")
        if on_modes != {True} or off_modes != {False}:
            self.skipTest("could not get one browser confined and one not "
                          f"(with the lockdown: {on_modes}, without: {off_modes})")
        for s in SCRIPTS:
            self.assertTrue(on[s], f"{s}: the confined renderer reports no platform font")
        self.assertEqual(on, off, "a confined renderer sets text in other fonts than an unconfined one")

    def note(self, text):
        self.ctx.note(self.id(), text)
