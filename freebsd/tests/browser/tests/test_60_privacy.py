# SPDX-License-Identifier: GPL-3.0-only
"""Privacy (plan/07 section 6): a fresh browser left alone, or showing a
local page, contacts no outside host. All traffic goes through a local
recording proxy that refuses every connection, so nothing leaves the
machine; the proxy's list of requested hosts is the result."""

import time

from berytest.base import BrowserTest
from berytest.servers import RecordingProxy


class QuietWhenIdle(BrowserTest):
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
