# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the evidence on Helium's canvas noise hash
(freebsd/privacy/noise-hash): the Python model against the suite's own
model, the numbers the README states, the probe page's arithmetic against
the model, and the collector's tally."""

import importlib.machinery
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EVIDENCE = os.path.join(REPO, "freebsd", "privacy", "noise-hash")
sys.path.insert(0, EVIDENCE)
sys.path.insert(0, os.path.join(REPO, "freebsd", "tests", "browser"))

import analysis  # noqa: E402
import model  # noqa: E402
from berytest import noise  # noqa: E402

loader = importlib.machinery.SourceFileLoader("noise_collect", os.path.join(EVIDENCE, "collect"))
spec = importlib.util.spec_from_loader("noise_collect", loader)
collect = importlib.util.module_from_spec(spec)
loader.exec_module(collect)

SIZES = [1031, 998, 1085, 982]   # by the token's low two bits


def moved(token, width, height, rgba, finalize=False):
    before = model.flat(width, height, rgba)
    after = model.noise_pixels(token, before, width, height, finalize=finalize)
    found = model.changed(before, after, width)
    return {(x, y) for x, y, *_ in found}, {c[2:] for c in found}


class Model(unittest.TestCase):
    def test_the_four_sets(self):
        sets = analysis.four_sets()
        self.assertEqual([len(s) for s in sets], SIZES)
        self.assertEqual(sum(SIZES), 64 * 64)
        self.assertEqual(len(frozenset().union(*sets)), 64 * 64, "the sets overlap")

    def test_agrees_with_the_suites_model_whatever_the_high_bits(self):
        rng = random.Random(1)
        for low in range(4):
            token = rng.getrandbits(64) & ~3 | low
            pixels, _ = moved(token, 64, 64, (100, 100, 100, 255))
            self.assertEqual(pixels, noise.old_moved_pixels(low, 64, 64, (100, 100, 100, 255)))
            self.assertEqual(len(pixels), SIZES[low])

    def test_two_bits_coordinates_and_red_predict_every_change(self):
        rng = random.Random(2)
        for _ in range(12):
            token = rng.getrandbits(64)
            width, height = rng.randint(3, 20), rng.randint(3, 20)
            rgba = (rng.randint(2, 253), rng.randint(2, 253), rng.randint(2, 253), 255)
            pixels, _ = moved(token, width, height, rgba)
            want = {(x, y) for y in range(height) for x in range(width)
                    if model.predicted_change(token & 3, x, y, rgba[0])}
            self.assertEqual(pixels, want, (hex(token), width, height, rgba))

    def test_the_direction_is_the_tokens_lowest_bit(self):
        rng = random.Random(3)
        for _ in range(24):
            token = rng.getrandbits(64)
            rgba = (rng.randint(2, 253), rng.randint(2, 253), rng.randint(2, 253), 255)
            _, steps = moved(token, 12, 12, rgba)
            self.assertEqual(len(steps), 1, "a flat fill moved in more than one way")
            step = next(iter(steps))
            self.assertEqual(sum(step), 1 if token & 1 else -1, (hex(token), rgba, step))
            self.assertEqual(sorted(abs(v) for v in step), [0, 0, 0, 1])

    def test_a_flat_fill_has_twelve_readbacks(self):
        rng = random.Random(4)
        seen = set()
        for _ in range(400):
            pixels, steps = moved(rng.getrandbits(64), 8, 8, (100, 100, 100, 255))
            seen.add((frozenset(pixels), frozenset(steps)))
        self.assertEqual(len(seen), 12)
        self.assertEqual(len({pixels for pixels, _ in seen}), 4)

    def test_finalizing_the_state_uses_the_whole_token(self):
        """Beryllium's change: tokens that share their low bits no longer
        share their pixels."""
        rng = random.Random(5)
        sets = set()
        for _ in range(40):
            pixels, _ = moved(rng.getrandbits(64) & ~3 | 1, 16, 16, (100, 100, 100, 255),
                              finalize=True)
            sets.add(frozenset(pixels))
        self.assertEqual(len(sets), 40)

    def test_fully_transparent_pixels_are_left_alone(self):
        before = model.flat(6, 6, (0, 0, 0, 0))
        self.assertEqual(model.noise_pixels(0x1234, before, 6, 6), before)

    def test_textured_pixels_stay_within_two_levels(self):
        rng = random.Random(6)
        before = [(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), 255)
                  for _ in range(10 * 10)]
        after = model.noise_pixels(rng.getrandbits(64), before, 10, 10)
        for a, b in zip(before, after):
            self.assertEqual(a[3], b[3])
            self.assertTrue(all(abs(p - q) <= 2 for p, q in zip(a[:3], b[:3])))


