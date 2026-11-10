# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the model of Helium's canvas noise before Beryllium 0.20.3.17
(freebsd/tests/browser/berytest/noise.py), which the browser suite uses to
recognise a build whose noise positions follow two bits of the token."""

import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests", "browser"))
from berytest import noise  # noqa: E402

FILL = (64, 64, (100, 100, 100, 255))  # the suite's probe

# The first row of moved pixels in the owner's 0.20.3.16 report (10 November
# 2026), where 127.0.0.1 and localhost both moved 982 pixels.
REPORTED_ROW_0 = [9, 19, 22, 26, 33, 39, 44, 45, 46, 49, 52, 55, 61, 62]
REPORTED_ROW_1 = [0, 10, 13, 20, 21, 23, 24, 31, 35, 36, 39, 48, 49, 51, 52, 53, 55, 63]


class OldSets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets = noise.old_sets(*FILL)

    def test_sizes_are_the_counts_every_report_showed(self):
        # Reports of 0.20.3.14 to 0.20.3.16 showed 982, 998 and 1085 changed
        # pixels and no other number; 1031 is the fourth.
        self.assertEqual([len(s) for s in self.sets], [1031, 998, 1085, 982])

    def test_the_four_sets_split_the_canvas(self):
        self.assertEqual(sum(len(s) for s in self.sets), 64 * 64)
        self.assertEqual(len(set().union(*self.sets)), 64 * 64)

    def test_set_three_is_what_the_report_listed(self):
        for y, row in ((0, REPORTED_ROW_0), (1, REPORTED_ROW_1)):
            self.assertEqual(sorted(x for x, yy in self.sets[3] if yy == y), row)

    def test_only_two_bits_of_the_token_matter(self):
        rng = random.Random(7)
        for _ in range(12):
            token = rng.getrandbits(64)
            self.assertEqual(noise.old_moved_pixels(token, 16, 16, FILL[2]),
                             noise.old_moved_pixels(token % 4, 16, 16, FILL[2]))

    def test_recognises_each_set(self):
        for low, moved in enumerate(self.sets):
            self.assertEqual(noise.old_set_of(moved, *FILL), low)

    def test_other_sets_are_not_recognised(self):
        self.assertIsNone(noise.old_set_of(set(), *FILL))
        one_less = set(self.sets[3])
        one_less.pop()
        self.assertIsNone(noise.old_set_of(one_less, *FILL))
        rng = random.Random(3)
        scattered = {(rng.randrange(64), rng.randrange(64)) for _ in range(1000)}
        self.assertIsNone(noise.old_set_of(scattered, *FILL))

    def test_the_pixel_value_changes_the_sets(self):
        # Another fill colour gives other sets: the model must be told what
        # the probe drew.
        other = noise.old_sets(64, 64, (101, 100, 100, 255))
        self.assertNotEqual(other[3], self.sets[3])


class Key(unittest.TestCase):
    def test_parse_key(self):
        self.assertEqual(noise.parse_key("9,0;19,0;0,1"), {(9, 0), (19, 0), (0, 1)})
        self.assertEqual(noise.parse_key(""), set())

    def test_round_trip_with_the_probe_format(self):
        moved = noise.old_moved_pixels(3, 8, 8, FILL[2])
        key = ";".join(f"{x},{y}" for x, y in sorted(moved, key=lambda p: (p[1], p[0])))
        self.assertEqual(noise.parse_key(key), moved)

    def test_pixel_value_is_little_endian_rgba(self):
        self.assertEqual(noise.pixel_value((100, 100, 100, 255)), 0xFF646464)
        self.assertEqual(noise.pixel_value((1, 2, 3, 4)), 0x04030201)


if __name__ == "__main__":
    unittest.main()
