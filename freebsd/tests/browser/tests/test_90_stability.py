# SPDX-License-Identifier: GPL-3.0-only
"""Stability: many busy tabs at once, and quick navigation between
internal pages, without a crash."""

import time

from berytest.base import BrowserTest


class Stability(BrowserTest):
    def test_many_busy_tabs(self):
        """Eight animated tabs for ten seconds; no renderer crashes."""
        mark = self.browser.conn.mark()
        pages = [self.browser.new_page(self.ctx.fixtures().url("busy.html")) for _ in range(8)]
        time.sleep(10)
        for p in pages:
            self.assertEqual(p.eval("document.title"), "busy")
            self.browser.close_page(p)
        self.assertEqual(self.browser.crashes(mark), [])

    def test_rapid_internal_navigation(self):
        """Settings, history, downloads and others, one after another."""
        mark = self.browser.conn.mark()
        page = self.browser.new_page()
        for _ in range(3):
            for path in ("settings", "history", "downloads", "extensions", "version",
                         "settings/appearance", "gpu", "newtab"):
                page.navigate(self.url(path), timeout=30)
        self.assertEqual(self.browser.crashes(mark), [])
