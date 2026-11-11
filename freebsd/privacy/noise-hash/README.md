# Helium's canvas noise: two bits of the token choose the pixels

Collected on 11 November 2026 for the owner's report to Helium. This is
the evidence, with a way to check each part. It is not the report: see
"Reporting" at the end.

Measured on Helium itself that day, release 0.21.2.1 on macOS and on
Fedora: all 60 readbacks changed exactly one of the four sets below, the
same sets on both machines. The same runs showed two further things about
the noise that have nothing to do with the hash; they are under "Two more
things the battery found".

## The finding

Helium gives each site a 64-bit noise token per profile session and
changes about one pixel in four of a smooth canvas area on readback. Which
pixels change is decided by the lowest two bits of that token. Every site,
profile and machine therefore changes one of the same four sets of pixels
in a given image, and the direction of the change follows the token's
lowest bit. A page can learn the two bits from one readback of a fill it
drew itself, and then knows for every smooth pixel of anything else it
draws whether noise was applied there.

## The code

Read at Helium 0.20.3 (commit `2f81b9c`, the tag Beryllium pins). Both
files are byte for byte the same at Helium's main on 10 November 2026
(commit `7f3ab18`, Chromium 157).

`third_party/blink/renderer/core/helium_noise/helium_noise_hash.cc`, from
`patches/helium/core/noise/core.patch`:

```cpp
void HeliumNoiseHash::Update(const uint64_t value) {
  token_hash_ ^= value;
  token_hash_ *= kFnvPrime;
  remaining_bits_ = 64;
}

int HeliumNoiseHash::GetValueBelow(const int max_value) {
  ...
  int value = (token_hash_ >> (64 - remaining_bits_)) % max_value;
```

`canvas_noising_helper.cc`, from `patches/helium/core/noise/canvas.patch`,
for a pixel whose 3 by 3 neighbourhood is smooth:

```cpp
  if (coordinate_hash.GetValueBelow(kSmoothRgbNoiseFrequency) != 0) {  // 4
    return {0, 0, 0};
  }
  RgbNoise noise = {0, 0, 0};
  noise[content_hash.GetValueBelow(3)] =
      GetNonZeroSignedNoiseValue(content_hash);
```

`coordinate_hash` is the token, updated with the mixed coordinates and
then with the pixel's value. The first draw after an update takes the
lowest bits of the state.

## The arithmetic

In a multiplication modulo 2^64 the low k bits of the product depend only
on the low k bits of the factors, and xor works bit by bit. So after any
number of `Update()` steps, the low two bits of the state depend only on
the low two bits of the token and of each value fed in. The FNV prime is 3
modulo 4. For a pixel at (x, y) with red value r (red is the low byte of
the pixel as hashed), with t the token modulo 4 and m the mixed
coordinates modulo 4:

    the pixel changes  if and only if  (((t xor m) * 3) xor r) * 3 = 0  (mod 4)

What follows from that alone:

1. **Four sets.** For a given image there are four possible sets of
   changed pixels in its smooth areas, one per value of t.
2. **They share nothing.** For each pixel exactly one value of t changes
   it. For a 64 by 64 fill of rgb(100,100,100) the four sets have 1031,
   998, 1085 and 982 pixels, which add up to all 4096.
3. **The direction is the lowest bit.** In the assignment above the right
   side is evaluated first (C++17), so the direction is the content hash's
   first draw, its bit 0. In a flat fill the content hash is the token
   updated ten times with the same value, and bit 0 comes out as the
   token's bit 0: an even token steps down, an odd one up.
4. **Twelve readbacks.** The channel is a draw below 3, which does depend
   on the whole state. So a flat fill has 12 possible readbacks in the
   world: four sets of pixels, each with its direction, times three
   channels.

