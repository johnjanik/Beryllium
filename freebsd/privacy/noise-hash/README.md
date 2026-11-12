# Helium's canvas noise: its hash, and the ways around it

Collected on 11 November 2026 for the owner's report to Helium. This is
the evidence, with a way to check each part. It is not the report: see
"Reporting" at the end.

Measured on Helium itself that day, release 0.21.2.1 on macOS and on
Fedora, in two runs on each: all 120 readbacks changed exactly one of the
four sets below, the same sets on both machines.

The same runs found something that matters more than the hash. The noise
is applied at four calls only, and a page can read a canvas without going
through any of them: copied into a WebGL texture or into a video frame,
the canvas came back with every pixel exact, 60 times of 60. That and a
second inconsistency are under "What else the battery found".

Beryllium 0.20.3.17 was measured the same evening on FreeBSD. Its change
to the hash holds: 30 readbacks, 30 different sets of pixels, none of the
four. The ways around the noise are open on it exactly as on Helium.

Beryllium build 0.20.3.18 was measured on 12 November 2026. It has two
patches more: a snapshot carried the noise of `getImageData` in 30
readbacks of 30, and so did a canvas read whole through a WebGL texture.
A video frame, and a read of one pixel at a time, still gave exact pixels
in 30 of 30. The numbers are under "Beryllium's changes".

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

A second run on each machine that evening, with the battery extended
(next section), gave the same answers to every question above, 30 of 30
on each, with 18 and 16 pairs of 75 sharing their pixels. Over the four
runs: 120 readbacks, every one of them one of the four sets, and 67 pairs
of sites of 300 with the same pixels.

## Measured on Beryllium

The owner ran the same battery against Beryllium 0.20.3.17 (Chromium
156.0.8078.79) on FreeBSD 16.0-CURRENT, amd64, that evening: one control
profile and five new profiles of six sites, thirty readbacks. Beryllium
carries Helium 0.20.3's canvas code with one change, to the hash.

| | Helium 0.21.2.1, macOS and Fedora | Beryllium 0.20.3.17, FreeBSD |
|---|---|---|
| Control, noise off: every readback exact | 6 of 6 on each | 6 of 6 |
| Readbacks with noise | 30 of 30 on each | 30 of 30 |
| Changed pixels are one of the four sets | 30 of 30 on each | 0 of 30 |
| Different sets of changed pixels among the readbacks | 4 | 30 |
| Counts of changed pixels | 982, 998, 1031, 1085 | 945 to 1065, mean 1015 |
| Textured image: some value of five low bits explains every step | 30 of 30 on each | 0 of 30 |
| Pairs of sites in one profile with the same pixels | 18 and 16 of 75 | 0 of 75 |
| The same canvas read twice gives the same pixels | 30 of 30 on each | 30 of 30 |
| Snapshots are `getImageData` with red and blue exchanged | 30 of 30 on each | 30 of 30 |
| WebGL `readPixels` is noised | 0 of 30 on each | 0 of 30 |
| Canvas copied into a WebGL texture: every pixel exact | 30 of 30 on each | 30 of 30 |
| Canvas copied into a video frame: every pixel exact | 30 of 30 on each | 30 of 30 |

- **The change to the hash does what it was written for,** by a test that
  was not written for it. Thirty readbacks gave thirty different sets of
  pixels. Their counts spread as independent choices with chance one in
  four would (mean 1015 and standard deviation 27, against 1024 and 28).
  For the textured image no value of five bits comes near: the closest
  gets about half of some 4,600 signs wrong, which is what guessing gets.
- **Everything under "What else the battery found" is in Beryllium too.**
  A canvas reads back exact through a WebGL texture and through a video
  frame, `readPixels` of a WebGL canvas carries no noise, and a snapshot
  is noised with red and blue exchanged. Two patches for build 0.20.3.18
  answer the snapshot and the WebGL read ("Beryllium's changes" below);
  0.20.3.17, measured here, has neither.

### Build 0.20.3.18, 12 November 2026

The owner ran the battery on build 0.20.3.18, the first with those two
patches, on the same machine: one control profile and five new profiles
of six sites, thirty readbacks. The build is not published as a release
yet.

The hash, in a second build:

