# SPDX-License-Identifier: GPL-3.0-only
"""Privacy (plan/07 section 6): a fresh browser left alone, or showing a
local page, contacts no outside host, and online services stay silent
until the user sets a server (feature matrix P-SVC-01). All traffic goes
through a local recording proxy that refuses every connection, so nothing
leaves the machine; the proxy's list of requested hosts is the result."""

import json
import time

from berytest.base import BrowserTest
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
