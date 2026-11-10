# SPDX-License-Identifier: GPL-3.0-only
"""Privacy (plan/07 section 6): a fresh browser left alone, or showing a
local page, contacts no outside host, and online services stay silent
until the user sets a server (feature matrix P-SVC-01). All traffic goes
through a local recording proxy that refuses every connection, so nothing
leaves the machine; the proxy's list of requested hosts is the result.
Also Helium's canvas fingerprinting noise (P-FPR-04): present by default,
stable within a session, different per site, chosen by the whole per-site
token, absent with the feature off."""

import json
import time

from berytest import noise
from berytest.base import BrowserTest
from berytest.browser import Browser
from berytest.cdp import CDPError
from berytest.servers import RecordingProxy

GET_PREF = """new Promise((ok, bad) => {
  if (!window.chrome || !chrome.settingsPrivate) { bad(new Error('settingsPrivate unavailable')); return; }
  chrome.settingsPrivate.getPref(%s, p => ok(p ? p.value : null));
})"""
SET_PREF = """new Promise((ok, bad) => {
  if (!window.chrome || !chrome.settingsPrivate) { bad(new Error('settingsPrivate unavailable')); return; }
  chrome.settingsPrivate.setPref(%s, %s, '', ok);
})"""


class Proxied(BrowserTest):
    """A browser whose every connection goes to a recording proxy."""
    proxy = None

    @classmethod
    def setUpClass(cls):
        cls.proxy = RecordingProxy(allow=False)
        try:
            super().setUpClass()
        except Exception:
            cls.proxy.close()
            raise

    @classmethod
    def extra_args(cls):
        return [f"--proxy-server={cls.proxy.address()}"]

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls.proxy:
            cls.proxy.close()

    def record(self, label):
        lines = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {m} {h}:{p}"
                 for t, m, h, p in self.proxy.requests]
        with open(self.ctx.artifact(f"privacy-{label}.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        return lines


class QuietWhenIdle(Proxied):
    def test_idle_browser_contacts_no_one(self):
        """A new profile, left idle, makes no outside connection."""
        time.sleep(self.ctx.options.idle)
        lines = self.record("idle")
        self.assertEqual(self.proxy.hosts(), [], "hosts contacted while idle:\n"
                         + "\n".join(lines))

    def test_local_page_contacts_no_one(self):
        """Showing a local page causes no outside connection."""
        before = len(self.proxy.requests)
        page = self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        time.sleep(5)
        self.browser.close_page(page)
        new = self.proxy.requests[before:]
        self.record("local-page")
        self.assertEqual(sorted({h for _, _, h, _ in new}), [])


class ServicesOff(Proxied):
    """Online services are off in a new profile; switched on, with the
    user's consent (what accepting the setup page does) but no server set,
    they still contact no one. Before the fix this sent requests to
    Helium's server (patches/privacy/beryllium-services-off-by-default.patch)."""

    def pref(self, page, name):
        return page.eval(GET_PREF % json.dumps(name))

    def test_services_off_in_a_new_profile(self):
        """A new profile has online services switched off and no server."""
        page = self.browser.new_page(self.url("settings"))
        try:
            enabled = self.pref(page, "helium.services.enabled")
            origin = self.pref(page, "helium.services.origin_override")
        finally:
            self.browser.close_page(page)
        self.note(f"helium.services.enabled={enabled!r} origin_override={origin!r}")
        self.assertIsNotNone(enabled, "no helium.services.enabled preference (not Beryllium?)")
        self.assertIs(enabled, False, "online services are on in a new profile")
        self.assertFalse(origin, f"a services server is set in a new profile: {origin!r}")

    def test_switched_on_without_server_contacts_no_one(self):
        """With services on and consent given but no server, nothing is contacted."""
        page = self.browser.new_page(self.url("settings"))
        try:
            for name in ("helium.services.user_consented", "helium.services.enabled"):
                page.eval(SET_PREF % (json.dumps(name), "true"))
                self.assertIs(self.pref(page, name), True, f"could not set {name}")
        finally:
            self.browser.close_page(page)
        before = len(self.proxy.requests)
        time.sleep(self.ctx.options.idle)
        new = self.proxy.requests[before:]
        self.record("services-on-no-server")
        hosts = sorted({h for _, _, h, _ in new})
        self.assertEqual(hosts, [], "hosts contacted with services on and no server set")


# A flat fill read back through getImageData: what Helium's canvas noise
# (helium/patches/helium/core/noise/canvas.patch) does to it. The pixels
# that differ from the drawn colour, each as [x, y, dr, dg, db, da], the
# two reads compared, and the alpha range.
NOISE_PROBE = """(() => {
  const c = document.createElement('canvas'); c.width = 64; c.height = 64;
  const k = c.getContext('2d', {willReadFrequently: true});
  k.fillStyle = 'rgb(100,100,100)'; k.fillRect(0, 0, 64, 64);
  const a = k.getImageData(0, 0, 64, 64).data;
  const b = k.getImageData(0, 0, 64, 64).data;
  const changed = [];
  let same_twice = true;
  for (let i = 0; i < a.length; i += 4) {
    const d = [a[i] - 100, a[i + 1] - 100, a[i + 2] - 100, a[i + 3] - 255];
    if (d.some(v => v !== 0)) changed.push([(i / 4) % 64, Math.floor(i / 4 / 64)].concat(d));
    for (let j = 0; j < 4; j++) if (a[i + j] !== b[i + j]) same_twice = false;
  }
  return {total: a.length / 4, changed: changed.length, same_twice,
          sample: changed.slice(0, 12), key: changed.map(e => e.slice(0, 2).join(',')).join(';')};
})()"""


def noise_problems(out):
    """What is wrong with a noised readback, as a list: every changed pixel
    must differ by one level in exactly one RGB channel, alpha untouched."""
    problems = []
    for x, y, dr, dg, db, da in out.get("sample", []):
        steps = [d for d in (dr, dg, db) if d]
        if len(steps) != 1 or abs(steps[0]) != 1 or da:
            problems.append(f"pixel ({x},{y}) moved by {dr},{dg},{db},{da}")
    return problems


class CanvasNoise(BrowserTest):
    """Helium's canvas fingerprinting noise (feature matrix P-FPR-04): a
    canvas readback carries sparse one-level noise by default, the same on
    every read in a session, different per site and chosen by the whole
    per-site token, and none with the feature off."""

    def read(self, browser, url):
        page = browser.new_page(url)
        try:
            return page.eval(NOISE_PROBE)
        finally:
            browser.close_page(page)

    def test_readback_carries_noise_by_default(self):
        """A flat fill reads back with some pixels one level off in one RGB
        channel (about one in four), alpha untouched, the same twice."""
        out = self.read(self.browser, self.ctx.fixtures().url("blank.html"))
        share = out["changed"] / out["total"]
        self.note(f"{out['changed']} of {out['total']} pixels changed ({share:.0%}); "
                  f"same on a second read: {out['same_twice']}; first: {out['sample'][:6]}")
        self.assertGreater(out["changed"], 0, "the readback was exact: no canvas noise")
        self.assertLess(share, 0.6, "most pixels changed; the noise is meant to be sparse")
        self.assertEqual(noise_problems(out), [], "noise outside one level in one channel")
        self.assertTrue(out["same_twice"], "two reads of the same canvas differed")

    FILL = (64, 64, (100, 100, 100, 255))  # what NOISE_PROBE draws and reads

    def old_hash_set(self, out):
        """Which of the four pixel sets of the hash before 0.20.3.17 this
        readback moved (0 to 3), or None for any other set."""
        return noise.old_set_of(noise.parse_key(out["key"]), *self.FILL)

    def test_moved_pixels_depend_on_the_whole_token(self):
        """Which pixels move is decided by the whole per-site token. Before
        0.20.3.17 two bits of it decided: a flat fill moved one of four
        pixel sets, the same four in every browser with Helium's noise
        (berytest/noise.py). The readback must be none of them."""
        out = self.read(self.browser, self.ctx.fixtures().url("blank.html"))
        which = self.old_hash_set(out)
        self.note(f"{out['changed']} pixels moved; "
                  + ("none of the four sets of the old hash" if which is None else
                     f"exactly set {which} of the four sets of the old hash"))
        self.assertGreater(out["changed"], 0, "the readback was exact: no canvas noise")
        self.assertIsNone(
            which, f"the moved pixels are set {which} of the four that the noise hash "
            "before 0.20.3.17 can produce: two bits of the site's token choose them "
            "(patches/privacy/beryllium-noise-hash-whole-token.patch changes this)")

    def test_noise_differs_per_site(self):
        """The same fill on another origin (localhost instead of 127.0.0.1,
        the same server) moves other pixels: the noise token is per site.
        Builds before 0.20.3.17 fail this in one session of four, whatever
        is reloaded, because two bits of the token choose the pixels; the
        failure says so when the pixels are one of those four sets."""
        base = self.ctx.fixtures().url("blank.html")
        first = self.read(self.browser, base)
        other = base.replace("127.0.0.1", "localhost")
        page = self.browser.new_page()
        try:
            try:
                page.navigate(other)
            except CDPError as e:
                if "browser connection closed" in str(e):
                    raise  # the browser died; that is not a missing localhost
                self.skipTest(f"localhost did not load: {e}")
            second = page.eval(NOISE_PROBE)
        finally:
            self.browser.close_page(page)
        same = second["key"] == first["key"]
        self.note(f"127.0.0.1: {first['changed']} pixels; localhost: {second['changed']} pixels, "
                  + ("the same pixels" if same else "other pixels"))
        self.assertGreater(second["changed"], 0, "no noise on the second origin")
        which = self.old_hash_set(first) if same else None
        self.assertFalse(
            same, "both origins moved the same pixels"
            + ("" if which is None else
               f": set {which} of the four sets of the noise hash before 0.20.3.17, "
               "which two origins share in one session of four"))

    def test_readback_is_exact_with_the_feature_off(self):
        """With --disable-features=HeliumNoiseCanvas the same fill reads back
        exactly (what the rendering group relies on)."""
        browser = Browser(self.ctx, "privacy-no-noise",
                          args=["--disable-features=HeliumNoiseCanvas"]).start()
        try:
            out = self.read(browser, self.ctx.fixtures().url("blank.html"))
        finally:
            browser.stop()
        self.assertEqual(out["changed"], 0, f"{out['changed']} pixels changed with the noise off: "
                         f"{out['sample'][:6]}")
