# SPDX-License-Identifier: GPL-3.0-only
"""Startup, identity, and where the browser keeps its files."""

import os

from berytest.base import BrowserTest


class Startup(BrowserTest):
    def test_starts_and_answers(self):
        """The browser starts and answers over DevTools."""
        product = self.browser.product()
        self.assertRegex(product, r"^(Headless)?Chrome/\d+\.")
        self.note(f"product {product}\nuser agent {self.browser.version.get('userAgent')}")

    def test_version_page_names_beryllium(self):
        """beryllium://version names Beryllium, not Helium."""
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
