# SPDX-License-Identifier: GPL-3.0-only
"""Stability: many busy tabs at once, and quick navigation between
internal pages, without a crash."""

import time

from berytest import capsicum
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

    def test_renderers_idle_without_spinning(self):
        """A renderer showing a static page uses almost no CPU over five
        seconds. (0.20.3.8's renderer lockdown left every renderer spinning
        in epoll-shim's poll loop while the rest of the suite passed.)"""
        page = self.browser.new_page(self.ctx.fixtures().url("blank.html"))
        time.sleep(2)  # let start-up work finish
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        before = {p["id"]: capsicum.cpu_seconds(p["id"]) for p in procs}
        time.sleep(5)
        lines, busy = [], []
        for p in procs:
            after = capsicum.cpu_seconds(p["id"])
            if before[p["id"]] is None or after is None:
                continue
            used = after - before[p["id"]]
            lines.append(f"{p['type']:<10} pid {p['id']:<7} {used:.2f} s of CPU in 5 s")
            if p["type"] == "renderer" and used > 1.0:
                busy.append(lines[-1])
        self.browser.close_page(page)
        if not lines:
            self.skipTest("ps reports no CPU time")
        self.note("\n".join(lines))
        self.assertEqual(busy, [], "renderers use CPU while idle")
