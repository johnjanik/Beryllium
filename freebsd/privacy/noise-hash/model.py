# SPDX-License-Identifier: GPL-3.0-only
"""Helium's canvas noise for 8-bit RGBA pixels, restated in Python.

A restatement of two pieces of Helium's source, to work out by arithmetic
what a readback looks like for a given per-site token:

  helium/patches/helium/core/noise/core.patch
      third_party/blink/renderer/core/helium_noise/helium_noise_hash.cc
  helium/patches/helium/core/noise/canvas.patch
      third_party/blink/renderer/core/helium_noise/canvas_noising_helper.cc
      (HeliumNoisePixels and what it calls)

read at Helium 0.20.3 (commit 2f81b9c). Both files are the same at
Helium's main on 10 November 2026 (commit 7f3ab18).

It is a model, not Helium's code, and it is only as good as its agreement
with a browser. What has been compared: which pixels of a flat fill
change, and in which direction (README.md, "What was measured"). The
path for textured areas has not been compared with a browser.
"""

MASK = (1 << 64) - 1
FNV_PRIME = 0x00000100000001B3

SMOOTH_RANGE = 2          # kSmoothNeighborhoodRgbRange
SMOOTH_FREQUENCY = 4      # kSmoothRgbNoiseFrequency
MAX_SHARED = 1            # kMaxSharedRgbNoise
MAX_INDEPENDENT = 1       # kMaxIndependentRgbNoise
MAX_ALPHA = 1             # kMaxAlphaNoise


class Hash:
    """HeliumNoiseHash. finalize: Beryllium's change (SplitMix64's finalizer
    over the state before each draw), off for Helium's own behaviour."""

    def __init__(self, state, finalize=False):
        self.state = state & MASK
        self.remaining = 0
        self.finalize = finalize

    def copy(self):
        other = Hash(self.state, self.finalize)
        other.remaining = self.remaining
        return other

    def update(self, value):
        self.state = ((self.state ^ (value & MASK)) * FNV_PRIME) & MASK
        self.remaining = 64

    def below(self, max_value):
        """GetValueBelow."""
        if max_value <= 0:
            return 0
        required = max_value.bit_length()   # std::bit_width
        assert self.remaining >= required
        state = mix(self.state) if self.finalize else self.state
        value = (state >> (64 - self.remaining)) % max_value
        self.remaining -= required
        return value


def mix(value):
    """SplitMix64's finalizer: MixCanvasCoordinateSeed in Helium, and the
    finalizer Beryllium's patch adds to the hash."""
    value ^= value >> 30
    value = value * 0xBF58476D1CE4E5B9 & MASK
    value ^= value >> 27
    value = value * 0x94D049BB133111EB & MASK
    value ^= value >> 31
    return value


def pixel_value(rgba):
    """base::U32FromLittleEndian over the pixel's four bytes."""
    r, g, b, a = rgba
    return r | g << 8 | b << 16 | a << 24


def signed(h, max_abs):
    """GetSignedNoiseValue."""
    if max_abs <= 0:
        return 0
    return h.below(max_abs * 2 + 1) - max_abs


def nonzero_signed(h):
    """GetNonZeroSignedNoiseValue."""
    return -1 if h.below(2) == 0 else 1


def smooth_vector(content, coordinate):
    """GetSmoothRgbNoiseVector. In
        noise[content_hash.GetValueBelow(3)] = GetNonZeroSignedNoiseValue(content_hash);
    the right side is evaluated first (C++17 and later), so the direction
    is drawn before the channel."""
    if coordinate.below(SMOOTH_FREQUENCY) != 0:
        return [0, 0, 0]
    direction = nonzero_signed(content)
    noise = [0, 0, 0]
    noise[content.below(3)] = direction
    return noise


def full_vector(content, coordinate):
    """GetFullRgbNoiseVector."""
    return [nonzero_signed(content) + signed(coordinate, MAX_INDEPENDENT) for _ in range(3)]


def noise_pixels(token, pixels, width, height, x_offset=0, y_offset=0, finalize=False):
    """HeliumNoisePixels: pixels is a list of (r, g, b, a), row by row;
    returns the noised list. token is the per-site canvas token."""
    token_hash = Hash(token, finalize)
    out = list(pixels)
    for y in range(height):
        for x in range(width):
            source = pixels[x + y * width]
            if source == (0, 0, 0, 0):
                continue
            value = pixel_value(source)
            content = token_hash.copy()
            content.update(value)
            low = [255, 255, 255]
            high = [0, 0, 0]
            for dy in (-1, 0, 1):
                sy = min(max(y + dy, 0), height - 1)
                for dx in (-1, 0, 1):
                    sx = min(max(x + dx, 0), width - 1)
                    sample = pixels[sx + sy * width]
                    content.update(pixel_value(sample))
                    for c in range(3):
                        low[c] = min(low[c], sample[c])
                        high[c] = max(high[c], sample[c])
            smooth = all(high[c] - low[c] <= SMOOTH_RANGE for c in range(3))
            coordinate = token_hash.copy()
            coordinate.update(mix(((y + y_offset) & 0xFFFFFFFF) << 32
                                  | ((x + x_offset) & 0xFFFFFFFF)))
            coordinate.update(value)
            rgb = smooth_vector(content, coordinate) if smooth else full_vector(content, coordinate)
            noised = []
            for i in range(4):
                channel = source[i]
                alpha = i == 3
                if alpha and channel in (0, 255):
                    noised.append(channel)
                    continue
                reach = MAX_ALPHA if alpha else MAX_SHARED + MAX_INDEPENDENT
                lowest = max(1 if alpha and channel > 0 else 0, channel - reach)
                highest = min(255, channel + reach)
                step = signed(coordinate, MAX_ALPHA) if alpha else rgb[i]
                noised.append(min(max(channel + step, lowest), highest))
            out[x + y * width] = tuple(noised)
    return out


def spare_uniform(before, after, width, height):
    """Beryllium's WebGL readback (patches/privacy/
    beryllium-noise-webgl-readpixels.patch): a pixel whose 3 x 3
    neighbourhood in the read, clamped at its edges, is one exact colour
    is put back as it was read. before, after: lists of (r, g, b, a)."""
    out = list(after)
    for y in range(height):
        for x in range(width):
            pixel = before[x + y * width]
            if all(before[min(max(x + dx, 0), width - 1)
                          + min(max(y + dy, 0), height - 1) * width] == pixel
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                out[x + y * width] = pixel
    return out


def webgl_readback(token, pixels, width, height, x=0, y=0, finalize=True):
    """What readPixels(x, y, width, height, RGBA, UNSIGNED_BYTE) hands a
    page with that patch: the canvas noise anchored to the framebuffer,
    uniform neighbourhoods spared. Rows as WebGL gives them, bottom first."""
    noised = noise_pixels(token, pixels, width, height, x, y, finalize=finalize)
    return spare_uniform(pixels, noised, width, height)


def changed(before, after, width):
    """[(x, y, dr, dg, db, da)] for every pixel that differs."""
    found = []
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b:
            found.append((i % width, i // width) + tuple(q - p for p, q in zip(a, b)))
    return found


def flat(width, height, rgba):
    return [tuple(rgba)] * (width * height)


def predicted_change(token_low2, x, y, red):
    """Whether a pixel in a smooth area changes, from two bits of the token,
    its coordinates and the low two bits of its red channel. The low two
    bits of an FNV step depend only on the low two bits going in, and the
    FNV prime is 3 modulo 4."""
    step = ((token_low2 ^ mix(y << 32 | x)) * 3) & 3
    return ((step ^ red) * 3) & 3 == 0
