# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/beryllium-name-substitution (regex layer only)."""

import importlib.machinery
import importlib.util
import os
import sys
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
        self.saved = (util.REPLACEMENT_REGEXES_STR, util.REPLACEMENT_REGEXES)
        berysub.install(util)

    def tearDown(self):
        self.util.REPLACEMENT_REGEXES_STR, self.util.REPLACEMENT_REGEXES = self.saved
        sys.path.remove(UTILS)

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


if __name__ == "__main__":
    unittest.main()
