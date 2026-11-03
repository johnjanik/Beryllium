# SPDX-License-Identifier: GPL-3.0-only
"""Live YouTube playback (needs --network). Watches a video for --watch
seconds and fails on a renderer crash (the sad tab's "Error code 11" is
signal 11, SIGSEGV), a player error, or playback that does not advance.
Samples are saved to youtube-samples.json, with the codecs YouTube chose."""

import json
import time

from berytest.base import BrowserTest
from berytest.cdp import CDPError, TargetCrashed

CONSENT = """(() => {
  const b = [...document.querySelectorAll('button, [role=button]')]
    .find(e => /reject all|alle ablehnen|tout refuser|rechazar todo/i.test(e.innerText || e.getAttribute('aria-label') || ''));
  if (b) { b.click(); return true; }
  return false;
})()"""

SAMPLE = """(() => {
  const v = document.querySelector('video');
  const p = document.getElementById('movie_player');
  let stats = null;
  try { stats = p && p.getStatsForNerds ? p.getStatsForNerds() : null; } catch (e) {}
  const err = document.querySelector('.ytp-error');
  if (v && v.paused && !v.ended) { v.muted = true; v.play().catch(() => {}); }
  return {
    url: location.href,
    video: !!v,
    t: v ? v.currentTime : null,
    paused: v ? v.paused : null,
    readyState: v ? v.readyState : null,
    mediaError: v && v.error ? v.error.code : null,
    playerError: err && err.offsetParent ? err.innerText.slice(0, 200) : null,
    ad: !!document.querySelector('.ad-showing'),
    codecs: stats ? stats.codecs : null,
    resolution: stats ? stats.resolution : null,
    dropped: v && v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality().droppedVideoFrames : null,
  };
})()"""


class YouTube(BrowserTest):
    NEEDS_NETWORK = True

    def test_watch_video(self):
        """A YouTube video plays for the watch period without a crash."""
        opts = self.ctx.options
        page = self.browser.new_page()
        samples = []
        try:
            page.navigate(f"https://www.youtube.com/watch?v={opts.youtube_video}", timeout=60)
            time.sleep(3)
            if "consent." in (page.eval("location.host") or "") or page.eval(CONSENT):
                self.note("dismissed a cookie consent dialog (Reject all)")
                time.sleep(5)
            deadline = time.monotonic() + opts.watch
            while time.monotonic() < deadline:
                samples.append(dict(page.eval(SAMPLE), at=round(time.monotonic() - deadline + opts.watch)))
                time.sleep(2)
        except TargetCrashed as e:
            self.save(samples)
            self.fail(f"renderer crashed during playback (error code {e.error_code}; 11 is "
                      f"SIGSEGV) after {len(samples) * 2} s; last sample: "
                      f"{samples[-1] if samples else None}\n{self.kernel_crash_log()}\n"
                      f"browser log tail:\n{self.browser.log_tail(40)}")
        except CDPError as e:
            self.save(samples)
            self.fail(f"{e}\nbrowser log tail:\n{self.browser.log_tail(40)}")
        self.save(samples)
        last_url = samples[-1]["url"] if samples else ""
        if "/sorry/" in last_url or "consent." in last_url:
            self.skipTest(f"YouTube showed a robot check or consent page instead of the "
                          f"video ({last_url[:80]}); open YouTube in Beryllium once and rerun")
        self.assertTrue(samples and samples[-1]["video"], "no video element found")
        codecs = next((s["codecs"] for s in reversed(samples) if s.get("codecs")), None)
        self.note(f"codecs: {codecs}; last sample: {samples[-1]}")
        errors = [s["playerError"] or f"media error {s['mediaError']}" for s in samples
                  if s.get("playerError") or s.get("mediaError")]
        self.assertEqual(errors[:1], [], "the player reported an error")
        played = max((s["t"] or 0) for s in samples)
        self.assertGreater(played, opts.watch / 3, "playback did not advance")

    def save(self, samples):
        with open(self.ctx.artifact("youtube-samples.json"), "w") as f:
            json.dump(samples, f, indent=2)
