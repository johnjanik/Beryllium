# SPDX-License-Identifier: GPL-3.0-only
"""Graphics: WebGL, WebGPU and canvas work, and what the GPU process reports."""

import json

from berytest.base import BrowserTest

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
  return out;
})()"""


class Rendering(BrowserTest):
    def test_webgl_webgpu_canvas(self):
        """Canvas draws; WebGL is available in a window (headless may lack it)."""
        page = self.browser.new_page(self.ctx.fixtures().url("blank.html"))
        out = page.eval(PROBE)
        self.note(json.dumps(out))
        self.assertEqual(out["canvas2d_cpu"], "18,52,86,255", "the CPU canvas is wrong")
        # The default canvas is GPU-backed; its readback was one level off
        # once (0.20.3.10, 18,52,87) and exact in every other run, so one
        # level is allowed there and the exact value is on record above.
        got = [int(x) for x in out["canvas2d"].split(",")]
        self.assertEqual(len(got), 4, out["canvas2d"])
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(got, [18, 52, 86, 255])),
                        f"the default canvas read {out['canvas2d']} for #123456")
        if not self.browser.headless:
            self.assertTrue(out["webgl"], "WebGL is not available")

    def test_gpu_info(self):
        """Record what the GPU process reports (driver, features, workarounds)."""
        info = self.browser.conn.send("SystemInfo.getInfo", timeout=30)
        with open(self.ctx.artifact("gpu-info.json"), "w") as f:
            json.dump(info, f, indent=2)
        gpu = info.get("gpu", {})
        devices = [f"{d.get('vendorString')} {d.get('deviceString')} driver "
                   f"{d.get('driverVendor')} {d.get('driverVersion')}"
                   for d in gpu.get("devices", [])]
        status = gpu.get("featureStatus", {})
        self.note("devices: " + "; ".join(devices) + "\nfeature status: "
                  + ", ".join(f"{k}={v}" for k, v in sorted(status.items())))
        self.assertTrue(gpu.get("devices"), "no GPU information")