| | Beryllium 0.20.3.17 | Beryllium 0.20.3.18 |
|---|---|---|
| Control, noise off: every readback exact | 6 of 6 | 6 of 6 |
| Readbacks with noise | 30 of 30 | 30 of 30 |
| Changed pixels are one of the four sets | 0 of 30 | 0 of 30 |
| Different sets of changed pixels among the readbacks | 30 | 30 |
| Counts of changed pixels | 945 to 1065, mean 1015 | 952 to 1071, mean 1027 |
| Textured image: some value of five low bits explains every step | 0 of 30 | 0 of 30 |
| Pairs of sites in one profile with the same pixels | 0 of 75 | 0 of 75 |
| The same canvas read twice gives the same pixels | 30 of 30 | 30 of 30 |

The counts again spread as independent choices with chance one in four
would (standard deviation 30, against 28). What the two patches changed
is in the table under "Beryllium's changes": every row came out as the
rehearsal had it.

## What was not measured

- Canvases with floating-point pixels, and canvases drawn by the GPU
  (the battery asks for a canvas that is read often, which is drawn in
  memory).
- A real fingerprinting script, and whether the hash alone recovers a
  stable fingerprint from one.
- Other ways out of a canvas: `captureStream`, `createImageBitmap`,
  WebGPU, and in WebGL 2 a read into a buffer. Two routes were tried and
  both were open; these were not tried.

## What else the battery found

None of this is about the hash, and Beryllium's change to the hash
touches none of it: the same measurements on Beryllium are in the section
above.

### The noise is applied at four calls, and a canvas can be read around them

Helium's canvas patch calls its noise in four places:

| File | Function |
|---|---|
| `canvas2d/base_rendering_context_2d.cc` | `getImageData` |
| `html/canvas/html_canvas_element.cc` | `ToDataURLInternal` (`toDataURL`) |
| `html/canvas/html_canvas_element.cc` | `toBlob` |
| `offscreencanvas/offscreen_canvas.cc` | `convertToBlob` |

Nothing else that hands out a canvas's pixels is touched. The second run
tried two other routes on the textured canvas of known pixels, with the
noise on:

| | macOS, arm64 | Fedora, x86_64 |
|---|---|---|
| Copied into a WebGL texture and read with `readPixels`: every pixel exact | 30 of 30 | 30 of 30 |
| Copied into a video frame and copied out (`VideoFrame.copyTo`): every pixel exact | 30 of 30 | 30 of 30 |
| The same two routes with the noise switched off: exact | 6 of 6 each | 6 of 6 each |
| `getImageData` of that canvas in the same readbacks: about 2,200 of 2,304 pixels changed | 30 of 30 | 30 of 30 |
| WebGL `readPixels` of a canvas WebGL drew itself: noised | 0 of 30 | 0 of 30 |
| `toDataURL` of that WebGL canvas: one of the four sets | 30 of 30 | 30 of 30 |

So a page that wants a canvas's true pixels has them: draw on a 2D
canvas, hand it to WebGL as a texture, read the texture. The noise only
reaches a script that reads through one of the four calls. The canvas
fingerprinting scripts in common use read through `toDataURL` or
`getImageData` and do get noise; changing that takes a few lines. No
tracker is known to this project to do it.

A line for the console, on any ordinary page. It fills a 2D canvas and
counts the pixels that come back changed, first through `getImageData`
and then through a WebGL texture:

```js
(() => { const c = document.createElement('canvas'); c.width = c.height = 64; const k = c.getContext('2d'); k.fillStyle = 'rgb(100,100,100)'; k.fillRect(0, 0, 64, 64); const count = d => { let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] != 100 || d[i + 1] != 100 || d[i + 2] != 100) n++; return n; }; const g = document.createElement('canvas').getContext('webgl'); g.bindTexture(g.TEXTURE_2D, g.createTexture()); g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, g.RGBA, g.UNSIGNED_BYTE, c); g.bindFramebuffer(g.FRAMEBUFFER, g.createFramebuffer()); g.framebufferTexture2D(g.FRAMEBUFFER, g.COLOR_ATTACHMENT0, g.TEXTURE_2D, g.getParameter(g.TEXTURE_BINDING_2D), 0); const p = new Uint8Array(64 * 64 * 4); g.readPixels(0, 0, 64, 64, g.RGBA, g.UNSIGNED_BYTE, p); return [count(k.getImageData(0, 0, 64, 64).data), count(p)]; })()
```

