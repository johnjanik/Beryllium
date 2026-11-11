#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""The numbers in README.md that come from arithmetic, recomputed.

  python3 analysis.py            prints them (under a minute)
  python3 analysis.py --tokens N random tokens to try (default 300)

Everything here is the model (model.py), not a browser. What a browser
did is in README.md under "What was measured".
"""

import argparse
import math
import random
import sys

import model

WIDTH = HEIGHT = 64
FILL = (100, 100, 100, 255)


def positions(token, finalize=False):
    before = model.flat(WIDTH, HEIGHT, FILL)
    after = model.noise_pixels(token, before, WIDTH, HEIGHT, finalize=finalize)
    found = model.changed(before, after, WIDTH)
    return frozenset((x, y) for x, y, *_ in found), frozenset(c[2:] for c in found)


def four_sets():
    return [frozenset((x, y) for y in range(HEIGHT) for x in range(WIDTH)
                      if model.predicted_change(low, x, y, FILL[0])) for low in range(4)]


def binomial_pmf(n, p, k):
    log = (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
           + k * math.log(p) + (n - k) * math.log(1 - p))
    return math.exp(log)


def survey(tokens, finalize):
    """Over random 64-bit tokens: the different sets of moved pixels, the
    different whole readbacks, and the counts of moved pixels."""
    sets, readbacks, counts = set(), set(), []
    for token in tokens:
        moved, steps = positions(token, finalize)
        sets.add(moved)
        readbacks.add((moved, steps))
        counts.append(len(moved))
    return sets, readbacks, counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", type=int, default=300)
    o = ap.parse_args(argv)
    rng = random.Random(20261111)
    tokens = [rng.getrandbits(64) for _ in range(o.tokens)]

    sets = four_sets()
    sizes = [len(s) for s in sets]
    print(f"The four sets for a {WIDTH} x {HEIGHT} fill of rgb{FILL[:3]}: sizes {sizes}, "
          f"sum {sum(sizes)} of {WIDTH * HEIGHT}; every pixel is in exactly one: "
          f"{all(sum((x, y) in s for s in sets) == 1 for x in range(WIDTH) for y in range(HEIGHT))}")

    weak_sets, weak_readbacks, weak_counts = survey(tokens, finalize=False)
    print(f"Helium's hash, {len(tokens)} random tokens: {len(weak_sets)} different sets of moved "
          f"pixels, all among the four: {weak_sets <= set(sets)}; "
          f"{len(weak_readbacks)} different whole readbacks; counts seen: {sorted(set(weak_counts))}")
    by_low = {}
    for token in tokens:
        moved, steps = positions(token)
        by_low.setdefault(token & 3, set()).update(s for s in steps)
    for low in sorted(by_low):
        print(f"  token's low two bits {low}: set of {sizes[low]} pixels, steps seen "
              f"(red green blue alpha): {sorted(by_low[low])}")

    fixed_sets, fixed_readbacks, fixed_counts = survey(tokens, finalize=True)
    mean = sum(fixed_counts) / len(fixed_counts)
    spread = (sum((c - mean) ** 2 for c in fixed_counts) / len(fixed_counts)) ** 0.5
    print(f"With the state finalized before each draw, the same tokens: {len(fixed_sets)} "
          f"different sets; any of the four: {bool(fixed_sets & set(sets))}; "
          f"counts from {min(fixed_counts)} to {max(fixed_counts)}, mean {mean:.1f}, "
          f"standard deviation {spread:.1f}")

    n, p = WIDTH * HEIGHT, 1 / 4
    chance = sum(binomial_pmf(n, p, k) for k in sizes)
    print(f"If each pixel moved independently with chance 1/4: mean {n * p:.0f}, standard "
          f"deviation {math.sqrt(n * p * (1 - p)):.1f}; chance that a count is one of "
          f"{sorted(sizes)}: {chance:.4f}; that twelve counts in a row all are: {chance ** 12:.1e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
