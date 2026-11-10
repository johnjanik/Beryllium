# SPDX-License-Identifier: GPL-3.0-only
"""Test case base: one browser per test class, crash checks after each test."""

import os
import unittest

from . import context, cores
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
        cls._headless = headless
        cls._restarts = 0
        cls.browser = cls.new_browser(cls.__name__)
        cls.browser.record_version()

    @classmethod
    def new_browser(cls, name):
        return Browser(cls.ctx, name, args=cls.extra_args(), headless=cls._headless,
                       user_data_dir=cls.USER_DATA_DIR, prefs=cls.PREFS).start()

    @classmethod
    def extra_args(cls):
        return list(cls.BROWSER_ARGS)

    @classmethod
    def tearDownClass(cls):
        if cls.browser:
            cls.browser.stop()

    def setUp(self):
        cls = type(self)
        dead = bool(self.browser) and bool(self.browser.ended() or self.browser.conn.closed)
        if dead or (self.browser is None and getattr(cls, "_restarts", 0)):
            # The class's browser died in an earlier test (noted there). One
            # death is one finding; the tests after it get a new browser, with
            # its own log, so each shows what it does to a fresh process. If
            # the new one does not start, this test fails saying so and the
            # next one tries again.
            if dead:
                cls._last_end = (self.browser.ended()
                                 or "closed its debugging pipe and kept running")
                self.browser.stop()
            cls._restarts += 1
            cls.browser = None
            cls.browser = cls.new_browser(f"{cls.__name__}-{cls._restarts + 1}")
            self.note(f"the browser of the test before {cls._last_end}; this test runs in "
                      f"a new one ({os.path.basename(cls.browser.log_path)})")
        self._crash_mark = self.browser.conn.mark() if self.browser else 0

    def tearDown(self):
        if not self.browser:
            return
        self.check_browser_alive()
        crashes = self.browser.crashes(self._crash_mark)
        if crashes:
            details = ", ".join(f"status={c.get('status')} error code={c.get('errorCode')}"
                                for c in crashes)
            self.ctx.note(self.id(), f"renderer crash during the test: {details}\n"
                          f"browser log tail:\n{self.browser.log_tail(25)}")
            self.collect_cores()

    def check_browser_alive(self):
        """A browser process that ended during the test is noted with how it
        ended, and fails a test that would otherwise pass (one that only
        waits and counts connections passes over a dead browser too)."""
        how = self.browser.ended()
        if not how:
            return
        self.note(self.browser.death_note() + "\nduring this test")
        self.collect_cores()
        if not self.already_reported():
            self.fail(f"the browser process {how} during the test")

    def already_reported(self):
        """Whether this test already has an error, failure or skip recorded.
        (unittest resets its own success flag for tearDown, so the result's
        lists are the place to look.)"""
        result = getattr(getattr(self, "_outcome", None), "result", None)
        if result is None:
            return False
        recorded = list(result.errors) + list(result.failures) + list(result.skipped)
        return any(test is self for test, _ in recorded)

    def collect_cores(self):
        """With --cores: backtraces of new core dumps, saved and noted."""
        if not self.browser.core_dir:
            return
        import time
        time.sleep(2)  # the kernel finishes writing the core
        seen = getattr(self.ctx, "cores_seen", set())
        self.ctx.cores_seen = seen
        new = [c for c in cores.find(self.browser.core_dir, self.browser.started_at)
               if c not in seen]
        if not new:
            self.note("no core file was written; check kern.coredump=1 and kern.corefile "
                      "(sysctl kern.corefile=/var/tmp/%N.%P.core), then rerun with --cores")
            return
        for core in new:
            seen.add(core)
            bt = cores.backtrace(self.browser.binary, core)
            name = f"backtrace-{self.id().split('.')[-1]}-{os.path.basename(core)}.txt"
            with open(self.ctx.artifact(name), "w") as f:
                f.write(f"core {core}\nbinary {self.browser.binary}\n\n{bt}\n")
            self.note(f"core {core}; backtrace in {name}:\n" + "\n".join(bt.splitlines()[:30]))

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
