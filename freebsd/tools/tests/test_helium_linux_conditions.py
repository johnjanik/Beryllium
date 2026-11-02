# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/helium-linux-conditions."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOL = os.path.join(HERE, "..", "helium-linux-conditions")

_loader = importlib.machinery.SourceFileLoader("hlc", TOOL)
_spec = importlib.util.spec_from_loader("hlc", _loader)
hlc = importlib.util.module_from_spec(_spec)
_loader.exec_module(hlc)

HELIUM_PATCH = """\
--- a/chrome/foo.cc
+++ b/chrome/foo.cc
@@ -1,3 +1,7 @@
 #include "chrome/foo.h"
+#if BUILDFLAG(IS_LINUX)
+int x = 1;
+#endif  // BUILDFLAG(IS_LINUX)
+// is_linux in prose is ignored
"""

FIX_PATCH = """\
Header text.

--- a/chrome/foo.cc
+++ b/chrome/foo.cc
@@ -1,4 +1,4 @@
 #include "chrome/foo.h"
-#if BUILDFLAG(IS_LINUX)
+#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_BSD)
 int x = 1;
-#endif  // BUILDFLAG(IS_LINUX)
+#endif  // BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_BSD)
"""


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.patches = os.path.join(d, "patches")
        os.makedirs(os.path.join(self.patches, "helium"))
        with open(os.path.join(self.patches, "series"), "w") as f:
            f.write("# comment\nhelium/foo.patch\n")
        with open(os.path.join(self.patches, "helium", "foo.patch"), "w") as f:
            f.write(HELIUM_PATCH)
        self.fix = os.path.join(d, "fix.patch")
        with open(self.fix, "w") as f:
            f.write(FIX_PATCH)
        self.reviewed = os.path.join(d, "reviewed.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = hlc.main(["--patches", self.patches, "--reviewed", self.reviewed,
                           "--fix-patch", self.fix, *extra])
        return rc, out.getvalue()

    def set_decisions(self, decision, reason=None):
        with open(self.reviewed) as f:
            data = json.load(f)
        for e in data["lines"]:
            e["decision"] = decision
            if reason:
                e["reason"] = reason
        with open(self.reviewed, "w") as f:
            json.dump(data, f)

    def test_finds_only_added_linux_lines(self):
        lines = hlc.helium_lines(self.patches)
        self.assertEqual([e["line"] for e in lines],
                         ["#if BUILDFLAG(IS_LINUX)", "#endif  // BUILDFLAG(IS_LINUX)"])
        self.assertEqual({e["file"] for e in lines}, {"chrome/foo.cc"})

    def test_new_lines_are_unreviewed_and_fail(self):
        self.assertEqual(self.run_tool("--write")[0], 0)
        rc, out = self.run_tool()
        self.assertEqual(rc, 1)
        self.assertIn("unreviewed", out)

    def test_bsd_like_linux_passes_when_fix_patch_changes_line(self):
        self.run_tool("--write")
        self.set_decisions("bsd-like-linux")
        self.assertEqual(self.run_tool()[0], 0)

    def test_bsd_like_linux_fails_when_fix_patch_misses_line(self):
        self.run_tool("--write")
        self.set_decisions("bsd-like-linux")
        with open(self.fix, "w") as f:
            f.write(FIX_PATCH.replace("-#endif  // BUILDFLAG(IS_LINUX)\n", " #endif  // BUILDFLAG(IS_LINUX)\n"))
        rc, out = self.run_tool()
        self.assertEqual(rc, 1)
        self.assertIn("does not change it", out)

    def test_linux_only_needs_reason(self):
        self.run_tool("--write")
        self.set_decisions("linux-only")
        self.assertEqual(self.run_tool()[0], 1)
        self.set_decisions("linux-only", reason="uses /proc")
        self.assertEqual(self.run_tool()[0], 0)

    def test_helium_update_adding_condition_fails(self):
        self.run_tool("--write")
        self.set_decisions("bsd-like-linux")
        with open(os.path.join(self.patches, "helium", "foo.patch"), "a") as f:
            f.write("+#elif BUILDFLAG(IS_LINUX)\n")
        rc, out = self.run_tool()
        self.assertEqual(rc, 1)
        self.assertIn("new line from Helium", out)

    def test_write_keeps_decisions(self):
        self.run_tool("--write")
        self.set_decisions("linux-only", reason="kept")
        self.run_tool("--write")
        with open(self.reviewed) as f:
            data = json.load(f)
        self.assertTrue(all(e["decision"] == "linux-only" and e["reason"] == "kept"
                            for e in data["lines"]))


@unittest.skipUnless(os.path.exists(os.path.join(REPO, "helium", "patches", "series")),
                     "helium submodule not checked out")
class RepositoryTests(unittest.TestCase):
    def test_repository_list_is_complete(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = hlc.main([])
        self.assertEqual(rc, 0, out.getvalue())

    def test_fix_patch_is_in_series(self):
        with open(os.path.join(REPO, "patches", "series")) as f:
            self.assertIn("platform/beryllium-bsd-helium-linux-conditions.patch",
                          f.read().split())


if __name__ == "__main__":
    unittest.main()
