// SPDX-License-Identifier: GPL-3.0-only
//
// The arithmetic of the noise battery (battery.html, battery): what
// Helium's canvas noise must do to a pixel if its hash hands out the low
// bits of an FNV-1a state, worked out from a few low bits of the site's
// token. Nothing here touches a canvas, so node can run it against the
// Python model (freebsd/tools/tests/test_noise_battery.py).
//
// From Helium's source (README.md has the excerpts):
//   coordinate hash = token, Update(mix(y << 32 | x)), Update(pixel)
//   content hash    = token, Update(pixel), Update(each of the 3 x 3
//                     neighbourhood, clamped at the edges, row by row)
//   smooth area:   changes if the coordinate hash's low two bits are 0;
//                  the direction is the content hash's bit 0
//   textured area: each of red, green, blue moves by (+1 or -1, from the
//                  content hash's bits 0, 2 and 4) plus (-1, 0 or +1, from
//                  the whole coordinate hash)
// A pixel is hashed as its four bytes little endian, so its low byte is
// red. The low k bits of an FNV-1a step depend only on the low k bits
// going in.
'use strict';

const MASK64 = (1n << 64n) - 1n;

// MixCanvasCoordinateSeed: SplitMix64's finalizer.
function mix64(v) {
  v ^= v >> 30n; v = v * 0xbf58476d1ce4e5b9n & MASK64;
  v ^= v >> 27n; v = v * 0x94d049bb133111ebn & MASK64;
  v ^= v >> 31n; return v;
}

const mixCache = new Map();
// The low bits (mask up to 255) of the mixed coordinates of (x, y).
function mixLow(x, y, mask) {
  const key = y * 65536 + x;
  let low = mixCache.get(key);
  if (low === undefined) {
    low = Number(mix64(BigInt(y) << 32n | BigInt(x)) & 0xffn);
    mixCache.set(key, low);
  }
  return low & mask;
}

const FNV_LOW = 0xb3;  // the low byte of the FNV prime 0x100000001b3

// One FNV-1a step on the low bits selected by mask (up to 255).
function step(state, value, mask) {
  return ((state ^ (value & mask)) * (FNV_LOW & mask)) & mask;
}

// Index of the red byte of (x, y) in an RGBA array, clamped to the image.
function at(width, height, x, y) {
  const cx = Math.min(Math.max(x, 0), width - 1);
  const cy = Math.min(Math.max(y, 0), height - 1);
  return 4 * (cx + cy * width);
}

// kSmoothNeighborhoodRgbRange: every RGB channel within 2 over the 3 x 3.
function isSmooth(img, width, height, x, y) {
  for (let c = 0; c < 3; c++) {
    let low = 255, high = 0;
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const v = img[at(width, height, x + dx, y + dy) + c];
        if (v < low) low = v;
        if (v > high) high = v;
      }
    }
    if (high - low > 2) return false;
  }
  return true;
}

// The low bits of the content hash of (x, y), from the low bits of the token.
function contentLow(tokenLow, img, width, height, x, y, mask) {
  let state = step(tokenLow & mask, img[at(width, height, x, y)], mask);
  for (let dy = -1; dy <= 1; dy++) {
    for (let dx = -1; dx <= 1; dx++) {
      state = step(state, img[at(width, height, x + dx, y + dy)], mask);
    }
  }
  return state;
}

// Does a pixel in a smooth area change? low2: the token's low two bits.
// (ox, oy): where the read rectangle starts on the canvas.
function smoothChanges(low2, x, y, red, ox, oy) {
  return step(step(low2 & 3, mixLow(x + ox, y + oy, 3), 3), red, 3) === 0;
}

// +1 or -1: the step of a smooth pixel that changes.
function direction(low1, img, width, height, x, y) {
  return contentLow(low1, img, width, height, x, y, 1) & 1 ? 1 : -1;
}

// [+1 or -1] for red, green and blue in a textured area, from five bits.
function texturedSigns(low5, img, width, height, x, y) {
  const c = contentLow(low5, img, width, height, x, y, 31);
  return [c & 1 ? 1 : -1, c & 4 ? 1 : -1, c & 16 ? 1 : -1];
}

