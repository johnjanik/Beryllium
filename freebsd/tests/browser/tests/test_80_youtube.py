# SPDX-License-Identifier: GPL-3.0-only
"""Live YouTube playback (needs --network). Watches a video for --watch
seconds and fails on a renderer crash (the sad tab's "Error code 11" is
signal 11, SIGSEGV), a player error, or playback that does not advance.
Samples are saved to youtube-samples.json, with the codecs YouTube chose.

When the video does not play, the report says who refused what: YouTube's
own answer for the video (its playability status), the player's error
fields, the requests that failed or came back with an error status, by
host, and the page's console errors. A session YouTube asks to sign in
("confirm you're not a bot") is skipped, not failed: the suite's profile is
new and driven over DevTools, and that refusal says nothing about the
browser."""

import collections
import json
import time
import urllib.parse

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


# What the player itself says: YouTube's answer for the video, and the
# fields of the player's "debug info" that describe an error.
DIAGNOSE = """(() => {
  const p = document.getElementById('movie_player');
  const out = {status: null, reason: null, debug: {}};
  try {
    const r = p && p.getPlayerResponse && p.getPlayerResponse();
    const s = r && r.playabilityStatus;
    if (s) { out.status = s.status || null; out.reason = s.reason || null; }
  } catch (e) { out.status = 'not readable: ' + e; }
  try {
    const d = JSON.parse(p && p.getDebugText ? p.getDebugText(true) : '{}');
    for (const k of ['state', 'vec', 'vemsg', 'debug_error', 'debug_playbackQuality',
                     'release_version', 'dis'])
      if (d[k] !== undefined && d[k] !== '' && d[k] !== 'null') out.debug[k] = String(d[k]).slice(0, 300);
  } catch (e) { out.debug.unreadable = String(e).slice(0, 120); }
  return out;
})()"""

# Hosts with many numbered names, shown under one.
HOST_GROUPS = ("googlevideo.com", "ytimg.com", "ggpht.com", "doubleclick.net",
               "googlesyndication.com", "googleusercontent.com")


def host_of(url):
    host = urllib.parse.urlsplit(url or "").hostname or "?"
    for group in HOST_GROUPS:
        if host == group or host.endswith("." + group):
            return "*." + group
    return host


def network_summary(events, session):
    """(failed, refused) from a page's Network events: Counters of
    (host, error text) for requests that failed (net::ERR_BLOCKED_BY_CLIENT
    is the content blocker's doing) and of (host, status) for responses of
    400 and above."""
    urls, failed, refused = {}, collections.Counter(), collections.Counter()
    for e in events:
        if e.get("sessionId") != session:
            continue
        p = e.get("params", {})
        if e["method"] == "Network.requestWillBeSent":
            urls[p.get("requestId")] = p.get("request", {}).get("url", "")
        elif e["method"] == "Network.loadingFailed":
            if p.get("canceled") and not p.get("blockedReason"):
                continue  # the page gave the request up itself
            why = p.get("errorText") or p.get("blockedReason") or "failed"
            failed[(host_of(urls.get(p.get("requestId"), "")), why)] += 1
        elif e["method"] == "Network.responseReceived":
            r = p.get("response", {})
            if r.get("status", 0) >= 400:
                refused[(host_of(r.get("url", "")), r["status"])] += 1
    return failed, refused


def console_errors(events, session, limit=6):
    """The page's first error messages (console.error, uncaught exceptions
    and the browser's own log entries at error level), shortened."""
    out = []
    for e in events:
        if e.get("sessionId") != session:
            continue
        p = e.get("params", {})
        text = None
        if e["method"] == "Runtime.consoleAPICalled" and p.get("type") == "error":
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
        elif e["method"] == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            text = d.get("exception", {}).get("description") or d.get("text")
        elif e["method"] == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
            entry = p["entry"]
            text = f"{entry.get('text', '')} ({host_of(entry.get('url', ''))})"
        if text:
            text = " ".join(text.split())[:200]
            if text not in out:
                out.append(text)
        if len(out) >= limit:
            break
    return out


def describe_failure(diagnosis, failed, refused, errors):
    """The lines a report gets when the video did not play."""
    d = diagnosis or {}
    lines = [f"YouTube's answer for the video: {d.get('status') or 'none read'}"
             + (f" ({d['reason']})" if d.get("reason") else "")]
    if d.get("debug"):
        lines.append("player: " + ", ".join(f"{k}={v}" for k, v in sorted(d["debug"].items())))
    if failed:
        lines.append("requests that failed: " + "; ".join(
            f"{n} to {host} ({why})" for (host, why), n in failed.most_common(8)))
    if refused:
        lines.append("responses with an error status: " + "; ".join(
            f"{n} from {host} ({status})" for (host, status), n in refused.most_common(8)))
    if not failed and not refused:
        lines.append("no request failed and no response had an error status")
    if errors:
        lines.append("console errors: " + " | ".join(errors))
    return lines


def refused_by_youtube(diagnosis):
    """YouTube declined to serve this session at all (it wants a sign-in, or
    says the video cannot be played here): the browser's playback was never
    tried. "OK" and no answer both mean the player went on."""
    status = (diagnosis or {}).get("status")
    return bool(status) and status != "OK" and not str(status).startswith("not readable")


class YouTube(BrowserTest):
    NEEDS_NETWORK = True

    def test_watch_video(self):
        """A YouTube video plays for the watch period without a crash."""
        opts = self.ctx.options
        page = self.browser.new_page()
        samples = []
        mark = self.browser.conn.mark()
        for domain in ("Network", "Log"):
            try:
                page.send(f"{domain}.enable")
            except CDPError:
                pass
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
        codecs = next((s["codecs"] for s in reversed(samples) if s.get("codecs")), None)
        self.note(f"codecs: {codecs}; last sample: {samples[-1] if samples else None}")
        errors = [s["playerError"] or f"media error {s['mediaError']}" for s in samples
                  if s.get("playerError") or s.get("mediaError")]
        played = max(((s["t"] or 0) for s in samples), default=0)
        if errors or played <= opts.watch / 3:
            # Who refused what, before anything is asserted.
            try:
                diagnosis = page.eval(DIAGNOSE)
            except CDPError as e:
                diagnosis = {"status": f"not readable: {e}"}
            events = self.browser.conn.events(since=mark)
            failed, refused = network_summary(events, page.session)
            self.note("\n".join(describe_failure(diagnosis, failed, refused,
                                                 console_errors(events, page.session))))
            if refused_by_youtube(diagnosis):
                self.skipTest("YouTube would not serve this session: "
                              f"{diagnosis.get('status')} ({diagnosis.get('reason')}); the "
                              "suite's profile is new and driven over DevTools. Play the "
                              "video in Beryllium by hand to check playback itself")
        self.assertTrue(samples and samples[-1]["video"], "no video element found")
        self.assertEqual(errors[:1], [], "the player reported an error")
        self.assertGreater(played, opts.watch / 3, "playback did not advance")

    def save(self, samples):
        with open(self.ctx.artifact("youtube-samples.json"), "w") as f:
            json.dump(samples, f, indent=2)
