// SPDX-License-Identifier: GPL-3.0-only
// node render-batch.js jobs.json   jobs: [{svg, size, out, bg}]
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 64, height: 64 }, deviceScaleFactor: 1 });
  for (const j of jobs) {
    const svg = fs.readFileSync(j.svg, 'utf8');
    await p.setViewportSize({ width: j.size, height: j.size });
    await p.setContent(`<html><body style="margin:0;background:${j.bg || 'transparent'}">` +
      `<img id=i style="display:block;width:${j.size}px;height:${j.size}px" src="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}"></body></html>`);
    await p.waitForFunction(() => document.getElementById('i').complete);
    await p.screenshot({ path: j.out, omitBackground: !j.bg });
  }
  await b.close();
})();
