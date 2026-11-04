# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/beryllium-name-substitution (regex layer only)."""

import contextlib
import hashlib
import io
import importlib.machinery
import importlib.util
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOL = os.path.join(HERE, "..", "beryllium-name-substitution")
UTILS = os.path.join(REPO, "helium", "utils")

_loader = importlib.machinery.SourceFileLoader("berysub", TOOL)
_spec = importlib.util.spec_from_loader("berysub", _loader)
berysub = importlib.util.module_from_spec(_spec)
_loader.exec_module(berysub)


@unittest.skipUnless(os.path.exists(os.path.join(UTILS, "name_substitution_utils.py")),
                     "helium submodule not checked out")
class SubstitutionTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, UTILS)
        import name_substitution_utils as util
        self.util = util
        self.saved = (util.REPLACEMENT_REGEXES_STR, util.REPLACEMENT_REGEXES,
                      util.replace_grit_tree)
        berysub.install(util)
        # compute_fp imports grit from a Chromium tree; a stand-in is enough
        # to exercise the rewrite.
        tclib = types.ModuleType("grit.extern.tclib")
        tclib.GenerateMessageId = lambda text, meaning="": hashlib.sha1(
            (text + meaning).encode()).hexdigest()
        self.saved_modules = {k: sys.modules.get(k) for k in
                              ("grit", "grit.extern", "grit.extern.tclib")}
        grit, extern = types.ModuleType("grit"), types.ModuleType("grit.extern")
        grit.extern, extern.tclib = extern, tclib
        sys.modules.update({"grit": grit, "grit.extern": extern,
                            "grit.extern.tclib": tclib})

    def tearDown(self):
        (self.util.REPLACEMENT_REGEXES_STR, self.util.REPLACEMENT_REGEXES,
         self.util.replace_grit_tree) = self.saved
        for k, v in self.saved_modules.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.path.remove(UTILS)

    def test_grdp_without_declaration_stays_without(self):
        # The onboarding strings file: no XML declaration, only "Helium".
        text = ('<grit-part>\n<message name="IDS_HELIUM_ONBOARDING_PAGE_TITLE" '
                'desc="x">\n  Helium Setup\n</message>\n</grit-part>\n')
        out, fp_map = self.util.replace_grit_tree(text)
        self.assertTrue(out.startswith("<grit-part>"), out[:60])
        self.assertIn("Beryllium Setup", out)
        self.assertEqual(len(fp_map), 1)

    def test_grd_with_declaration_keeps_it(self):
        text = ('<?xml version="1.0" encoding="UTF-8"?>\n<grit-part>\n'
                '<message name="IDS_X" desc="x">Google Chrome</message>\n</grit-part>\n')
        out, _ = self.util.replace_grit_tree(text)
        self.assertTrue(out.startswith("<?xml"), out[:60])
        self.assertIn(">Beryllium<", out)

    def test_sanity_table(self):
        berysub.sanity(self.util)

    def test_internal_identifiers_untouched(self):
        for s in ("helium.services.enabled", "kHeliumUIScheme"):
            out, _ = self.util.replace_text(s)
            self.assertEqual(out, s)

    def test_helium_tool_still_has_expected_hooks(self):
        # If Helium renames these, the wrapper must be updated.
        import name_substitution as ns
        self.assertTrue(hasattr(ns, "replacement_sanity"))
        self.assertTrue(hasattr(ns, "main"))
        self.assertTrue(hasattr(self.util, "replace_text"))


class CppStringTests(unittest.TestCase):
    ENTRIES = (
        '    {"bookmark-open-all-confirmation",\n'
        '     "Bookmark open-all confirmation",\n'
        '     "Controls whether Helium asks for confirmation before opening 15 or more "\n'
        '     "bookmarks. Helium flag.",\n'
        '     kOsAll, FEATURE_VALUE_TYPE(features::kHeliumBookmarkConfirm)},\n'
        '    {"helium-noise", "Helium Noise", "Quote \\"Helium\\" inside. HeliumLike stays.",\n'
        '     kOsAll, SINGLE_VALUE_TYPE("helium-noise")},\n'
        '// A comment about Helium outside any string.\n')

    def test_only_capitalised_word_in_literals(self):
        text, count = berysub.rename_in_string_literals(self.ENTRIES)
        self.assertEqual(count, 4)
        self.assertIn('"Controls whether Beryllium asks for confirmation', text)
        self.assertIn('"bookmarks. Beryllium flag."', text)
        self.assertIn('"Beryllium Noise"', text)
        self.assertIn('Quote \\"Beryllium\\" inside. HeliumLike stays.', text)
        for kept in ('"bookmark-open-all-confirmation"', '"helium-noise"',
                     'features::kHeliumBookmarkConfirm', '// A comment about Helium outside'):
            self.assertIn(kept, text)

    def test_renames_files_in_tree(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tree:
            for rel in berysub.CPP_STRING_FILES:
                path = os.path.join(tree, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(self.ENTRIES)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(berysub.rename_cpp_strings(tree), 8)
            with open(os.path.join(tree, berysub.FLAG_ENTRIES)) as f:
                self.assertNotIn("Helium flag.", f.read())

    def test_missing_file_warns(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tree:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(berysub.rename_cpp_strings(tree), 0)
            self.assertIn("not found", err.getvalue())

    def test_tree_argument(self):
        self.assertEqual(berysub.tree_argument(["--sub", "-t", "/w"]), "/w")
        self.assertEqual(berysub.tree_argument(["--sub", "--tree=/w"]), "/w")
        self.assertIsNone(berysub.tree_argument(["--revert", "-t", "/w"]))
        self.assertIsNone(berysub.tree_argument(["--sub", "--dry-run", "-t", "/w"]))


if __name__ == "__main__":
    unittest.main()
