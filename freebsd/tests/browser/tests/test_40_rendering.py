# SPDX-License-Identifier: GPL-3.0-only
"""Graphics: WebGL, WebGPU and canvas work, and what the GPU process reports.

Helium's canvas noise (helium/patches/helium/core/noise/canvas.patch, the
feature HeliumNoiseCanvas, on by default) changes one RGB channel of about
one in four pixels of a flat area by one level on every readback, chosen by
a per-session, per-site token: that is what the suite saw as "a colour off
by one" from 0.20.3.8 to 0.20.3.13 (plan/14). It is a privacy feature
(test_60_privacy checks it), so this group turns it off to test the
rasterizer itself."""

import json
import re

from berytest.base import BrowserTest
from berytest.browser import Browser

PROBE = """(async () => {
  const out = {};
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl2') || c.getContext('webgl');
  out.webgl = gl ? (gl instanceof WebGL2RenderingContext ? 'webgl2' : 'webgl') : null;
  if (gl) {
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    out.renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  }
  out.webgpu = null;
  if (navigator.gpu) {
    try {
      const a = await navigator.gpu.requestAdapter();
      out.webgpu = a ? (a.info ? (a.info.vendor + ' ' + a.info.architecture).trim() || 'adapter' : 'adapter') : 'no adapter';
    } catch (e) { out.webgpu = 'error: ' + e; }
  }
  const k = document.createElement('canvas').getContext('2d');
  k.fillStyle = '#123456'; k.fillRect(0, 0, 4, 4);
  out.canvas2d = Array.from(k.getImageData(1, 1, 1, 1).data).join(',');
  // The same through a canvas kept in CPU memory (willReadFrequently), to
  // tell a GPU rasterization difference from a drawing error.
  const s = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  s.fillStyle = '#123456'; s.fillRect(0, 0, 4, 4);
  out.canvas2d_cpu = Array.from(s.getImageData(1, 1, 1, 1).data).join(',');
  // How the context stores the colour, and a copy with no drawing at all.
  out.fill_style = s.fillStyle;
  const img = s.createImageData(1, 1); img.data.set([18, 52, 86, 255]);
  s.putImageData(img, 0, 0);
  out.put_get = Array.from(s.getImageData(0, 0, 1, 1).data).join(',');
  out.attributes = {cpu: s.getContextAttributes(), gpu: k.getContextAttributes()};
  out.screen = {dpr: devicePixelRatio, depth: screen.colorDepth,
                p3: matchMedia('(color-gamut: p3)').matches,
                hdr: matchMedia('(dynamic-range: high)').matches};
  // Every grey, drawn on the same pixel by a fill or copied in with
  // putImageData, on the CPU canvas and on the default one, read twice.
  // Only the values that do not read back as drawn are kept, as
  // "v->r,g,b,a" (and " then r,g,b,a" if the second read differed). With
  // Helium's canvas noise on, a quarter of the greys read one level off in
  // one channel; this group runs with it off.
  const sweep = (ctx, how) => {
    const off = [];
    for (let v = 0; v < 256; v++) {
      if (how === 'fill') {
        ctx.fillStyle = 'rgb(' + v + ',' + v + ',' + v + ')'; ctx.fillRect(0, 0, 2, 2);
      } else {
        const i = ctx.createImageData(2, 2);
        for (let p = 0; p < 16; p += 4) { i.data[p] = i.data[p + 1] = i.data[p + 2] = v; i.data[p + 3] = 255; }
        ctx.putImageData(i, 0, 0);
      }
      const d = Array.from(ctx.getImageData(0, 0, 1, 1).data).join(',');
      const e = Array.from(ctx.getImageData(0, 0, 1, 1).data).join(',');
      const want = [v, v, v, 255].join(',');
      if (d !== want || e !== want) off.push(v + '->' + d + (e !== d ? ' then ' + e : ''));
    }
    return off;
  };
  out.sweep_off = sweep(s, 'fill');
  out.sweeps = {cpu_fill_again: sweep(s, 'fill'), cpu_put: sweep(s, 'put'),
                gpu_fill: sweep(k, 'fill'), gpu_put: sweep(k, 'put')};
  // Primaries and a few mixed colours on the CPU canvas, by fill.
  const mixed = [];
  for (const [r, g, b] of [[255,0,0],[0,255,0],[0,0,255],[18,52,86],[86,52,18],[200,100,50],[1,2,3],[254,253,252]]) {
    s.fillStyle = 'rgb(' + r + ',' + g + ',' + b + ')'; s.fillRect(0, 0, 2, 2);
    const d = Array.from(s.getImageData(0, 0, 1, 1).data).join(',');
    if (d !== [r, g, b, 255].join(',')) mixed.push([r, g, b].join(',') + '->' + d);
  }
  out.mixed_off = mixed;
  // What the context says it holds for the first greys that moved.
  out.fill_style_of = {};
  for (const entry of out.sweep_off.slice(0, 3)) {
    const v = entry.split('->')[0];
    s.fillStyle = 'rgb(' + v + ',' + v + ',' + v + ')';
    out.fill_style_of[v] = s.fillStyle;
  }
  return out;
})()"""