// The pixels of a width x height fill with this red value that change,
// as "x,y" strings in reading order.
function flatSet(low2, width, height, red, ox, oy) {
  const set = [];
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (smoothChanges(low2, x, y, red, ox || 0, oy || 0)) set.push(x + ',' + y);
    }
  }
  return set;
}

// The pixels that differ between two RGBA arrays, as "x,y" strings, and
// the different steps seen, as "dr dg db da".
function changedPixels(before, after, width) {
  const keys = [], steps = new Set();
  for (let i = 0; i < before.length; i += 4) {
    const d = [after[i] - before[i], after[i + 1] - before[i + 1],
               after[i + 2] - before[i + 2], after[i + 3] - before[i + 3]];
    if (d[0] || d[1] || d[2] || d[3]) {
      keys.push(((i / 4) % width) + ',' + Math.floor(i / 4 / width));
      steps.add(d.join(' '));
    }
  }
  return {keys, steps: [...steps].sort()};
}

function sameList(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// Which of the four sets a changed-pixel list is: 0 to 3, or null.
function whichSet(keys, width, height, red, ox, oy) {
  for (let low2 = 0; low2 < 4; low2++) {
    if (sameList(keys, flatSet(low2, width, height, red, ox, oy))) return low2;
  }
  return null;
}

// Hold a readback (out) of a known image (img) against what five low bits
// of the token would make of it. Counts, not a verdict:
//   smooth, smoothWrong      smooth pixels, and those that did not behave
//                            as predicted (changed or not, and the step)
//   textured, constraints,   textured pixels, channels that moved (each
//   texturedWrong            gives away its +1 or -1), and those whose
//                            sign was not the predicted one
//   tooFar, alphaChanged     channels more than two levels off; alpha moved
function check(low5, img, out, width, height, ox, oy) {
  const r = {smooth: 0, smoothWrong: 0, textured: 0, constraints: 0, texturedWrong: 0,
             tooFar: 0, alphaChanged: 0, changed: 0};
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = 4 * (x + y * width);
      const d = [out[i] - img[i], out[i + 1] - img[i + 1], out[i + 2] - img[i + 2]];
      if (out[i + 3] !== img[i + 3]) r.alphaChanged++;
      if (d[0] || d[1] || d[2] || out[i + 3] !== img[i + 3]) r.changed++;
      if (isSmooth(img, width, height, x, y)) {
        r.smooth++;
        const moved = d.filter(v => v !== 0);
        let ok;
        if (smoothChanges(low5 & 3, x, y, img[i], ox || 0, oy || 0)) {
          ok = moved.length === 1 && moved[0] === direction(low5 & 1, img, width, height, x, y);
        } else {
          ok = moved.length === 0;
        }
        if (!ok) r.smoothWrong++;
      } else {
        r.textured++;
        const signs = texturedSigns(low5, img, width, height, x, y);
        for (let c = 0; c < 3; c++) {
          if (Math.abs(d[c]) > 2) r.tooFar++;
          if (d[c] !== 0) {
            r.constraints++;
            if (Math.sign(d[c]) !== signs[c]) r.texturedWrong++;
          }
        }
      }
    }
  }
  return r;
}

// Try all 32 values of the token's low five bits against a readback.
// fits: the values under which every pixel behaved as predicted.
// best: the counts for the value with the fewest pixels out of line.
function findLow5(img, out, width, height, ox, oy) {
  const fits = [];
  let best = null;
  for (let low5 = 0; low5 < 32; low5++) {
    const r = check(low5, img, out, width, height, ox, oy);
    const wrong = r.smoothWrong + r.texturedWrong;
    if (wrong === 0) fits.push(low5);
    if (best === null || wrong < best.wrong) best = Object.assign({low5, wrong}, r);
  }
  return {fits, best};
}

// xorshift32: the same test images on every machine.
function generator(seed) {
  let s = (seed >>> 0) || 1;
  return () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5; s >>>= 0;
    return s;
  };
}

// Every pixel different from its neighbours: all textured. Channels stay
// within 2..253 so that no step is clamped away at 0 or 255.
function randomImage(width, height, seed) {
  const next = generator(seed);
  const img = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < img.length; i += 4) {
    img[i] = 2 + next() % 252; img[i + 1] = 2 + next() % 252;
    img[i + 2] = 2 + next() % 252; img[i + 3] = 255;
  }
  return img;
}

