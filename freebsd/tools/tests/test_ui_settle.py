# SPDX-License-Identifier: GPL-3.0-only
"""The toolbar test waits for a layout to settle before it judges it
(freebsd/tests/browser/tests/test_70_ui.py, settled()). The browser is not
run here."""

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.abspath(os.path.join(HERE, "..", "..", "tests", "browser"))
sys.path.insert(0, SUITE)

spec = importlib.util.spec_from_file_location(
    "test_70_ui_settle", os.path.join(SUITE, "tests", "test_70_ui.py"))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept += 1
        self.now += seconds


def takes(snapshots):
    """A take() that hands out the snapshots in turn, the last one for ever."""
    left = list(snapshots)
    return lambda: left.pop(0) if len(left) > 1 else left[0]


class Settled(unittest.TestCase):
    def problems(self, rows):
        return ["HomeButton has no size"] if rows == "no width yet" else []

    def test_a_layout_that_is_fine_at_once_is_not_waited_for(self):
        clock = Clock()
        rows = ui.settled(takes(["fine"]), self.problems, clock=clock, sleep=clock.sleep)
        self.assertEqual((rows, clock.slept), ("fine", 0))

    def test_a_button_that_gets_its_size_a_moment_later_is_judged_then(self):
        clock = Clock()
        rows = ui.settled(takes(["no width yet", "no width yet", "fine"]), self.problems,
                          clock=clock, sleep=clock.sleep)
        self.assertEqual((rows, clock.slept), ("fine", 2))

    def test_a_button_that_never_gets_a_size_is_still_judged_as_it_is(self):
        clock = Clock()
        rows = ui.settled(takes(["no width yet"]), self.problems, seconds=10.0, pause=1.0,
                          clock=clock, sleep=clock.sleep)
        self.assertEqual(rows, "no width yet")
        self.assertEqual(clock.slept, 10)
        self.assertEqual(self.problems(rows), ["HomeButton has no size"])

    def test_the_wait_is_long_enough_for_a_cold_start_and_short_enough_to_fail(self):
        self.assertGreaterEqual(ui.SETTLE_SECONDS, 5)
        self.assertLessEqual(ui.SETTLE_SECONDS, 30)


if __name__ == "__main__":
    unittest.main()