By the same reasoning, and not measured: in textured areas each channel's
step is one of plus or minus one, taken from bits 0, 2 and 4 of the
content hash (so from the token's low five bits), plus a draw below 3 on
the coordinate hash that depends on the whole token. The audio and
hardware-concurrency noise use the same hash, but their first draws are
below 10001 and below 3, which use the whole state.

`model.py` restates the 8-bit path in Python. `analysis.py` recomputes the
numbers above from it: over 300 random tokens it finds 4 sets, 12 whole
readbacks and no count other than 982, 998, 1031 and 1085.

## What was measured

On the owner's machine (FreeBSD 16.0-CURRENT, amd64), with Beryllium
0.20.3.15 and 0.20.3.16, which carry Helium 0.20.3's noise code unchanged.
Each run is a new profile; the suite fills a 64 by 64 canvas with
rgb(100,100,100) on two sites served from the same machine (127.0.0.1 and
localhost) and reads it back.

| Run (local time, 10 Nov 2026) | Version | Pixels changed, first site | Step | Pixels changed, second site | Same pixels on both |
|---|---|---|---|---|---|
| 12:43 | 0.20.3.15 | 982 | blue +1 | 1085 | no |
| 12:46 | 0.20.3.15 | 998 | green +1 | 1085 | no |
| 16:27 | 0.20.3.16 | 982 | green +1 | 982 | yes |
| 16:37 | 0.20.3.16 | 1031 | red -1 | 1031 | yes |
| 17:58 | 0.20.3.16 | 982 | red +1 | 1085 | no |
| 18:07 | 0.20.3.16 | 998 | green +1 | 998 | yes |

- All twelve counts are one of 982, 998, 1031 and 1085. If each pixel
  moved independently with chance one in four, a count would be one of
  those four numbers about 3 times in 100, and twelve in a row about 4
  times in 10^19.
- In the 18:07 run the suite compared the changed pixels with the model's
  four sets pixel by pixel: exactly the set for t = 1. The header of
  `patches/privacy/beryllium-noise-hash-whole-token.patch` records the
  same exact match for the 982 and the 1031 pixels of the 16:27 and 16:37
  runs.
- The step follows the set as point 3 says in all six runs that recorded
  it: 982 and 998 (odd t) step up, 1031 (even t) steps down.
- Two sites changed the same pixels in three sessions of six. One in four
  is expected; six sessions cannot tell those apart.

With Beryllium's change (0.20.3.17, 11 November 2026, four new profiles,
two sites each): 1016, 994, 1022, 1000, 1023, 1061, 1052 and 1000 pixels,
other pixels on the two sites every time, and none of the four sets.

## Measured on Helium itself

The owner ran the battery (below) on 11 November 2026 against Helium
0.21.2.1 (Chromium 157.0.8103.50) as released: on macOS (Darwin 27.2) on
Apple silicon, and on Fedora 43 on x86_64. On each machine: one control profile
with the canvas noise switched off, then five new profiles, six sites
each. Thirty readbacks a machine, sixty in all.

| | macOS, arm64 | Fedora, x86_64 |
|---|---|---|
| Control, noise off: every readback exact | 6 of 6 | 6 of 6 |
| Readbacks with noise | 30 of 30 | 30 of 30 |
| Changed pixels are exactly one of the four sets | 30 of 30 | 30 of 30 |
| Readbacks per set 0, 1, 2, 3 | 6, 8, 7, 9 | 7, 6, 9, 8 |
| Counts of changed pixels seen | 982, 998, 1031, 1085 | 982, 998, 1031, 1085 |
| The same canvas read twice gives the same pixels | 30 of 30 | 30 of 30 |
| Five other fills predicted pixel for pixel from two bits | 30 of 30 | 30 of 30 |
| The step's direction follows the token's lowest bit | 30 of 30 | 30 of 30 |
| A rectangle read at (5, 7) follows canvas coordinates | 30 of 30 | 30 of 30 |
| Textured image: one value of five low bits explains every step | 30 of 30 | 30 of 30 |
| and its two low bits are the flat fill's | 30 of 30 | 30 of 30 |
| Mixed image: the same five bits explain every pixel | 30 of 30 | 30 of 30 |
| Pairs of sites in one profile with the same changed pixels | 20 of 75 | 13 of 75 |
| `toDataURL` and `toBlob` give the pixels of `getImageData` | 12 of 30 | 10 of 30 |
| WebGL `readPixels` is noised | 0 of 30 | 0 of 30 |
| `toDataURL` of a WebGL canvas changes one of the four sets | 30 of 30 | 30 of 30 |

What that establishes:

- **The four sets, on Helium, on two systems and two processor
  families.** Every set seen has the same digest on both machines, and it
  is the digest of the set the Python model gives: `57b58ab8645d`,
  `146daf6c71a9`, `fdce97e9dd5f` and `5bbce908f02c` for sets 0 to 3. The
  release tested is newer than the one Beryllium pins.
- **The two bits predict everything about a flat area.** 300 other fills
  of other sizes and colours, every changed pixel, and the direction of
  every step.
- **The textured path, measured for the first time.** The page puts an
  image of known pixels on the canvas and tries all 32 values of the
  token's low five bits. In all 60 readbacks exactly one value accounts
  for the sign of every step: 276,061 channel steps in the textured
  image, and in the mixed image 265,679 more together with all 143,400
  smooth pixels. Its low two bits are the flat fill's every time. So in
  textured areas each channel's plus or minus one is fixed by five bits
  of the token, as the arithmetic says; the other part of the step, a
  draw below 3, was not predicted and is not expected to be.
- **Sites share their pixels about one time in four:** 33 of 150 pairs.

## What was not measured

- Canvases with floating-point pixels.
- A real fingerprinting script, and whether any of this recovers a stable
  fingerprint from one.
