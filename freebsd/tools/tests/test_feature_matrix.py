# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/feature-matrix."""

import importlib.machinery
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "feature-matrix")

_loader = importlib.machinery.SourceFileLoader("feature_matrix", TOOL)
_spec = importlib.util.spec_from_loader("feature_matrix", _loader)
fm = importlib.util.module_from_spec(_spec)
_loader.exec_module(fm)

REDTEAM = "| RT-04 | High | sandbox status |\n"


def feature(**kw):
    base = {"id": "S-REN-01", "group": "Capsicum renderer sandbox",
            "title": "Renderers enter capability mode",
            "need": "Every renderer calls cap_enter before it handles web content.",
            "priority": "must", "phase": 2, "implemented": "todo", "built": "no",
            "tested": "planned", "planned_test": "sandbox suite: procstat shows C",
            "source": ["plan/06.md §3.1", "RT-04"]}
    base.update(kw)
    return base


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        for rel, text in {"plan/06.md": "# model\n",
                          "patches/security/a.patch": "--- a/x\n",
                          "tests/test_sandbox.py": "def test_capability_mode():\n    pass\n"}.items():
            path = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)

    def tearDown(self):
        self.tmp.cleanup()

    def problems(self, *features):
        return fm.check({}, list(features), repo=self.repo, redteam_text=REDTEAM)

    def test_valid_row(self):
        self.assertEqual(self.problems(feature()), [])

    def test_done_needs_code(self):
        p = self.problems(feature(implemented="done"))
        self.assertTrue(any('needs "where"' in x for x in p), p)

    def test_passing_needs_test_and_evidence(self):
        p = self.problems(feature(implemented="done", where=["patches/security/a.patch"],
                                  tested="passing"))
        self.assertTrue(any('needs "tests"' in x for x in p), p)
        self.assertTrue(any('needs "evidence"' in x for x in p), p)

    def test_test_name_must_exist(self):
        ok = feature(implemented="done", where=["patches/security/a.patch"], tested="written",
                     tests=["tests/test_sandbox.py::test_capability_mode"])
        self.assertEqual(self.problems(ok), [])
        bad = feature(implemented="done", where=["patches/security/a.patch"], tested="written",
                      tests=["tests/test_sandbox.py::test_missing"])
        self.assertTrue(any("has no test_missing" in x for x in self.problems(bad)))

    def test_missing_paths_and_unknown_rt(self):
        p = self.problems(feature(source=["plan/nope.md §2", "RT-99"]))
        self.assertTrue(any("plan/nope.md does not exist" in x for x in p), p)
        self.assertTrue(any("RT-99 is not in" in x for x in p), p)

    def test_cannot_ship_unimplemented(self):
        p = self.problems(feature(built="v0.20.3.1-1"))
        self.assertTrue(any("cannot have shipped" in x for x in p), p)

    def test_bad_values_and_duplicates(self):
        p = self.problems(feature(id="X-1", priority="urgent", phase=9, tested="maybe",
                                  built="0.20"), feature(id="X-1"))
        for needle in ("id must look like", "priority must be", "phase must be",
                       "tested must be", "built must be", "duplicate id"):
            self.assertTrue(any(needle in x for x in p), (needle, p))

    def test_disabled_needs_reason(self):
        p = self.problems(feature(implemented="disabled"))
        self.assertTrue(any('needs "notes"' in x for x in p), p)

    def test_ref_path(self):
        self.assertEqual(fm.ref_path("plan/06-SECURITY-MODEL.md §3.1"), "plan/06-SECURITY-MODEL.md")
        self.assertEqual(fm.ref_path("a/b.py::C.test_x"), "a/b.py")
        self.assertIsNone(fm.ref_path("RT-04"))
        self.assertIsNone(fm.ref_path("owner's report"))


class Render(unittest.TestCase):
    def test_render_groups_and_next_phase(self):
        rows = [feature(),
                feature(id="S-REN-02", title="Descriptor allowlist", phase=3, priority="should"),
                feature(id="P-NET-01", group="Network silence", title="No contact when idle",
                        phase=1, implemented="inherited", built="v0.20.3.1-1", tested="passing",
                        tests=["tests/test_sandbox.py"], evidence="owner, 16.0-CURRENT")]
        text = fm.render({"as_of": "2026-11-04", "release": "v0.20.3.1-1", "next_phase": 2}, rows)
        self.assertIn("## Next: phase 2", text)
        self.assertIn("`S-REN-01` Renderers enter capability mode", text)
        self.assertNotIn("`S-REN-02` Descriptor allowlist (", text)
        self.assertLess(text.index("## Privacy"), text.index("## Security"))
        self.assertIn("### Network silence", text)
        self.assertIn("| Privacy | 1 | 1 | 1 | 1 |", text)

    def test_open_items(self):
        rows = [feature(), feature(id="S-REN-02", implemented="done", tested="passing",
                                   where=["x"], tests=["y"], evidence="z")]
        self.assertEqual(len(fm.open_items(rows, phase=2)), 1)


class RepositoryData(unittest.TestCase):
    def test_repository_matrix_is_valid_and_current(self):
        if not os.path.exists(fm.DATA):
            self.skipTest("no plan/feature-matrix.toml yet")
        self.assertEqual(fm.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
