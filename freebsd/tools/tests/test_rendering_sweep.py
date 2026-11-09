# SPDX-License-Identifier: GPL-3.0-only
"""The rendering test's sweep summary (freebsd/tests/browser/tests/
test_40_rendering.py): the greys that did not read back as drawn, reduced
to what they have in common."""

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUITE = os.path.join(REPO, "freebsd", "tests", "browser")
sys.path.insert(0, SUITE)

spec = importlib.util.spec_from_file_location(
    "test_40_rendering", os.path.join(SUITE, "tests", "test_40_rendering.py"))
rendering = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rendering)


class SweepSummary(unittest.TestCase):
    def test_nothing_off(self):
        self.assertEqual(rendering.sweep_summary([]), "none")

    def test_the_0_20_3_13_pattern(self):
        # Every fourth step of the old step-5 sweep, one channel up by one.
        off = ["15->16,15,15,255", "35->36,35,35,255", "55->55,55,56,255",
               "75->75,76,75,255", "95->95,96,95,255"]
        s = rendering.sweep_summary(off)
        self.assertIn("5 of 256 greys off", s)
        self.assertIn("steps {1: 5}", s)
        self.assertIn("'R': 2", s)
        self.assertIn("'G': 2", s)
        self.assertIn("'B': 1", s)
        self.assertIn("values 15..95 with gaps [20]", s)
        self.assertNotIn("second time", s)

    def test_a_second_read_that_differs_is_counted(self):
        off = ["20->19,20,20,255 then 20,20,20,255", "40->40,39,40,255"]
        s = rendering.sweep_summary(off)
        self.assertIn("2 of 256 greys off", s)
        self.assertIn("steps {-1: 2}", s)
        self.assertIn("1 read differently the second time", s)

    def test_malformed_entries_are_ignored(self):
        self.assertEqual(rendering.sweep_summary(["garbage"]), "none")


if __name__ == "__main__":
    unittest.main()
