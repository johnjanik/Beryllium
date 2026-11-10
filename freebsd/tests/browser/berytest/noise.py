# SPDX-License-Identifier: GPL-3.0-only
"""A model of which pixels Helium's canvas noise moved in a flat fill
before Beryllium 0.20.3.17, to recognise that behaviour in a readback.

Helium's noise hash (helium/patches/helium/core/noise/core.patch,
helium_noise_hash.cc) takes an FNV-1a step per value (xor, multiply by the
FNV prime) and hands out its bits from the low end. In a smooth area a
pixel moves when a draw below 4 on the hash of (token, coordinates, pixel
value) gives 0. That draw is the low two bits of the hash, and the low two
bits of a product depend only on the low two bits of its factors: of the
64-bit per-site token, two bits decided which pixels moved. A flat fill
had four possible sets of moved pixels, the same four in every browser
with this code. patches/privacy/beryllium-noise-hash-whole-token.patch
finalizes the hash before the draw; a build with it moves none of the four
sets.
"""

MASK = (1 << 64) - 1
FNV_PRIME = 0x00000100000001B3


def mix_coordinate(value):
    """MixCanvasCoordinateSeed in Helium's canvas noise (SplitMix64's
    finalizer), applied to (y << 32 | x) before it enters the hash."""
    value ^= value >> 30
    value = value * 0xBF58476D1CE4E5B9 & MASK
    value ^= value >> 27
    value = value * 0x94D049BB133111EB & MASK
    value ^= value >> 31
    return value


def pixel_value(rgba):
    """A pixel as the noise code hashes it: its four bytes, little endian."""
    r, g, b, a = rgba
    return r | g << 8 | b << 16 | a << 24


def old_moved_pixels(token, width, height, rgba):
    """The (x, y) the old hash moved in a width x height fill of rgba read
    back from (0, 0), for a token; only token % 4 matters."""
    source = pixel_value(rgba)
    moved = set()
    for y in range(height):
        for x in range(width):
            h = ((token & MASK) ^ mix_coordinate(y << 32 | x)) * FNV_PRIME & MASK
            h = (h ^ source) * FNV_PRIME & MASK
            if h % 4 == 0:
                moved.add((x, y))
    return moved


def old_sets(width, height, rgba):
    """The four sets, by the token's low two bits."""
    return [old_moved_pixels(low, width, height, rgba) for low in range(4)]


def old_set_of(pixels, width, height, rgba):
    """The token's low two bits if pixels is one of the four sets of the old
    hash, else None."""
    pixels = set(pixels)
    for low, moved in enumerate(old_sets(width, height, rgba)):
        if pixels == moved:
            return low
    return None


def parse_key(key):
    """The probe's "x,y;x,y;..." as a set of (x, y)."""
    return {tuple(int(n) for n in part.split(",")) for part in key.split(";") if part}