class Readme(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(EVIDENCE, "README.md")) as f:
            self.text = f.read()

    def test_every_measured_count_before_the_change_is_one_of_the_four(self):
        rows = re.findall(r"^\| (\d\d:\d\d) \| (0\.20\.3\.\d+) \| (\d+) \| (\w+) ([+-]1) \| (\d+) \|",
                          self.text, re.M)
        self.assertEqual(len(rows), 6)
        for _, _, first, _, step, second in rows:
            self.assertIn(int(first), SIZES)
            self.assertIn(int(second), SIZES)
            low = SIZES.index(int(first))
            self.assertEqual(step, "+1" if low & 1 else "-1",
                             "the README's table contradicts its own point 3")

    def test_the_stated_chance(self):
        chance = sum(analysis.binomial_pmf(4096, 0.25, k) for k in SIZES)
        self.assertAlmostEqual(chance, 0.029, places=3)
        self.assertLess(chance ** 12, 1e-18)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_console_line_is_javascript(self):
        line = re.search(r"```js\n(.*?)\n```", self.text, re.S).group(1)
        r = subprocess.run(["node", "-e", "new Function('return ' + process.argv[1])", line],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class ProbePage(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_its_arithmetic_is_the_models(self):
        with open(os.path.join(EVIDENCE, "probe.html")) as f:
            page = f.read()
        script = re.search(r"// --- model begin\n(.*?)// --- model end", page, re.S).group(1)
        fills = [(64, 64, 100), (40, 25, 37), (90, 31, 101), (33, 77, 250), (128, 16, 3),
                 (200, 3, 64)]
        self.assertIn("readFill(64, 64, [100, 100, 100])", page)
        for width, height, red in fills[1:]:
            self.assertIn(f"[{width}, {height}, [{red}, ", page, "the page draws other fills")
        code = script + "\nconst out = {};\n" + "".join(
            f"for (let low = 0; low < 4; low++) out['{w}x{h}x{r}x' + low] = "
            f"predicted(low, {w}, {h}, {r}).length;\n" for w, h, r in fills
        ) + "console.log(JSON.stringify(out));"
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        for w, h, red in fills:
            for low in range(4):
                want = sum(model.predicted_change(low, x, y, red)
                           for y in range(h) for x in range(w))
                self.assertEqual(got[f"{w}x{h}x{red}x{low}"], want, (w, h, red, low))


class Collector(unittest.TestCase):
    def test_classify(self):
        sets = collect.four_sets()
        self.assertEqual([len(s) for s in sets], SIZES)
        self.assertEqual(collect.classify([], sets), "none")
        self.assertEqual(collect.classify([list(p) for p in sets[2]], sets), 2)
        self.assertEqual(collect.classify([[0, 0], [5, 9]], sets), "other")
        almost = [list(p) for p in sets[2]][1:]
        self.assertEqual(collect.classify(almost, sets), "other")

    def sample(self, session, site, which, count, steps=("1 0 0 0",)):
        return {"session": session, "site": f"site{site}.test", "set": which, "count": count,
                "steps": list(steps)}

    def test_summary_of_a_browser_with_heliums_hash(self):
        lines = collect.summarise([self.sample(0, 0, 3, 982), self.sample(0, 1, 2, 1085, ["0 -1 0 0"]),
                                   self.sample(1, 0, 3, 982, ["0 0 1 0"])])
        text = "\n".join(lines)
        self.assertIn("3 readbacks in 2 new profiles", text)
        self.assertIn("set 3 of the four: 2 readbacks; pixels moved: 982", text)
        self.assertIn("Every noised readback (3) moved one of the same four sets", text)

    def test_summary_of_a_browser_that_uses_the_whole_token(self):
        text = "\n".join(collect.summarise([self.sample(0, 0, "other", 1016),
                                            self.sample(0, 1, "other", 994)]))
        self.assertIn("No readback moved one of the four sets (2 noised readbacks)", text)

    def test_summary_of_a_browser_without_noise(self):
        text = "\n".join(collect.summarise([self.sample(0, 0, "none", 0, [])]))
        self.assertIn("No canvas noise", text)


if __name__ == "__main__":
    unittest.main()