In a browser without canvas noise it answers `[0, 0]`. From the battery's
results Helium should answer about a thousand and then 0. The line itself
has been run in a Chromium without noise and with the stand-in noise
(`[982, 0]`), not yet by hand in Helium.

### A snapshot is noised with red and blue exchanged

`toDataURL`, `toBlob` and `convertToBlob` gave the pixels of
`getImageData` in 42 readbacks of 120, and those are exactly the
readbacks whose step fell on green. The second run asked the question
directly:

| | macOS, arm64 | Fedora, x86_64 |
|---|---|---|
| `toDataURL`, `toBlob`, `convertToBlob` of the grey fill are the pixels of `getImageData` with red and blue exchanged | 30 of 30 | 30 of 30 |
| `toDataURL` of the textured image equals its `getImageData` | 0 of 30 | 0 of 30 |
| and is explained by the same five bits once red and blue are exchanged | 30 of 30 | 30 of 30 |

The source says why. `canvas_noising_helper.cc` reads a snapshot back in
the snapshot's own pixel format where that is one of

```cpp
    case kRGBA_8888_SkColorType:
    case kBGRA_8888_SkColorType:
```

and runs the same four-bytes-a-pixel arithmetic over it. `ImageData` is
always red, green, blue, alpha; a snapshot on these machines is blue,
green, red, alpha. So for a snapshot the low byte that the hash sees is
blue, and channel 0 is blue. A grey fill hashes the same either way,
which is why its pixels and direction agree and only the channel moves;
any other content gets different noise altogether.

A site therefore holds two differently noised copies of one canvas for
the asking. In a smooth area a pixel changes in the one reading when its
red has a certain value modulo 4 and in the other when its blue does, so
where those differ at most one of the two readings is changed. What that
is worth to a tracker was not measured, and beside the section above it
matters little.

## What it does and does not mean

Established, on Helium: in smooth areas the positions of the noise carry
two bits where the token has 64, the four patterns are public and the
same for everyone, and a page can tell exactly where noise was applied.
In textured areas a page can recover five bits of the token and with them
the sign of each channel's fixed step.

Not established: that the hash alone recovers a stable canvas fingerprint
from a real fingerprinting image. In textured areas the rest of each step
uses the whole token, and noise this small can be tolerated by a matcher
that compares images loosely, whatever the hash. The finding about the
hash is that it does less than its design reads as intending, and it has
a small fix.

The order of importance is the other way round from the order of
discovery. The hash decides how good the noise is where it is applied.
The four calls decide whether it is applied, and a page chooses the
call.

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
| The textured canvas copied into a WebGL texture, and into a video frame | recorded: exact, or noised, and whether the noise is `getImageData`'s |
| WebGL reads of flat colour: one pixel, and 3 by 3 | recorded: exact or not. A page that picks objects by colour needs them exact |
| The textured canvas through WebGL one pixel at a time | recorded: exact or not |
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
noise (the self-test above, which CI also runs); and against Helium
0.21.2.1 on macOS and Fedora, twice, with the results above. On Fedora
the first runs printed a traceback: Helium dropped a connection while the
battery was refusing a file it does not serve. The runs were unaffected;
the battery no longer prints it, and it now records what else a browser
asks it for.

## Beryllium's changes

Three patches, public in this repository.

`patches/privacy/beryllium-noise-hash-whole-token.patch`: the state goes
through SplitMix64's finalizer before each draw, so every draw depends on
the whole token. Released in 0.20.3.17 and measured above.

`patches/privacy/beryllium-noise-snapshot-channel-order.patch`, written
11 November 2026 for 0.20.3.18: a blue, green, red snapshot is read back
as red, green, blue before it is noised, so `toDataURL`, `toBlob` and
`convertToBlob` carry the noise `getImageData` carries. Eight lines.
Built in 0.20.3.18 and measured on 12 November 2026.

`patches/privacy/beryllium-noise-webgl-readpixels.patch`, written the
same day for 0.20.3.18: `readPixels` into an array, in the format every
WebGL context offers (four bytes a pixel), gets the site's canvas noise,
anchored to the framebuffer. That covers a WebGL scene read back, and a
2D canvas read through a texture, which then carries exactly the noise
`getImageData` gives it. Built in 0.20.3.18 and measured on 12 November
2026. Before that build its new function had been compiled outside the
tree against Chromium's own headers, where it agreed with `model.py` on
240 cases.

