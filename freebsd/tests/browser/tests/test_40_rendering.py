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
  // How the context stores the colour, and a copy with no drawing at all:
  // under the renderer lockdown a channel has read one level off (plan/14),
  // and these say whether the parser, the fill or the copy moves it.
  out.fill_style = s.fillStyle;
  const img = s.createImageData(1, 1); img.data.set([18, 52, 86, 255]);
  s.putImageData(img, 0, 0);
  out.put_get = Array.from(s.getImageData(0, 0, 1, 1).data).join(',');
  // A sweep of greys and primaries on the CPU canvas: which values move.
  const off = [];
  const probe = (r, g, b) => {
    s.fillStyle = 'rgb(' + r + ',' + g + ',' + b + ')'; s.fillRect(0, 0, 2, 2);
    const d = s.getImageData(0, 0, 1, 1).data;
    if (d[0] !== r || d[1] !== g || d[2] !== b || d[3] !== 255) off.push([r, g, b].join(',') + '->' + Array.from(d).join(','));
  };
  for (let v = 0; v < 256; v += 5) probe(v, v, v);
  for (const c of [[255,0,0],[0,255,0],[0,0,255],[18,52,86],[86,52,18],[200,100,50],[1,2,3],[254,253,252]]) probe(...c);
  out.sweep_off = off;
  return out;
})()"""


class Rendering(BrowserTest):
    def test_webgl_webgpu_canvas(self):
        """Canvas draws; WebGL is available in a window (headless may lack it)."""
        page = self.browser.new_page(self.ctx.fixtures().url("blank.html"))
        out = page.eval(PROBE)
        self.note(json.dumps(out))
        # Exact on both canvases. Under the renderer lockdown a channel has
        # read one level off (18,52,87 in 0.20.3.10 on the GPU canvas;
        # 18,53,86 in 0.20.3.12 on both), never without it; the sweep above
        # is recorded to find out why (plan/14).
        self.assertEqual(out.get("sweep_off"), [],
                         "colours that did not read back as drawn on the CPU canvas")
        self.assertEqual(out["put_get"], "18,52,86,255", "a copied pixel changed")
        self.assertEqual(out["canvas2d_cpu"], "18,52,86,255", "the CPU canvas is wrong")
        self.assertEqual(out["canvas2d"], "18,52,86,255", "the default canvas is wrong")
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