// A third flat blocks, a third slow gradients, a third random: smooth and
// textured pixels side by side.
function mixedImage(width, height, seed) {
  const next = generator(seed);
  const img = new Uint8ClampedArray(width * height * 4);
  const third = Math.floor(width / 3);
  const blocks = new Map();
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = 4 * (x + y * width);
      let rgb;
      if (x < third) {
        const key = Math.floor(x / 8) + ',' + Math.floor(y / 8);
        if (!blocks.has(key)) blocks.set(key, [2 + next() % 252, 2 + next() % 252, 2 + next() % 252]);
        rgb = blocks.get(key);
      } else if (x < 2 * third) {
        rgb = [40 + Math.floor(x / 3), 90 + Math.floor(y / 4), 200 - Math.floor((x + y) / 5)];
      } else {
        rgb = [2 + next() % 252, 2 + next() % 252, 2 + next() % 252];
      }
      img[i] = rgb[0]; img[i + 1] = rgb[1]; img[i + 2] = rgb[2]; img[i + 3] = 255;
    }
  }
  return img;
}

// A PNG as a canvas writes it (8 bits a channel, RGB or RGBA, not
// interlaced) to {width, height, data: RGBA}. A readback through an image
// element would be noised a second time; this is not.
async function decodePng(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getUint32(0) !== 0x89504e47) throw new Error('not a PNG');
  let width = 0, height = 0, channels = 0;
  const parts = [];
  for (let p = 8; p < bytes.length;) {
    const length = view.getUint32(p);
    const type = String.fromCharCode(bytes[p + 4], bytes[p + 5], bytes[p + 6], bytes[p + 7]);
    if (type === 'IHDR') {
      width = view.getUint32(p + 8); height = view.getUint32(p + 12);
      const depth = bytes[p + 16], colour = bytes[p + 17], interlace = bytes[p + 20];
      if (depth !== 8 || (colour !== 2 && colour !== 6) || interlace !== 0) {
        throw new Error(`PNG of depth ${depth}, colour type ${colour}, interlace ${interlace}`);
      }
      channels = colour === 6 ? 4 : 3;
    } else if (type === 'IDAT') {
      parts.push(bytes.subarray(p + 8, p + 8 + length));
    }
    p += 12 + length;
  }
  const stream = new Blob(parts).stream().pipeThrough(new DecompressionStream('deflate'));
  const raw = new Uint8Array(await new Response(stream).arrayBuffer());
  const stride = width * channels;
  const data = new Uint8ClampedArray(width * height * 4);
  let previous = new Uint8Array(stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const line = raw.slice(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let i = 0; i < stride; i++) {
      const left = i >= channels ? line[i - channels] : 0;
      const up = previous[i];
      const corner = i >= channels ? previous[i - channels] : 0;
      let add = 0;
      if (filter === 1) add = left;
      else if (filter === 2) add = up;
      else if (filter === 3) add = (left + up) >> 1;
      else if (filter === 4) {
        const p0 = left + up - corner;
        const pa = Math.abs(p0 - left), pb = Math.abs(p0 - up), pc = Math.abs(p0 - corner);
        add = pa <= pb && pa <= pc ? left : pb <= pc ? up : corner;
      } else if (filter !== 0) throw new Error('PNG filter ' + filter);
      line[i] = (line[i] + add) & 255;
    }
    for (let x = 0; x < width; x++) {
      const o = 4 * (x + y * width);
      data[o] = line[x * channels]; data[o + 1] = line[x * channels + 1];
      data[o + 2] = line[x * channels + 2];
      data[o + 3] = channels === 4 ? line[x * channels + 3] : 255;
    }
    previous = line;
  }
  return {width, height, data};
}

const NoiseBattery = {mix64, mixLow, step, at, isSmooth, contentLow, smoothChanges, direction,
                      texturedSigns, flatSet, changedPixels, sameList, whichSet, check, findLow5,
                      generator, randomImage, mixedImage, decodePng};
if (typeof module !== 'undefined') module.exports = NoiseBattery;
