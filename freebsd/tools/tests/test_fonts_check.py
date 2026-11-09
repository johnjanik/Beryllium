# SPDX-License-Identifier: GPL-3.0-only
"""The fonts test's glyph-coverage logic (freebsd/tests/browser/tests/
test_45_fonts.py), with fontconfig's answers faked: text set in a font
without its glyphs is named with the package that brings one, text set in
a font that has them passes, and fc-list's escaped names are parsed."""

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUITE = os.path.join(REPO, "freebsd", "tests", "browser")
sys.path.insert(0, SUITE)

spec = importlib.util.spec_from_file_location(
    "test_45_fonts", os.path.join(SUITE, "tests", "test_45_fonts.py"))
fonts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fonts)

# What fontconfig knows on the owner's machine before the CJK font: Noto
# Sans and Liberation Serif for Latin, Greek, Cyrillic and Hebrew; DejaVu
# Sans for Arabic as well; FreeSans and FreeSerif for Devanagari and Thai;
# Noto Color Emoji; nothing for CJK.
COVERAGE = {
    "latin": ["Noto Sans", "Liberation Serif", "DejaVu Sans", "FreeSans", "FreeSerif"],
    "greek": ["Noto Sans", "Liberation Serif", "DejaVu Sans", "FreeSerif"],
    "cyrillic": ["Noto Sans", "Liberation Serif", "DejaVu Sans", "FreeSerif"],
    "hebrew": ["Liberation Serif", "DejaVu Sans", "FreeSerif"],
    "arabic": ["DejaVu Sans", "FreeSerif"],
    "devanagari": ["FreeSans", "FreeSerif"],
    "thai": ["FreeSerif"],
    "emoji": ["Noto Color Emoji"],
}


def fake_fc_list(coverage):
    """An fc-list that answers `:charset=HEX family` from COVERAGE-shaped
    data, one family per line."""
    def fc_list(pattern, element):
        assert element == "family" and pattern.startswith(":charset=")
        char = chr(int(pattern[len(":charset="):], 16))
        for script, text in fonts.SCRIPTS.items():
            if char in text and script in coverage:
                return "".join(f"{family}\n" for family in coverage[script])
        return ""
    return fc_list


class Letters(unittest.TestCase):
    def test_letters_skip_spaces_punctuation_and_marks(self):
        self.assertEqual(fonts.letters("हिन्दी पाठ"), ["ह", "न", "द", "प", "ठ"])
        self.assertEqual(fonts.letters("😀 🎉 🦊"), ["😀", "🎉", "🦊"])
        self.assertEqual(fonts.letters("中文文本，简体与繁體。"), list("中文本简体与繁體"))

    def test_every_script_has_letters_and_a_package(self):
        for script, text in fonts.SCRIPTS.items():
            self.assertTrue(fonts.letters(text), script)
            self.assertIn(script, fonts.PACKAGES)
        self.assertEqual(set(fonts.PACKAGES), set(fonts.SCRIPTS))


class Families(unittest.TestCase):
    def test_names_are_split_and_unescaped(self):
        def fc_list(pattern, element):
            return "Noto Sans CJK SC,Noto Sans CJK SC Regular\nUnifont\\-JP\nFree\\, Serif,FreeSerif\n"
        self.assertEqual(fonts.families_with("中", fc_list),
                         {"Noto Sans CJK SC", "Noto Sans CJK SC Regular", "Unifont-JP",
                          "Free, Serif", "FreeSerif"})

    def test_no_answer_is_no_family(self):
        self.assertEqual(fonts.families_with("中", lambda p, e: ""), set())


class Tofu(unittest.TestCase):
    def check(self, fonts_by_script, coverage=COVERAGE):
        fc = fake_fc_list(coverage)
        return fonts.tofu(fonts_by_script, lambda c: fonts.families_with(c, fc))

    def test_cjk_in_liberation_serif_is_tofu_naming_the_package(self):
        seen = {
            "latin": [("Liberation Serif", 43)],
            "greek": [("Liberation Serif", 17)],
            "cyrillic": [("Liberation Serif", 43)],
            "hebrew": [("Liberation Serif", 11)],
            "devanagari": [("FreeSans", 8), ("Liberation Serif", 1)],
            "thai": [("FreeSerif", 7)],
            "chinese": [("Liberation Serif", 11)],
            "japanese": [("Liberation Serif", 19)],
            "korean": [("Liberation Serif", 10)],
            "arabic": [("DejaVu Sans", 6), ("Liberation Serif", 1)],
            "emoji": [("Liberation Serif", 2), ("Noto Color Emoji", 3)],
        }
        problems = self.check(seen)
        self.assertEqual(len(problems), 3, problems)
        self.assertEqual(problems[0], "chinese: set in Liberation Serif, without a glyph for "
                                      "中文本简体与繁體; no installed font has them: pkg install noto-sans-sc")
        self.assertTrue(problems[1].startswith("japanese: set in Liberation Serif, without a glyph for 日本語の"))
        self.assertIn("pkg install noto-sans-sc", problems[2])
        self.assertTrue(problems[2].startswith("korean:"))

    def test_text_in_a_font_that_has_it_passes(self):
        seen = {s: [("Noto Sans", 10)] for s in ("latin", "greek", "cyrillic")}
        seen.update({
            "chinese": [("Noto Sans CJK SC", 11)],
            "japanese": [("Noto Sans CJK SC", 19)],
            "korean": [("Noto Sans CJK SC", 10)],
            "arabic": [("DejaVu Sans", 6), ("Noto Sans", 1)],
            "hebrew": [("Liberation Serif", 11)],
            "devanagari": [("FreeSans", 8), ("Noto Sans", 1)],
            "thai": [("FreeSerif", 7)],
            "emoji": [("Noto Color Emoji", 3), ("Noto Sans", 2)],
        })
        coverage = dict(COVERAGE)
        for s in ("chinese", "japanese", "korean"):
            coverage[s] = ["Noto Sans CJK SC"]
        self.assertEqual(self.check(seen, coverage), [])

    def test_an_installed_font_the_browser_did_not_use_is_named(self):
        seen = {s: [("Noto Sans", 10)] for s in fonts.SCRIPTS}
        seen["thai"] = [("Noto Sans", 7)]
        problems = self.check(seen)
        thai = [p for p in problems if p.startswith("thai:")]
        self.assertEqual(thai, ["thai: set in Noto Sans, without a glyph for ภาษไทย; "
                                "installed fonts that have them, which the browser did not use: FreeSerif"])

    def test_a_script_the_renderer_reported_no_font_for(self):
        problems = self.check({"chinese": []}, {})
        chinese = [p for p in problems if p.startswith("chinese:")]
        self.assertEqual(chinese, ["chinese: set in no platform font, without a glyph for "
                                   "中文本简体与繁體; no installed font has them: pkg install noto-sans-sc"])


if __name__ == "__main__":
    unittest.main()