ENTRY_RE = re.compile(r"^(\d+)->(\d+),(\d+),(\d+),(\d+)(?: then (\d+),(\d+),(\d+),(\d+))?$")


def sweep_summary(entries):
    """What a sweep's deviations have in common: how many greys moved, by
    how much and in which channels, whether a second read agreed, and the
    spacing between the values that moved (a period in the input points
    at a conversion, randomness at noise)."""
    values, steps, channels, unstable = [], [], {"R": 0, "G": 0, "B": 0, "A": 0}, 0
    for entry in entries:
        m = ENTRY_RE.match(entry)
        if not m:
            continue
        v = int(m.group(1))
        got = [int(m.group(i)) for i in range(2, 6)]
        want = [v, v, v, 255]
        for name, a, b in zip("RGBA", got, want):
            if a != b:
                channels[name] += 1
                steps.append(a - b)
        if m.group(6) is not None and [int(m.group(i)) for i in range(6, 10)] != got:
            unstable += 1
        values.append(v)
    if not values:
        return "none"
    gaps = sorted({b - a for a, b in zip(values, values[1:])})
    by_step = {s: steps.count(s) for s in sorted(set(steps))}
    return (f"{len(values)} of 256 greys off; steps {by_step}; channels "
            f"{ {k: v for k, v in channels.items() if v} }; values {values[0]}..{values[-1]}"
            f" with gaps {gaps}" + (f"; {unstable} read differently the second time" if unstable else ""))


NO_NOISE = "--disable-features=HeliumNoiseCanvas"


