# SPDX-License-Identifier: GPL-3.0-only
"""Capsicum survey (--diagnose): runs the browser under ktrace and records,
per process type, everything capability mode would refuse (system calls,
path lookups, sysctls) across the plan/09 Phase 2 workloads, with each
process's descriptors, environment variable names and limits. Builds with
patches/security/beryllium-capsicum-renderer.patch write a marker at the
renderer's lockdown point (utrace, traced with -t u); the report then
separates what a renderer does before it (start-up, allowed) from what it
does after (must work in capability mode). The input to the renderer
sandbox (feature matrix S-REN-02 warm-up and S-REN-03 descriptor
inventory). Nothing is confined unless the browser is started with
--enable-features=BerylliumCapsicumRenderer.

Results: capsicum-survey.txt (read this), capsicum-survey.json, and
capsicum-kdump.txt.gz (the trace lines of every process but the browser)."""

import gzip
import json
import os
import platform
import shutil
import struct
import subprocess
import time
import unittest
import zlib

from berytest import capsicum, context
from berytest.browser import Browser, has_display
from berytest.cdp import CDPError

RESULTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                           "results"))


def png(width=64, height=64):
    """A small RGB gradient PNG."""
    raw = b"".join(b"\x00" + b"".join(bytes((x * 4 % 256, y * 4 % 256, 128))
                                      for x in range(width)) for y in range(height))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def pdf():
    """A one-page PDF (PDFium repairs the missing cross-reference table)."""
    content = b"BT /F1 24 Tf 20 100 Td (Beryllium) Tj ET"
    return (b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
            b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
            b"4 0 obj<</Length " + str(len(content)).encode() + b">>stream\n"
            + content + b"\nendstream endobj\n"
            b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")


# (module (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add))
WASM = bytes.fromhex("0061736d0100000001070160027f7f017f030201000707010361646400000a"
                     "09010700200020016a0b")

PAGES = {
    "text.html": """<!doctype html><meta charset="utf-8"><title>text</title>
<p style="font-family:serif">The quick brown fox jumps over the lazy dog.</p>
<p style="font-family:sans-serif">日本語のテキスト。中文文本。한국어 텍스트.</p>
<p>Emoji: 😀 🎉 🦊 👩‍💻</p><p dir="rtl">نص عربي. טקסט בעברית.</p>
<p>हिन्दी पाठ। ไทย ภาษา</p><p style="font-family:monospace">monospace 0123456789</p>""",
    "image.html": """<!doctype html><title>image</title><img src="gradient.png" width="256">
<canvas id="c" width="200" height="200"></canvas><script>
const g = document.getElementById('c').getContext('2d');
g.fillStyle = '#c00'; g.fillRect(10, 10, 100, 100);
g.font = '20px sans-serif'; g.fillText('canvas text', 20, 150);
document.title = 'image ' + document.getElementById('c').toDataURL().length;
</script>""",
    "webgl.html": """<!doctype html><title>webgl</title><canvas id="c" width="256" height="256"></canvas><script>
const gl = document.getElementById('c').getContext('webgl2');
if (gl) { gl.clearColor(0.2, 0.4, 0.6, 1); gl.clear(gl.COLOR_BUFFER_BIT);
  const px = new Uint8Array(4); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
  document.title = 'webgl ' + px.join(','); } else { document.title = 'webgl none'; }
</script>""",
    "wasm.html": """<!doctype html><title>wasm</title><script>
fetch('add.wasm').then(r => r.arrayBuffer()).then(b => WebAssembly.instantiate(b))
  .then(m => { document.title = 'wasm ' + m.instance.exports.add(2, 3); })
  .catch(e => { document.title = 'wasm error ' + e; });
</script>""",
    "worker.html": """<!doctype html><title>worker</title><script>
const src = 'let s = 0; for (let i = 0; i < 5e6; i++) s += i; postMessage(s);';
const w = new Worker(URL.createObjectURL(new Blob([src], {type: 'text/javascript'})));
w.onmessage = e => { document.title = 'worker ' + e.data; };
</script>""",
    "sw.js": "self.addEventListener('fetch', e => {});\n",
    "serviceworker.html": """<!doctype html><title>serviceworker</title><script>
navigator.serviceWorker.register('sw.js').then(() => navigator.serviceWorker.ready)
  .then(() => { document.title = 'serviceworker ready'; })
  .catch(e => { document.title = 'serviceworker error ' + e; });
</script>""",
    "storage.html": """<!doctype html><title>storage</title><script>
localStorage.setItem('k', 'v'.repeat(1000));
const req = indexedDB.open('db', 1);
req.onupgradeneeded = () => req.result.createObjectStore('s');
req.onsuccess = () => { const tx = req.result.transaction('s', 'readwrite');
  tx.objectStore('s').put('value', 'key'); tx.oncomplete = () => { document.title = 'storage ok'; }; };
fetch('text.html').then(r => r.text()).then(t => { document.title += ' fetched ' + t.length; });
</script>""",
    "form.html": """<!doctype html><title>form</title><form>
<input id="name" autocomplete="name"><input type="email" autocomplete="email">
<input type="date"><input type="color"><input type="range">
<select><option>one</option><option>two</option></select><textarea>text</textarea>
<input type="file"></form><script>
const n = document.getElementById('name'); n.focus(); n.value = 'Beryllium'; n.select();
</script>""",
}


def ktrace_works(scratch):
    """ktrace may be refused (security.bsd.unprivileged_proc_debug=0)."""
    trace = os.path.join(scratch, "probe.ktr")
    try:
        r = subprocess.run(["ktrace", "-i", "-t", "p", "-f", trace, "true"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return None if r.returncode == 0 else (r.stderr.strip() or f"exit {r.returncode}")


class CapsicumSurvey(unittest.TestCase):
    def test_capability_mode_survey(self):
        """Record what each process does that capability mode would refuse."""
        ctx = context.get()
        if not ctx.options.diagnose:
            self.skipTest("run with --diagnose")
        if not ctx.is_freebsd():
            self.skipTest("FreeBSD only (ktrace capability-failure tracing)")
        if not shutil.which("ktrace") or not shutil.which("kdump"):
            self.skipTest("ktrace and kdump not found")
        headless = ctx.options.headless or not has_display()
        scratch = ctx.scratch("capsicum")
        problem = ktrace_works(scratch)
        if problem:
            self.skipTest(f"ktrace not permitted ({problem}); "
                          "security.bsd.unprivileged_proc_debug must be 1 for this run")

        workloads = [("blank", ctx.fixtures().url("blank.html"))]
        ctx.add_fixture("gradient.png", png())
        ctx.add_fixture("doc.pdf", pdf())
        ctx.add_fixture("add.wasm", WASM)
        for name, html in PAGES.items():
            url = ctx.add_fixture(name, html)
            if name.endswith(".html"):
                workloads.append((name[:-5], url))
        workloads.append(("busy", ctx.fixtures().url("busy.html")))
        workloads.append(("pdf", ctx.fixtures().url("doc.pdf")))
        clips, _ = ctx.media()
        for clip in ("h264_aac.mp4", "vp9_opus.webm"):
            if clip in clips:
                url = ctx.add_fixture(f"video-{clip}.html",
                                      f'<!doctype html><title>video</title><video src="{clip}" '
                                      'autoplay muted loop width="320"></video>')
                workloads.append((f"video {clip}", url))
        workloads.append(("print to PDF", ctx.fixtures().url("text.html")))

        trace = os.path.join(scratch, "browser.ktr")
        browser = Browser(ctx, "capsicum", headless=headless,
                          wrapper=["ktrace", "-i", "-t", "pnyu", "-f", trace]).start()
        browser.record_version()
        types = {browser.proc.pid: "browser"}
        samples = {}
        ran = []

        def sample(workload):
            try:
                procs = browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
            except CDPError:
                return
            for p in procs:
                pid, ptype = p["id"], p["type"]
                types[pid] = ptype
                if ptype == "browser":
                    continue
                s = samples.get(pid)
                if s is None:
                    s = samples[pid] = {"pid": pid, "type": ptype, "workloads": [],
                                        "env": capsicum.environment_names(pid),
                                        "limits": capsicum.limits(pid)}
                s["workloads"].append(workload)
                s["fds"] = capsicum.descriptors(pid)

        try:
            sample("start")
            for name, url in workloads:
                try:
                    page = browser.new_page(url, timeout=30)
                except CDPError as e:
                    ran.append(f"{name}: did not load ({str(e)[:80]})")
                    continue
                try:
                    if name == "print to PDF":
                        page.send("Page.printToPDF", {}, timeout=60)
                    time.sleep(4)
                    title = page.eval("document.title", timeout=10)
                    ran.append(f"{name}: {title}")
                    sample(name)
                except CDPError as e:
                    ran.append(f"{name}: {str(e)[:80]}")
                finally:
                    browser.close_page(page)
        finally:
            browser.stop()

        readable, readable_from = capsicum.readable_sysctls(RESULTS_DIR, platform.release())
        no_fds = samples and not any(s.get("fds") for s in samples.values())
        debug = capsicum.proc_debug_setting()
        fd_note = ""
        if no_fds:
            fd_note = ("Descriptors and environment could not be read (procstat -f and -e "
                       f"need security.bsd.unprivileged_proc_debug=1; it is {debug}). To "
                       "include them, run again after: doas sysctl "
                       "security.bsd.unprivileged_proc_debug=1 (and set it back after).\n\n")
        kept = []
        with subprocess.Popen(["kdump", "-f", trace], stdout=subprocess.PIPE, text=True,
                              errors="replace") as proc:
            parsed_lines = []
            for line in proc.stdout:
                m = capsicum.KDUMP_RE.match(line)
                if m and types.get(int(m.group(1))) != "browser":
                    parsed_lines.append(line)
                    kept.append(line)
        kdump = capsicum.parse_kdump(parsed_lines)
        summary = capsicum.summarise(kdump, types, readable)
        text = (f"Capsicum survey, {time.strftime('%Y-%m-%d %H:%M:%S')}, kernel "
                f"{platform.release()}, browser {getattr(ctx, 'browser_version', {}).get('product', '?')}\n"
                "Workloads (name: page title when done):\n"
                + "".join(f"  {r}\n" for r in ran) + "\n" + fd_note
                + capsicum.report(summary, samples, readable_from))
        with open(ctx.artifact("capsicum-survey.txt"), "w") as f:
            f.write(text)
        with open(ctx.artifact("capsicum-survey.json"), "w") as f:
            json.dump({"kernel": platform.release(), "readable_from": readable_from,
                       "workloads": ran, "types": {str(k): v for k, v in types.items()},
                       "samples": {str(k): v for k, v in samples.items()},
                       "summary": {k: {"pids": v["pids"], "cap": dict(v["cap"]),
                                       "cap_after": dict(v["cap_after"]),
                                       "cap_paths": dict(v["cap_paths"]),
                                       "cap_paths_after": dict(v["cap_paths_after"]),
                                       "sysctl_after": dict(v["sysctl_after"]),
                                       "sysctl": dict(v["sysctl"]),
                                       "sysctl_blocked": v["sysctl_blocked"]}
                                   for k, v in summary.items()}}, f, indent=1)
        with gzip.open(ctx.artifact("capsicum-kdump.txt.gz"), "wt") as f:
            f.writelines(kept)
        renderer = summary.get("renderer", {})
        ctx.note(self.id(), f"renderer processes: {len(renderer.get('pids', []))}, "
                 f"distinct refusals: {len(renderer.get('cap', {}))}, sysctls read: "
                 f"{len(renderer.get('sysctl', {}))}; details in capsicum-survey.txt")
        self.assertTrue(kdump, "ktrace recorded nothing; is CAPFAIL tracing supported "
                        "(FreeBSD 14.1, 15 or later)?")
