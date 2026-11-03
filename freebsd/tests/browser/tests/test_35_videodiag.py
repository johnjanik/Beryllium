# SPDX-License-Identifier: GPL-3.0-only
"""Video crash diagnosis (--diagnose): replays video playback under browser
switches that each turn off one part of the video path, and records which
ones avoid the crash. Owner's report, 3 November 2026: every video test
crashed the renderer with SIGSEGV on the 15.1 package on 16-CURRENT, while
audio played."""

import json
import os
import unittest

from berytest import context
from berytest.browser import Browser, has_display
from berytest.cdp import CDPError, TargetCrashed
from tests.test_30_media import PLAY

# (name, switches, headless) - each turns off one suspect.
VARIANTS = [
    ("as normally run", [], None),
    ("one decode thread (--video-threads=1)", ["--video-threads=1"], None),
    ("no GPU at all (--disable-gpu)", ["--disable-gpu"], None),
    ("no hardware video decode", ["--disable-accelerated-video-decode"], None),
    ("no GPU memory buffers for video frames",
     ["--disable-gpu-memory-buffer-video-frames"], None),
    ("no VA-API decoders", ["--disable-features=VaapiVideoDecoder,VaapiVideoDecodeLinux,"
                            "AcceleratedVideoDecodeLinuxGL,AcceleratedVideoDecodeLinuxZeroCopyGL"],
     None),
    ("software GL (SwiftShader)", ["--use-gl=angle", "--use-angle=swiftshader",
                                   "--enable-unsafe-swiftshader"], None),
    ("X11 instead of Wayland", ["--ozone-platform=x11"], None),
    ("headless", [], True),
]
CLIPS = [("h264_aac.mp4", False, "video"), ("mse_vp9.webm", True, "video"),
         ("mse_av1.mp4", True, "video"), ("mse_opus.webm", True, "audio")]


class VideoDiagnosis(unittest.TestCase):
    def test_which_switch_avoids_the_crash(self):
        """Play video under each switch; the table shows what avoids the crash."""
        ctx = context.get()
        if not ctx.options.diagnose:
            self.skipTest("run with --diagnose")
        clips, why = ctx.media()
        clips_here = [c for c in CLIPS if c[0] in clips]
        if not clips_here:
            self.skipTest(why.get("*") or "no clips")
        rows = []
        for name, args, headless in VARIANTS:
            if headless is None and not has_display() and not ctx.options.headless:
                continue
            if "--ozone-platform=x11" in args and not os.environ.get("DISPLAY"):
                rows.append((name, {c[0]: "skipped (no X11 DISPLAY)" for c in clips_here}))
                continue
            results = {}
            try:
                browser = Browser(ctx, "diag", args=args, headless=headless).start()
            except CDPError as e:
                rows.append((name, {c[0]: f"browser did not start: {str(e)[:80]}"
                                    for c in clips_here}))
                continue
            try:
                for clip, mse, kind in clips_here:
                    page = browser.new_page(ctx.fixtures().url("blank.html"))
                    arg = json.dumps([ctx.fixtures().url(clip), mse, clips[clip], kind])[1:-1]
                    try:
                        r = page.eval(PLAY % arg, timeout=60)
                        if r.get("ok"):
                            results[clip] = "plays" + (f" ({r.get('frames')} frames)"
                                                       if r.get("frames") else "")
                        else:
                            results[clip] = f"error: {r}"
                    except TargetCrashed as e:
                        results[clip] = f"CRASH (code {e.error_code})"
                    except CDPError as e:
                        results[clip] = f"error: {str(e)[:80]}"
                    finally:
                        browser.close_page(page)
            finally:
                browser.stop()
            rows.append((name, results))
        header = ["switches"] + [c[0] for c in clips_here]
        body = [[name] + [results.get(c[0], "-") for c in clips_here] for name, results in rows]
        widths = [max(len(r[i]) for r in [header] + body) for i in range(len(header))]
        table = "\n".join("  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip()
                          for r in [header] + body)
        with open(ctx.artifact("video-diagnosis.txt"), "w") as f:
            f.write(table + "\n")
        ctx.note(self.id(), table)
