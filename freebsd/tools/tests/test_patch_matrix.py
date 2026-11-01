# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/patch-matrix."""

import importlib.machinery
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "patch-matrix")
_loader = importlib.machinery.SourceFileLoader("patchmatrix", TOOL)
_spec = importlib.util.spec_from_loader("patchmatrix", _loader)
pm = importlib.util.module_from_spec(_spec)
_loader.exec_module(pm)

BSD = """--- base/foo.cc.orig\t2026-10-18 13:29:39 UTC
+++ base/foo.cc
@@ -10,7 +10,7 @@ void F() {
-#if BUILDFLAG(IS_LINUX)
+#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_BSD)
"""

HELIUM = """--- a/base/foo.cc
+++ b/base/foo.cc
@@ -40,6 +40,7 @@
+x
--- /dev/null
+++ b/base/new.cc
@@ -0,0 +1,3 @@
+a
"""


class ParseTests(unittest.TestCase):
    def test_bsd_orig_style(self):
        files = pm.parse_patch(BSD)
        self.assertEqual(list(files), ["base/foo.cc"])
        self.assertEqual(files["base/foo.cc"]["hunks"], [(10, 7)])

    def test_git_style_and_new_file(self):
        files = pm.parse_patch(HELIUM)
        self.assertEqual(files["base/foo.cc"]["hunks"], [(40, 6)])
        self.assertTrue(files["base/new.cc"]["new"])


class ClassifyTests(unittest.TestCase):
    def entry(self, hunks, new=False):
        return [("p", {"hunks": hunks, "new": new, "deleted": False})]

    def test_overlapping(self):
        self.assertEqual(pm.classify(self.entry([(10, 7)]), self.entry([(14, 3)]))[0], "overlapping")

    def test_adjacent(self):
        rel, gap = pm.classify(self.entry([(10, 7)]), self.entry([(20, 3)]))
        self.assertEqual((rel, gap), ("adjacent", 4))

    def test_separate(self):
        self.assertEqual(pm.classify(self.entry([(10, 7)]), self.entry([(100, 3)]))[0], "separate")

    def test_created_file_counts_as_overlap(self):
        self.assertEqual(pm.classify(self.entry([(0, 0)], new=True), self.entry([(5, 2)]))[0], "overlapping")


if __name__ == "__main__":
    unittest.main()