It leaves one kind of pixel alone: one whose whole 3 by 3 neighbourhood
in the read is one exact colour. WebGL pages read flat colour back for
exact values (the colour under the pointer names the object drawn
there), and Helium's noise changes one such pixel in four. Tor Browser's
protection of `readPixels` broke pages that way. A flat area tells a
page nothing one pixel of it would not.

What that patch leaves open, and the battery keeps showing:

- a read of one pixel at a time, which is exact for the reason above and
  costs a page one call a pixel;
- reads in other formats (floating point, integer);
- WebGL 2 `readPixels` into a buffer object;
- video frames, `captureStream`, `createImageBitmap`.

So from 0.20.3.18 the scripts that hash a WebGL scene with `readPixels`,
or a canvas with `toDataURL`, get noise, and one noise. A page written to
get round Beryllium's noise still can. Feature matrix row P-FPR-07 stays
open for that.

What the battery was expected to show on 0.20.3.18, from a rehearsal
against the stand-in noise (`battery run --simulate fixed`) written before
the build, and what it showed on the build (12 November 2026, thirty
readbacks):

| Row | 0.20.3.17, measured | 0.20.3.18, expected | 0.20.3.18, measured |
|---|---|---|---|
| `toDataURL`, `toBlob`, `convertToBlob` give the pixels of `getImageData` | 10 of 30 | 30 of 30 | 30 of 30 |
| Textured image through `toDataURL` gives the pixels of `getImageData` | 0 of 30 | 30 of 30 | 30 of 30 |
| A canvas copied into a WebGL texture reads back exact | 30 of 30 | 0 of 30 | 0 of 30 |
| or reads back with the noise of `getImageData` | 0 of 30 | 30 of 30 | 30 of 30 |
| WebGL: single pixels and 3 by 3 blocks of a flat colour read back exact | not asked | 30 of 30 | 30 of 30 |
| WebGL: read one pixel at a time, a canvas comes back exact | not asked | 30 of 30 (the open route) | 30 of 30 |
| A canvas copied into a video frame reads back exact | 30 of 30 | 30 of 30 (still open) | 30 of 30 |

Read as results:

- **One noise for a canvas.** A snapshot now carries the pixels of
  `getImageData`, in all thirty readbacks and for the grey fill, the
  textured image and the mixed one. Red and blue are no longer exchanged:
  the two readings agree whichever channel the step is on (in seven of
  the thirty it was on green, where an exchange would not show).
- **The texture route is closed for the usual read.** A canvas copied
  into a WebGL texture and read back whole comes back with exactly the
  noise `getImageData` gives that canvas, so a page gains nothing by
  taking that route.
- **Flat colour reads back exact, and only flat colour.** The four reads
  of one pixel and the four of 3 by 3 pixels inside a flat square were
  exact every time, so a page that picks objects by colour is not
  disturbed. A whole read of the four squares changed 112 to 122 of its
  1,024 pixels. `model.py`, run on that scene afterwards with 400 tokens,
  changes 111 to 123, all among the 124 pixels on the borders between the
  squares; the battery records the count for the build, not which pixels.
- **What was left open is open.** Read one pixel at a time, the textured
  canvas came back exact in thirty of thirty. Through a video frame it
  came back exact in thirty of thirty. Both were written down as open
  before the build.

The two patch files still say "not built" in their headers. They stay as
they are until 0.20.3.18 is published or dropped: a package's manifest
carries the SHA-256 of every patch, and `publish-release` refuses a
package whose patches differ from the checkout.

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
- There are three separate things: that a canvas can be read around the
  noise (WebGL texture, video frame, and `readPixels` of a WebGL canvas),
  the snapshot's byte order, and the hash. Each wants its own
  reproduction by hand before it goes into a report, and each can be
  reported on its own. The first is the one that matters most.
- No patch is offered. Helium can read Beryllium's if it wishes.
- If asked how it was found, the answer is the true one: the test suite of
  a derived browser failed one run in four, and an AI assistant worked
  with the owner on why.
- Helium's blank-issue template says security vulnerabilities go through
  "an appropriate channel" and does not name it. Find that channel before
  filing. The finding is already public in this repository.
