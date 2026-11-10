# SPDX-License-Identifier: GPL-3.0-only
"""Tests for what the browser suite says when the browser process ends
under a test (freebsd/tests/browser/berytest: browser.py, cdp.py, base.py).
The 0.20.3.16 run on the Intel render node (10 November 2026) had 21
errors that said only "browser connection closed"."""

import os
import signal
import sys
import tempfile
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests", "browser"))
from berytest import base, browser, cdp  # noqa: E402


class DescribeExit(unittest.TestCase):
    def test_running(self):
        self.assertIsNone(browser.describe_exit(None))

    def test_exit_status(self):
        self.assertEqual(browser.describe_exit(0), "exited with status 0")
        self.assertEqual(browser.describe_exit(1), "exited with status 1")

    def test_signal(self):
        self.assertEqual(browser.describe_exit(-signal.SIGSEGV),
                         f"was killed by signal {int(signal.SIGSEGV)} (SIGSEGV)")
        self.assertEqual(browser.describe_exit(-signal.SIGABRT),
                         f"was killed by signal {int(signal.SIGABRT)} (SIGABRT)")

    def test_unknown_signal(self):
        self.assertEqual(browser.describe_exit(-250), "was killed by signal 250 (unknown)")


LOG = """\
[100:100:1110/163102.1:WARNING:chrome/browser/x.cc:1] something ordinary
[100:100:1110/163102.2:INFO:y.cc:2] hello
[101:101:1110/163102.3:ERROR:ui/ozone/platform/wayland/host/z.cc:3] a wl_buffer could not be made
[100:100:1110/163102.4:FATAL:content/browser/gpu/gpu_data_manager_impl_private.cc:448] GPU process isn't usable. Goodbye.
#0 0x000001234567 (/usr/local/share/beryllium/beryllium+0x1234566)
#1 0x000001234568 (/usr/local/share/beryllium/beryllium+0x1234567)
  r8: 000000007fffffef  r9: 00000000ffffffed r10: 00000000ffffffec r11: 0000000000000000
 r12: fffffffc00000000 r13: 000024b4043498a8 r14: 000024b4044dd3c0 r15: 0000000000000000
  di: 000024b4044dd100  si: 00000000000000cd  bp: 00007fff3856ece0  bx: 000024b4044dd100
[end of stack trace]

"""


class TellingLines(unittest.TestCase):
    def test_keeps_what_says_why_and_drops_the_stack(self):
        lines = browser.telling_lines(LOG.splitlines())
        self.assertEqual(len(lines), 2)
        self.assertIn("wl_buffer", lines[0])
        self.assertIn("Goodbye", lines[1])

    def test_falls_back_to_the_last_lines_that_are_not_frames(self):
        quiet = ["one", "two", "#0 0x01 (bin+0x1)", "  ip: 0000562928adbb7a efl: 0", "three"]
        self.assertEqual(browser.telling_lines(quiet, limit=2), ["two", "three"])

    def test_limit_and_length(self):
        many = [f"[1:1:ERROR:a.cc:1] {'x' * 500} {i}" for i in range(30)]
        lines = browser.telling_lines(many, limit=5)
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(len(l) <= 300 for l in lines))

    def test_empty(self):
        self.assertEqual(browser.telling_lines([]), [])