class Rendering(BrowserTest):
    BROWSER_ARGS = (NO_NOISE,)

    def probe_with(self, name, args):
        """The probe in a second browser started with |args| (and the noise
        off); its CPU fill sweep summary, or the error."""
        browser = None
        try:
            browser = Browser(self.ctx, name, args=[NO_NOISE] + list(args)).start()
            page = browser.new_page(self.ctx.fixtures().url("blank.html"))
            out = page.eval(PROBE)
            return sweep_summary(out.get("sweep_off", []))
        except Exception as e:  # a diagnosis, not the test
            return f"not run: {e}"
        finally:
            if browser:
                browser.stop()

    def test_webgl_webgpu_canvas(self):
        """Canvas colours read back as drawn, on a CPU canvas and the default
        one, with Helium's canvas noise off; WebGL is available in a window
        (headless may lack it)."""
        page = self.browser.new_page(self.ctx.fixtures().url("blank.html"))
        out = page.eval(PROBE)
        self.note(json.dumps(out))
        off = out.get("sweep_off", [])
        lines = ["CPU canvas, fill: " + sweep_summary(off),
                 "CPU canvas, fill again: " + sweep_summary(out.get("sweeps", {}).get("cpu_fill_again", [])),
                 "CPU canvas, putImageData: " + sweep_summary(out.get("sweeps", {}).get("cpu_put", [])),
                 "default canvas, fill: " + sweep_summary(out.get("sweeps", {}).get("gpu_fill", [])),
                 "default canvas, putImageData: " + sweep_summary(out.get("sweeps", {}).get("gpu_put", [])),
                 f"mixed colours off: {out.get('mixed_off')}",
                 f"fillStyle of the first greys that moved: {out.get('fill_style_of')}",
                 f"context attributes: {out.get('attributes')}; screen: {out.get('screen')}"]
        if off and not self.browser.headless:
            # The same probe under three switches, to place the fault: the
            # display colour profile forced to sRGB, no GPU at all, and
            # Skia's baseline CPU code instead of the AVX paths it picks at
            # run time (the port is built with the system compiler).
            lines.append("with --force-color-profile=srgb, CPU canvas, fill: "
                         + self.probe_with("rendering-srgb", ["--force-color-profile=srgb"]))
            lines.append("with --disable-gpu, CPU canvas, fill: "
                         + self.probe_with("rendering-nogpu", ["--disable-gpu"]))
            lines.append("with --disable-skia-runtime-opts, CPU canvas, fill: "
                         + self.probe_with("rendering-baseline", ["--disable-skia-runtime-opts"]))
        self.note("\n".join(lines))
        self.assertEqual(off, [], "greys that did not read back as drawn on the CPU canvas:\n"
                         + "\n".join(lines))
        self.assertEqual(out.get("mixed_off"), [], "colours that did not read back as drawn")
        self.assertEqual(out["put_get"], "18,52,86,255", "a copied pixel changed")
        self.assertEqual(out["canvas2d_cpu"], "18,52,86,255", "the CPU canvas is wrong")
        self.assertEqual(out["canvas2d"], "18,52,86,255", "the default canvas is wrong")
        if not self.browser.headless:
            self.assertTrue(out["webgl"], "WebGL is not available")

    def test_gpu_info(self):
        """Record what the GPU process reports (driver, features, workarounds)
        and what the GPU page says about the displays (colour space, bits)."""
        info = self.browser.conn.send("SystemInfo.getInfo", timeout=30)
        with open(self.ctx.artifact("gpu-info.json"), "w") as f:
            json.dump(info, f, indent=2)
        gpu = info.get("gpu", {})
        devices = [f"{d.get('vendorString')} {d.get('deviceString')} driver "
                   f"{d.get('driverVendor')} {d.get('driverVersion')}"
                   for d in gpu.get("devices", [])]
        status = gpu.get("featureStatus", {})
        lines = ["devices: " + "; ".join(devices),
                 "feature status: " + ", ".join(f"{k}={v}" for k, v in sorted(status.items()))]
        # The GPU page's display section: colour space, bits per component,
        # SDR white level, HDR. A canvas colour that reads back one level
        # off would follow a display profile that is not plain sRGB.
        try:
            page = self.browser.new_page(self.browser.url("gpu"))
            self.browser.wait(2)
            text = page.eval("document.body.innerText") or ""
            wanted = re.compile(r"Display\[|[Cc]olor space|[Cc]olor volume|Bits per|white level|HDR|Buffer format")
            shown = [l.strip() for l in text.splitlines() if wanted.search(l)]
            lines.append("displays (beryllium://gpu): " + ("\n  ".join([""] + shown[:24]) if shown else "nothing shown"))
        except Exception as e:  # a note, not the test
            lines.append(f"displays (beryllium://gpu): not read: {e}")
        self.note("\n".join(lines))
        self.assertTrue(gpu.get("devices"), "no GPU information")
