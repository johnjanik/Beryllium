# SPDX-License-Identifier: GPL-3.0-only
"""Startup, identity, and where the browser keeps its files."""

import os
import time

from berytest.base import BrowserTest


class Startup(BrowserTest):
    def test_starts_and_answers(self):
        """The browser starts and answers over DevTools."""
        product = self.browser.product()
        self.assertRegex(product, r"^(Headless)?Chrome/\d+\.")
        self.note(f"product {product}\nuser agent {self.browser.version.get('userAgent')}")

    def test_version_page_names_beryllium(self):
        """The version page names Beryllium, not Helium."""
        page = self.browser.new_page(self.url("version"))
        text = page.text()
        self.assertContains(text, "Beryllium")
        self.assertLacks(text, "Helium")

    def test_profile_and_cache_are_berylliums_own(self):
        """The profile is ~/.config/beryllium; nothing goes to Chromium's folders."""
        page = self.browser.new_page(self.url("version"))
        self.assertContains(page.text(), "/.config/beryllium/")
        home = self.browser.home
        self.assertTrue(os.path.isdir(os.path.join(home, ".config", "beryllium")))
        for other in (".config/chromium", ".cache/chromium", ".config/helium"):
            self.assertFalse(os.path.exists(os.path.join(home, other)),
                             f"~/{other} was created")

    def test_beryllium_scheme_opens_internal_pages(self):
        """beryllium://version opens the version page (browser navigation maps it
        to chrome://; DevTools' new-tab command goes through that navigation)."""
        conn = self.browser.conn
        tid = conn.send("Target.createTarget", {"url": "beryllium://version"})["targetId"]
        try:
            sid = conn.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            from berytest.cdp import Page
            page = Page(conn, tid, sid)
            for _ in range(40):
                href = page.eval("location.href")
                if href and href != "about:blank":
                    break
                time.sleep(0.25)
            self.assertTrue(href.startswith("chrome://version"), f"opened {href!r}")
            self.assertContains(page.text(), "Beryllium")
        finally:
            conn.send("Target.closeTarget", {"targetId": tid})
