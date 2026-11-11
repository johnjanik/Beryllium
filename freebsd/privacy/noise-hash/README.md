# Helium's canvas noise: two bits of the token choose the pixels

Collected on 11 November 2026 for the owner's report to Helium. This is
the evidence, with a way to check each part. It is not the report: see
"Reporting" at the end.

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

## What was not measured

- **Stock Helium.** Nobody on this project has run this against a build
  from Helium. Helium's official Linux builds 0.20.3.1 and 0.21.2.1 were
  downloaded in a cloud session on 11 November 2026 and that session's
  safety rules refused to execute them, so they were not run. The
  measurements above are from Beryllium builds that compile the same two
  files. Run `probe.html` on a stock Helium before reporting anything.
- Textured areas, canvases with floating-point pixels, `toDataURL`,
  `toBlob` and WebGL readback. They go through the same helper; they were
  not looked at separately.
- A real fingerprinting script.

## What it does and does not mean

Established: in smooth areas the positions of the noise carry two bits
where the token has 64, the four patterns are public and the same for
everyone, and a page can tell exactly where noise was applied. Part 2 of
`probe.html` does that: it reads one fill, then says in advance which
pixels of five other fills will come back changed.

Not established: that this recovers a stable canvas fingerprint from a
real fingerprinting image. Edges and text take the textured path, which
uses more of the token, and noise this small can be tolerated by a
matcher that compares images loosely, whatever the hash. The finding is
about the hash doing less than its design reads as intending, and it has
a small fix.

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
| `toDataURL`, `toBlob`, `OffscreenCanvas` | the same pixels as `getImageData`; the PNG is decoded in the page, because drawing it back would be noised again |
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
model with node, and the whole of it against a Chromium with the stand-in
noise (the self-test above, which CI also runs). Against a browser with
Helium's own noise it has not been run. Its first run on macOS is the
owner's.

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
- No patch is offered. Helium can read Beryllium's if it wishes.
- If asked how it was found, the answer is the true one: the test suite of
  a derived browser failed one run in four, and an AI assistant worked
  with the owner on why.
- Helium's blank-issue template says security vulnerabilities go through
  "an appropriate channel" and does not name it. Find that channel before
  filing. The finding is already public in this repository.