class KernelLines(unittest.TestCase):
    def test_finds_the_process(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write("Nov 10 16:31:02 zen kernel: pid 78526 (beryllium), jid 0, uid 1001: "
                    "exited on signal 6 (core dumped)\n"
                    "Nov 10 16:31:03 zen kernel: pid 7852 (other), jid 0, uid 1001: "
                    "exited on signal 11\n")
            path = f.name
        try:
            self.assertEqual(len(browser.kernel_lines(78526, path)), 1)
            self.assertIn("signal 6", browser.kernel_lines(78526, path)[0])
            # pid 7852 is not a prefix match of 78526
            self.assertIn("signal 11", browser.kernel_lines(7852, path)[0])
            self.assertEqual(browser.kernel_lines(1, path), [])
        finally:
            os.unlink(path)

    def test_unreadable_log(self):
        self.assertEqual(browser.kernel_lines(1, "/nonexistent/messages"), [])


def closed_connection(why=None):
    """A Connection whose browser end is already closed."""
    r, w = os.pipe()
    r2, w2 = os.pipe()
    os.close(w)       # the reader sees end of file at once
    os.close(r2)      # writing to the browser fails with EPIPE
    conn = cdp.Connection(r, w2)
    conn.why_closed = why
    for _ in range(100):  # the reader thread notices within a moment
        if conn.closed:
            break
        time.sleep(0.02)
    return conn


class ClosedConnection(unittest.TestCase):
    def test_send_says_how_the_browser_ended(self):
        conn = closed_connection(lambda: "the browser process (pid 5) exited with status 1")
        try:
            with self.assertRaises(cdp.CDPError) as caught:
                conn.send("Target.createTarget", {"url": "about:blank"})
        finally:
            conn.close()
        text = str(caught.exception)
        self.assertIn("Target.createTarget: browser connection closed", text)
        self.assertIn("exited with status 1", text)

    def test_wait_event_says_how_the_browser_ended(self):
        conn = closed_connection(lambda: "the browser process (pid 5) was killed by signal 11")
        try:
            with self.assertRaises(cdp.CDPError) as caught:
                conn.wait_event("Page.loadEventFired", timeout=5)
        finally:
            conn.close()
        self.assertIn("waiting for Page.loadEventFired: browser connection closed; "
                      "the browser process (pid 5) was killed by signal 11", str(caught.exception))

    def test_without_an_owner_the_message_is_as_before(self):
        conn = closed_connection()
        try:
            with self.assertRaises(cdp.CDPError) as caught:
                conn.wait_event("Page.loadEventFired", timeout=5)
        finally:
            conn.close()
        self.assertEqual(str(caught.exception),
                         "waiting for Page.loadEventFired: browser connection closed")

    def test_a_failing_description_does_not_hide_the_error(self):
        def broken():
            raise OSError("no log")
        conn = closed_connection(broken)
        try:
            with self.assertRaises(cdp.CDPError) as caught:
                conn.wait_event("Page.loadEventFired", timeout=5)
        finally:
            conn.close()
        self.assertIn("browser connection closed", str(caught.exception))
        self.assertIn("could not be read", str(caught.exception))


class FakeProc:
    def __init__(self, status, pid=4242):
        self.status, self.pid = status, pid

    def poll(self):
        return self.status

    def wait(self, timeout=None):
        return self.status


def fake_browser(status, log_text):
    b = browser.Browser.__new__(browser.Browser)
    b.proc = FakeProc(status)
    b._stopping = False
    b._death_told = False
    f = tempfile.NamedTemporaryFile("w", suffix=".stderr.log", delete=False)
    f.write(log_text)
    f.close()
    b.log_path = f.name
    return b


class Death(unittest.TestCase):
    def setUp(self):
        self.browser = fake_browser(-signal.SIGABRT, LOG)
        self.addCleanup(os.unlink, self.browser.log_path)

    def test_ended(self):
        self.assertIn("SIGABRT", self.browser.ended())
        self.assertIsNone(fake_browser_running().ended())

    def test_first_report_carries_the_log_and_later_ones_do_not(self):
        with unittest.mock.patch.object(browser, "kernel_lines", return_value=[]):
            first = self.browser.death()
            second = self.browser.death()
        self.assertIn("pid 4242", first)
        self.assertIn("SIGABRT", first)
        self.assertIn("Goodbye", first)
        self.assertIn(os.path.basename(self.browser.log_path), first)
        self.assertIn("SIGABRT", second)
        self.assertNotIn("Goodbye", second)
        self.assertIn("earlier test", second)

    def test_kernel_line_is_included(self):
        with unittest.mock.patch.object(browser, "kernel_lines",
                                        return_value=["pid 4242 (beryllium): exited on signal 6"]):
            self.assertIn("kernel: pid 4242 (beryllium): exited on signal 6",
                          self.browser.death())

    def test_nothing_to_say_while_the_suite_stops_the_browser(self):
        self.browser._stopping = True
        self.assertEqual(self.browser.death(), "")

    def test_death_note(self):
        with unittest.mock.patch.object(browser, "kernel_lines", return_value=[]):
            note = self.browser.death_note()
        self.assertIn("was killed by signal", note)
        self.assertIn("no line about it", note)
        self.assertIn("Goodbye", note)


def fake_browser_running():
    b = browser.Browser.__new__(browser.Browser)
    b.proc = FakeProc(None)
    return b


class AlreadyReported(unittest.TestCase):
    """base.BrowserTest.already_reported reads the result's own lists."""

    def run_case(self, body):
        seen = {}

        class Case(base.BrowserTest):
            browser = None

            @classmethod
            def setUpClass(cls):
                pass

            @classmethod
            def tearDownClass(cls):
                pass

            def tearDown(self):
                seen["reported"] = self.already_reported()

            def test_it(self):
                body(self)

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(Case).run(result)
        return seen["reported"]

    def test_passing(self):
        self.assertFalse(self.run_case(lambda case: None))

    def test_error(self):
        def body(case):
            raise RuntimeError("x")
        self.assertTrue(self.run_case(body))

    def test_failure(self):
        self.assertTrue(self.run_case(lambda case: case.fail("x")))

    def test_skip(self):
        self.assertTrue(self.run_case(lambda case: case.skipTest("x")))


if __name__ == "__main__":
    unittest.main()
