# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/helium-bsd-crashpad-calls."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOL = os.path.join(HERE, "..", "helium-bsd-crashpad-calls")

_loader = importlib.machinery.SourceFileLoader("hbcc", TOOL)
_spec = importlib.util.spec_from_loader("hbcc", _loader)
hbcc = importlib.util.module_from_spec(_spec)
_loader.exec_module(hbcc)

HELIUM_PATCH = """\
--- /dev/null
+++ b/chrome/browser/foo.cc
@@ -0,0 +1,5 @@
+void F() {
+  // crash_reporter::InAComment(true);
+  crash_reporter::GetReports(&reports);
+  crash_reporter::SetUploadConsentFromUser(false);
+}
"""

FIX_PATCH = """\
Header.

--- /dev/null
+++ b/components/crash/core/app/crashpad_bsd.cc
@@ -0,0 +1,9 @@
+namespace crash_reporter {
+
+void GetReports(std::vector<Report>* reports) {
+  reports->clear();
+}
+
+void SetUploadConsentFromUser(bool consent) {}
+
+}  // namespace crash_reporter
"""


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.patches = os.path.join(d, "patches")
        os.makedirs(os.path.join(self.patches, "helium"))
        with open(os.path.join(self.patches, "series"), "w") as f:
            f.write("helium/foo.patch\n")
        self.helium = os.path.join(self.patches, "helium", "foo.patch")
        with open(self.helium, "w") as f:
            f.write(HELIUM_PATCH)
        self.fix = os.path.join(d, "fix.patch")
        with open(self.fix, "w") as f:
            f.write(FIX_PATCH)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, fix=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = hbcc.main(["--patches", self.patches, "--fix-patch", fix or self.fix])
        return rc, out.getvalue()

    def test_stub_definitions_parsed(self):
        self.assertEqual(hbcc.stub_definitions(self.fix),
                         {"GetReports", "SetUploadConsentFromUser"})

    def test_defined_calls_pass_and_comments_ignored(self):
        rc, out = self.run_tool()
        self.assertEqual(rc, 0, out)
        self.assertIn("2 calls", out)

    def test_missing_stub_fails_like_the_linker(self):
        rc, out = self.run_tool(fix=os.path.join(self.tmp.name, "absent.patch"))
        self.assertEqual(rc, 1)
        self.assertIn("crash_reporter::GetReports", out)
        self.assertIn("crash_reporter::SetUploadConsentFromUser", out)

    def test_new_helium_call_fails(self):
        with open(self.helium, "a") as f:
            f.write("+  crash_reporter::DumpWithoutCrashing();\n")
        rc, out = self.run_tool()
        self.assertEqual(rc, 1)
        self.assertIn("DumpWithoutCrashing", out)


@unittest.skipUnless(os.path.exists(os.path.join(REPO, "helium", "patches", "series")),
                     "helium submodule not checked out")
class RepositoryTests(unittest.TestCase):
    def run_tool(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = hbcc.main(list(argv))
        return rc, out.getvalue()

    def test_repository_passes(self):
        rc, out = self.run_tool()
        self.assertEqual(rc, 0, out)

    def test_without_fix_reports_the_fifth_build_link_errors(self):
        rc, out = self.run_tool("--fix-patch", os.devnull)
        self.assertEqual(rc, 1)
        # The four undefined symbols ld.lld reported on 2 November 2026.
        for fn in ("SetUploadConsentFromUser", "GetReports", "DeleteCrashReport",
                   "RequestSingleCrashUpload"):
            self.assertIn("crash_reporter::" + fn, out)
        self.assertNotIn("UploadListToValue", out)

    def test_fix_patch_is_in_series(self):
        with open(os.path.join(REPO, "patches", "series")) as f:
            self.assertIn("platform/beryllium-bsd-no-crashpad.patch", f.read().split())


if __name__ == "__main__":
    unittest.main()