- The two routes added to the battery after these runs (a canvas copied
  into a WebGL texture, and into a video frame): see the next section.

## Two more things the battery found

Neither is about the hash, and Beryllium's change to the hash does not
touch either. Both are in Beryllium too, where they have not been tested.

**A snapshot of a canvas is noised differently from `getImageData`.**
`toDataURL` and `toBlob` (and `convertToBlob` on an `OffscreenCanvas`)
gave the pixels of `getImageData` in 22 readbacks of 60, and those 22 are
exactly the readbacks whose step fell on green. In the other 38 the step
fell on red or blue. For the textured and mixed images the two never
agreed, 0 of 60. The source says why. `canvas_noising_helper.cc` reads a
snapshot back in the snapshot's own pixel format where that is one of

```cpp
    case kRGBA_8888_SkColorType:
    case kBGRA_8888_SkColorType:
```

and runs the same four-bytes-a-pixel arithmetic over it. `ImageData` is
always red, green, blue, alpha; a snapshot on these machines is blue,
green, red, alpha. So for a snapshot the "low byte" that the hash sees is
blue, and channel 0 is blue. A grey fill hashes the same either way, which
is why its pixels and direction agree and only the channel moves; any
other content gets different noise altogether. A site therefore holds two
differently noised copies of one canvas for the asking. What that is
worth to a tracker has not been measured. In a smooth area a pixel
changes in the one reading when its red has a certain value modulo 4, and
in the other when its blue does, so where those differ at most one of the
two readings is changed.

The battery now checks this directly: whether a snapshot is the pixels of
`getImageData` with red and blue exchanged, and whether the textured
image's snapshot is explained by the same five bits once red and blue are
exchanged. That check has run against the stand-in noise only.

**WebGL `readPixels` is not noised.** A WebGL canvas cleared to
rgb(100,100,100) read back exact through `readPixels` in 60 readbacks of
60, while `toDataURL` of the same canvas changed one of the four sets
every time. Helium's canvas patch touches the 2D context, the canvas
element and `OffscreenCanvas`, and not the WebGL context. A line for the
console, to compare with the one under "Check it yourself":

```js
(() => { const c = document.createElement('canvas'); c.width = c.height = 64; const gl = c.getContext('webgl', {preserveDrawingBuffer: true}); gl.clearColor(100 / 255, 100 / 255, 100 / 255, 1); gl.clear(gl.COLOR_BUFFER_BIT); const p = new Uint8Array(64 * 64 * 4); gl.readPixels(0, 0, 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, p); let n = 0; for (let i = 0; i < p.length; i += 4) if (p[i] != 100 || p[i + 1] != 100 || p[i + 2] != 100) n++; return n; })()
```

It answered 0 with the noise on. The question that follows is whether
any canvas can be read without noise by going through WebGL. The battery
now asks it: it copies the textured 2D canvas into a WebGL texture and
reads that with `readPixels`, and copies it into a video frame and copies
the frame out. In a Chromium without noise both give every pixel exact,
so the routes themselves are faithful. Neither has yet run against
Helium.

## What it does and does not mean

Established, on Helium: in smooth areas the positions of the noise carry
two bits where the token has 64, the four patterns are public and the
same for everyone, and a page can tell exactly where noise was applied.
In textured areas a page can recover five bits of the token and with them
the sign of each channel's fixed step.

Not established: that this recovers a stable canvas fingerprint from a
real fingerprinting image. In textured areas the rest of each step uses
the whole token, and noise this small can be tolerated by a matcher that
compares images loosely, whatever the hash. The finding is about the hash
doing less than its design reads as intending, and it has a small fix.

## Check it yourself

A line for the browser's console, on any ordinary web page:

```js
(() => { const c = document.createElement('canvas'); c.width = c.height = 64; const k = c.getContext('2d'); k.fillStyle = 'rgb(100,100,100)'; k.fillRect(0, 0, 64, 64); const d = k.getImageData(0, 0, 64, 64).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] != 100 || d[i + 1] != 100 || d[i + 2] != 100) n++; return n; })()
```

With Helium's hash the answer is 1031, 998, 1085 or 982 on every site, in
every profile, on every machine.

`probe.html` shows which of the four sets was changed and predicts other
fills from it. Serve it and open it from two sites:

```bash
python3 -m http.server 8000 --directory freebsd/privacy/noise-hash
```

then `http://localhost:8000/probe.html` and
`http://127.0.0.1:8000/probe.html`.

`analysis.py` recomputes the arithmetic (under a minute):

```bash
python3 freebsd/privacy/noise-hash/analysis.py
```

How far these have been tried: the page was run against a Chromium with
no canvas noise (nothing changes, and it says so), and against the
model's output put in place of the browser's readback, for two tokens
with Helium's hash (set 1 stepping up, set 2 stepping down, every
prediction exact) and one with Beryllium's (none of the four). It has not
been run against a browser with Helium's noise.

