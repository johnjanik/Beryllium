// SPDX-License-Identifier: GPL-3.0-only
//
// A stand-in for Helium's canvas noise, for the battery's self-test only.
//
// The self-test starts a browser with its own canvas noise off, loads this
// file, and lets it noise every readback the way model.py says Helium
// does (or the way Beryllium's changed hash does). The battery must then
// report the weakness for the first and its absence for the second. That
// shows the battery can tell the two apart on this machine. It shows
// nothing about any browser: results made with this file are marked
// "simulated" and are never counted as measurements.
//
// heliumNoise() is model.py's noise_pixels() in JavaScript; the tests hold
// the two together.
'use strict';

(function () {
  const MASK = (1n << 64n) - 1n;
  const PRIME = 0x00000100000001b3n;

  function mix(v) {
    v ^= v >> 30n; v = v * 0xbf58476d1ce4e5b9n & MASK;
    v ^= v >> 27n; v = v * 0x94d049bb133111ebn & MASK;
    v ^= v >> 31n; return v;
  }

  class Hash {
    constructor(state, finalize) { this.state = state & MASK; this.remaining = 0; this.finalize = finalize; }
    copy() { const h = new Hash(this.state, this.finalize); h.remaining = this.remaining; return h; }
    update(value) { this.state = ((this.state ^ (value & MASK)) * PRIME) & MASK; this.remaining = 64; }
    below(max) {
      if (max <= 0) return 0;
      const required = max.toString(2).length;   // std::bit_width
      if (this.remaining < required) throw new Error('hash bits used up');
      const state = this.finalize ? mix(this.state) : this.state;
      const value = Number((state >> BigInt(64 - this.remaining)) % BigInt(max));
      this.remaining -= required;
      return value;
    }
  }

  const signed = (h, reach) => reach <= 0 ? 0 : h.below(reach * 2 + 1) - reach;
  const nonzero = h => h.below(2) === 0 ? -1 : 1;

  // src: RGBA bytes of a width x height rectangle that starts at (ox, oy)
  // on the canvas. Returns the noised bytes.
  function heliumNoise(token, src, width, height, ox, oy, finalize) {
    const tokenHash = new Hash(token, !!finalize);
    const out = new Uint8ClampedArray(src);
    const value = i => BigInt(src[i]) | BigInt(src[i + 1]) << 8n | BigInt(src[i + 2]) << 16n |
                       BigInt(src[i + 3]) << 24n;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = 4 * (x + y * width);
        if (!src[i] && !src[i + 1] && !src[i + 2] && !src[i + 3]) continue;
        const content = tokenHash.copy();
        content.update(value(i));
        const low = [255, 255, 255], high = [0, 0, 0];
        for (let dy = -1; dy <= 1; dy++) {
          const sy = Math.min(Math.max(y + dy, 0), height - 1);
          for (let dx = -1; dx <= 1; dx++) {
            const sx = Math.min(Math.max(x + dx, 0), width - 1);
            const j = 4 * (sx + sy * width);
            content.update(value(j));
            for (let c = 0; c < 3; c++) {
              if (src[j + c] < low[c]) low[c] = src[j + c];
              if (src[j + c] > high[c]) high[c] = src[j + c];
            }
          }
        }
        const smooth = [0, 1, 2].every(c => high[c] - low[c] <= 2);
        const coordinate = tokenHash.copy();
        coordinate.update(mix(BigInt((y + oy) >>> 0) << 32n | BigInt((x + ox) >>> 0)));
        coordinate.update(value(i));
        let rgb = [0, 0, 0];
        if (smooth) {
          if (coordinate.below(4) === 0) {
            const step = nonzero(content);       // the right side first (C++17)
            rgb[content.below(3)] = step;
          }
        } else {
          rgb = [0, 1, 2].map(() => nonzero(content) + signed(coordinate, 1));
        }
        for (let c = 0; c < 4; c++) {
          const channel = src[i + c];
          const alpha = c === 3;
          if (alpha && (channel === 0 || channel === 255)) continue;
          const reach = alpha ? 1 : 2;
          const lowest = Math.max(alpha && channel > 0 ? 1 : 0, channel - reach);
          const highest = Math.min(255, channel + reach);
          const step = alpha ? signed(coordinate, 1) : rgb[c];
          out[i + c] = Math.min(Math.max(channel + step, lowest), highest);
        }
      }
    }
    return out;
  }

  // A token for this origin from a seed, as Helium derives one per origin.
  function tokenFor(seed, origin) {
    let h = BigInt.asUintN(64, BigInt(seed)) ^ 0xcbf29ce484222325n;
    for (const ch of origin) h = ((h ^ BigInt(ch.codePointAt(0))) * PRIME) & MASK;
    return mix(h);
  }

  // Put the stand-in noise on every 2D readback of this page.
  function install(seed, finalize) {
    const token = tokenFor(seed, location.origin);
    const noised = (image, sx, sy) => {
      image.data.set(heliumNoise(token, image.data, image.width, image.height, sx, sy, finalize));
      return image;
    };
    const contexts = [CanvasRenderingContext2D];
    if (typeof OffscreenCanvasRenderingContext2D !== 'undefined') contexts.push(OffscreenCanvasRenderingContext2D);
    const realGet = new Map();
    for (const type of contexts) {
      const real = type.prototype.getImageData;
      realGet.set(type, real);
      type.prototype.getImageData = function (sx, sy, sw, sh, settings) {
        return noised(real.call(this, sx, sy, sw, sh, settings), sx, sy);
      };
    }
    // A noised copy of a 2D canvas, to encode in place of the canvas.
    const copyOf = (canvas, make) => {
      const context = canvas.getContext('2d');
      if (!context) return null;                 // WebGL: not simulated
      const real = realGet.get(Object.getPrototypeOf(context).constructor) ||
                   realGet.get(CanvasRenderingContext2D);
      const image = noised(real.call(context, 0, 0, canvas.width, canvas.height), 0, 0);
      const copy = make(canvas.width, canvas.height);
      copy.getContext('2d').putImageData(image, 0, 0);
      return copy;
    };
    const element = (w, h) => Object.assign(document.createElement('canvas'), {width: w, height: h});
    const realUrl = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function (...args) {
      return realUrl.apply(copyOf(this, element) || this, args);
    };
    const realBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function (...args) {
      return realBlob.apply(copyOf(this, element) || this, args);
    };
    if (typeof OffscreenCanvas !== 'undefined') {
      const realConvert = OffscreenCanvas.prototype.convertToBlob;
      OffscreenCanvas.prototype.convertToBlob = function (...args) {
        return realConvert.apply(copyOf(this, (w, h) => new OffscreenCanvas(w, h)) || this, args);
      };
    }
    return token;
  }

  const NoiseSim = {heliumNoise, tokenFor, install};
  if (typeof module !== 'undefined') module.exports = NoiseSim;
  else globalThis.NoiseSim = NoiseSim;
})();
