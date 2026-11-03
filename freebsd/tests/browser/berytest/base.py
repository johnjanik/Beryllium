# SPDX-License-Identifier: GPL-3.0-only
"""Test case base: one browser per test class, crash checks after each test."""

import unittest

from . import context
from .browser import Browser, has_display


class BrowserTest(unittest.TestCase):
    """Subclasses may set BROWSER_ARGS, HEADLESS (None: run default),
    NEEDS_DISPLAY, NEEDS_FREEBSD, NEEDS_NETWORK, USER_DATA_DIR and PREFS."""

    BROWSER_ARGS = ()
    HEADLESS = None
    NEEDS_DISPLAY = False
    NEEDS_FREEBSD = False
    NEEDS_NETWORK = False
    USER_DATA_DIR = False
    PREFS = None
    browser = None

    @classmethod
    def setUpClass(cls):
        cls.ctx = context.get()
        opts = cls.ctx.options
        if cls.NEEDS_NETWORK and not opts.network:
            raise unittest.SkipTest("needs the network; run with --network")
        if cls.NEEDS_FREEBSD and not cls.ctx.is_freebsd():
            raise unittest.SkipTest("FreeBSD only")
        headless = opts.headless if cls.HEADLESS is None else cls.HEADLESS
        if cls.NEEDS_DISPLAY and (headless or not has_display()):
            raise unittest.SkipTest("needs a desktop session (not --headless)")
        cls.browser = Browser(cls.ctx, cls.__name__, args=cls.extra_args(),
                              headless=headless, user_data_dir=cls.USER_DATA_DIR,
                              prefs=cls.PREFS).start()
        if not getattr(cls.ctx, "browser_version", None):
            cls.ctx.browser_version = cls.browser.version

    @classmethod
    def extra_args(cls):
        return list(cls.BROWSER_ARGS)

    @classmethod
    def tearDownClass(cls):
        if cls.browser:
            cls.browser.stop()

    def setUp(self):
        self._crash_mark = self.browser.conn.mark() if self.browser else 0

    def tearDown(self):
        if not self.browser:
            return
        crashes = self.browser.crashes(self._crash_mark)
        if crashes:
            details = ", ".join(f"status={c.get('status')} error code={c.get('errorCode')}"
                                for c in crashes)
            self.ctx.note(self.id(), f"renderer crash during the test: {details}\n"
                          f"browser log tail:\n{self.browser.log_tail(25)}")

    def url(self, path):
        return self.browser.url(path)

    def kernel_crash_log(self):
        """FreeBSD logs "pid N (name), ... exited on signal S" for crashes."""
        try:
            with open("/var/log/messages", errors="replace") as f:
                lines = [l.rstrip() for l in f if "exited on signal" in l]
            return "\n".join(lines[-5:])
        except OSError:
            return ""

    def note(self, text):
        self.ctx.note(self.id(), text)

    def assertContains(self, text, needle, what="page"):
        if needle not in text:
            self.fail(f"{what} does not contain {needle!r}; it starts: {text[:300]!r}")

    def assertLacks(self, text, needle, what="page"):
        if needle in text:
            i = text.index(needle)
            self.fail(f"{what} contains {needle!r}: ...{text[max(0, i - 80):i + 80]!r}...")