## The battery: the same tests on every machine

`battery` runs a browser through a fixed set of tests and writes one
result file per machine; `battery compare` puts the files side by side.
It needs Python 3.8 or later and nothing else, and runs on macOS, Linux
and FreeBSD. Each run uses new, empty profiles in a temporary directory
and a page served from the same machine on several ports. Helium derives
the token from the origin, port included, so each port is another site
with another token. Nothing leaves the machine and your own profile is
not touched.

First, on each machine, show that the battery can tell a weak hash from a
good one there. This switches the browser's own canvas noise off and puts
stand-in noise (`sim.js`, the model in JavaScript) in its place:

```bash
freebsd/privacy/noise-hash/battery selftest
```

Then the measurement:

```bash
freebsd/privacy/noise-hash/battery run --label mac
```

On macOS it looks for `/Applications/Helium.app`; elsewhere, or for
another browser, give `--browser PATH` (a binary, or a `.app`). On a
machine reached over ssh it runs headless as it is. Then, with the result
files copied to one place:

```bash
freebsd/privacy/noise-hash/battery compare noise-battery-mac.json noise-battery-linux1.json
```

For a browser the battery cannot start, or to test a private window or
your everyday profile, `battery serve` prints an address to open by hand.

What each site is asked, and what Helium's hash should answer:

| Test | With two bits choosing the pixels |
|---|---|
| A 64 by 64 fill, read twice | 1031, 998, 1085 or 982 pixels changed, the same twice, exactly one of the four sets (checked again by the Python model) |
| Five other fills | every changed pixel predicted from the two bits |
| Direction of the step | +1 for an odd token, -1 for an even one |
| A rectangle read from (5, 7) | the noise follows canvas coordinates (`source_x`, `source_y` in the code) |
| `toDataURL`, `toBlob`, `convertToBlob` | the pixels of `getImageData` with red and blue exchanged (the same pixels only when the step is on green); the PNG is decoded in the page, because drawing it back would be noised again |
| `OffscreenCanvas` | the same pixels as a canvas element |
| The textured image through `toDataURL` | explained by the same five bits once red and blue are exchanged |
| The textured canvas copied into a WebGL texture, and into a video frame | recorded: exact, or noised |
| WebGL | recorded: whether `readPixels` is noised, and whether `toDataURL` of a WebGL canvas changes one of the four sets |
| A textured image of known pixels | exactly one value of the token's low five bits accounts for the sign of every step, and its two low bits are the fill's |
| An image part flat, part gradient, part textured | every pixel behaves as those five bits predict |
| Across sites in one profile | two sites share their pixels about one time in four |

A control profile runs first with `--disable-features=HeliumNoiseCanvas`:
every readback must then be exact, or the rest means nothing on that
machine.

The textured and mixed images go further than anything measured so far.
They are put on the canvas pixel by pixel, so the page knows the original
of every pixel and can test the arithmetic of the textured path, which
the reports above never touched.

How far the battery has been tried: its arithmetic against the Python
model with node; the whole of it against a Chromium with the stand-in
noise (the self-test above, which CI also runs); and its first version
against Helium 0.21.2.1 on macOS and Fedora, with the results above. The
checks added after those runs (the exchange of red and blue, the WebGL
texture, the video frame) have run against the stand-in only.

## Beryllium's change

`patches/privacy/beryllium-noise-hash-whole-token.patch`: the state goes
through SplitMix64's finalizer before each draw, so every draw depends on
the whole token. Released in 0.20.3.17 and public in this repository.

## Reporting

The owner decided on 11 November 2026 to report this to Helium (plan/18
section 8.3). Helium's rules, read that day in its `CONTRIBUTING.md` and
`AGENTS.md`:

- "Do not use AI to generate issue or PR descriptions. You will get
  banned for spam without review."
- "Please do not use AI for contributing if you don't fully understand
  its output."
- AI agents are told not to write code for the project and not to open
  pull requests in its repositories.

This directory was put together with an AI assistant, and the report must
not be. So:

- The report is the owner's, in the owner's words, about what the owner
  has run and understood: the console line on a stock Helium, on a few
  sites and profiles, is enough to stand on.
- There are now three separate things (the hash, the snapshot's byte
  order, WebGL `readPixels`). Each wants its own reproduction by hand
  before it goes into a report, and each can be reported on its own.
- No patch is offered. Helium can read Beryllium's if it wishes.
- If asked how it was found, the answer is the true one: the test suite of
  a derived browser failed one run in four, and an AI assistant worked
  with the owner on why.
- Helium's blank-issue template says security vulnerabilities go through
  "an appropriate channel" and does not name it. Find that channel before
  filing. The finding is already public in this repository.
