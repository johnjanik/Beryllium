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



class GpuPageLines(unittest.TestCase):
    """Rows of the GPU page (read through its shadow trees) to report lines.
    The rows are those of a real chrome://gpu page, shortened, with a second
    GPU as a machine with two shows them."""

    ROWS = [
        ["Canvas", "Hardware accelerated"],
        ["GPU0 :", "VENDOR= 0x10de [Google Inc. (NVIDIA Corporation)], DEVICE=0x2c58 *ACTIVE*"],
        ["GPU1 :", "VENDOR= 0x8086 [Intel], DEVICE=0x7d67"],
        ["Optimus :", "false"],
        ["AMD switchable :", "false"],
        ["Driver vendor", "NVIDIA"],
        ["Info", "Display[2300000000] bounds=[0,0 800x600], scale=1"],
        ["Color space (all)", "{primaries:BT709, transfer:SRGB, matrix:RGB, range:FULL}"],
        ["Buffer format (all)", "RGBA_8888"],
        ["SDR white level in nits", "203"],
        ["Bits per color component", "8"],
        ["", ""],
        [],
    ]

    def test_gpus_and_displays_are_kept(self):
        lines = rendering.gpu_page_lines(self.ROWS)
        self.assertEqual(lines[0], "GPU0: VENDOR= 0x10de [Google Inc. (NVIDIA Corporation)], "
                                   "DEVICE=0x2c58 *ACTIVE*")
        self.assertEqual(lines[1], "GPU1: VENDOR= 0x8086 [Intel], DEVICE=0x7d67")
        self.assertIn("Optimus: false", lines)
        self.assertIn("AMD switchable: false", lines)
        self.assertTrue(any(l.startswith("Info: Display[") for l in lines))
        self.assertIn("Bits per color component: 8", lines)

    def test_other_rows_are_dropped(self):
        lines = rendering.gpu_page_lines(self.ROWS)
        self.assertFalse(any(l.startswith(("Canvas", "Driver vendor")) for l in lines))

    def test_nothing_from_nothing(self):
        self.assertEqual(rendering.gpu_page_lines([]), [])
        self.assertEqual(rendering.gpu_page_lines([["", ""], []]), [])

    def test_long_values_are_cut(self):
        lines = rendering.gpu_page_lines([["GPU0", "x" * 2000]])
        self.assertEqual(len(lines[0]), 400)

    def test_the_page_script_walks_shadow_trees(self):
        self.assertIn("shadowRoot", rendering.GPU_ROWS)
        self.assertIn("'TR'", rendering.GPU_ROWS)


class RenderNode(unittest.TestCase):
    """The render node and who chose it, from the GPU page's command line."""

    ROW = ["Command Line :", "/usr/local/share/beryllium/beryllium --no-first-run "
           "--render-node-override=/dev/dri/renderD128 --flag-switches-begin"]

    def test_the_browsers_own_choice(self):
        line = rendering.render_node([["Canvas", "x"], self.ROW])
        self.assertTrue(line.startswith("render node: /dev/dri/renderD128 (the browser's own"))

    def test_named_by_the_run(self):
        line = rendering.render_node(
            [self.ROW], ["--foo", "--render-node-override=/dev/dri/renderD128"])
        self.assertEqual(line, "render node: /dev/dri/renderD128 (named by this run's switch)")

    def test_no_switch_on_the_page(self):
        self.assertIsNone(rendering.render_node([["Command Line", "beryllium --no-first-run"]]))
        self.assertIsNone(rendering.render_node([]))


if __name__ == "__main__":
    unittest.main()
