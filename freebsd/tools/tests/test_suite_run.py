# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the browser suite's run script (freebsd/tests/browser/run):
the --lockdown shortcut and what a run says before its first test. Two
runs sent as lockdown runs on 10 November 2026 had only a render node
switch; the report said so in its header, the terminal did not."""

import importlib.machinery
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.abspath(os.path.join(HERE, "..", "..", "tests", "browser"))
sys.path.insert(0, SUITE)

loader = importlib.machinery.SourceFileLoader("suite_run", os.path.join(SUITE, "run"))
spec = importlib.util.spec_from_loader("suite_run", loader)
suite_run = importlib.util.module_from_spec(spec)
loader.exec_module(suite_run)

from berytest import capsicum  # noqa: E402

FEATURE = "BerylliumCapsicumRenderer"
NODE = "--render-node-override=/dev/dri/renderD128"


def options(*argv):
    return suite_run.options(list(argv) + ["--results", "/nonexistent/results"])


class Lockdown(unittest.TestCase):
    def test_shortcut_adds_the_switch(self):
        o = options("--lockdown")
        self.assertEqual(o.browser_args, [f"--enable-features={FEATURE}"])
        self.assertTrue(capsicum.lockdown_requested(o))

    def test_without_it_nothing_is_added(self):
        o = options(f"--browser-arg={NODE}")
        self.assertEqual(o.browser_args, [NODE])
        self.assertFalse(capsicum.lockdown_requested(o))

    def test_shortcut_keeps_other_switches(self):
        o = options("--lockdown", f"--browser-arg={NODE}")
        self.assertEqual(o.browser_args, [NODE, f"--enable-features={FEATURE}"])

    def test_shortcut_joins_an_enable_features_switch(self):
        # The browser reads only the last --enable-features switch.
        o = options("--lockdown", "--browser-arg=--enable-features=Other")
        self.assertEqual(o.browser_args, [f"--enable-features=Other,{FEATURE}"])
        self.assertTrue(capsicum.lockdown_requested(o))

    def test_shortcut_with_the_long_form_changes_nothing(self):
        o = options("--lockdown", f"--browser-arg=--enable-features={FEATURE}")
        self.assertEqual(o.browser_args, [f"--enable-features={FEATURE}"])


class StartLines(unittest.TestCase):
    def test_says_when_the_lockdown_is_not_requested(self):
        lines = suite_run.start_lines(options(f"--browser-arg={NODE}"), "1")
        self.assertEqual(lines[0], "Results: /nonexistent/results")
        self.assertIn("Renderer lockdown: not requested (add --lockdown for a lockdown run)",
                      lines)
        self.assertIn(f"Browser switches: {NODE}", lines)

    def test_says_when_it_is(self):
        lines = suite_run.start_lines(options("--lockdown"), "1")
        self.assertTrue(any(l.startswith("Renderer lockdown: requested") for l in lines))
        self.assertFalse(any("unprivileged_proc_debug" in l for l in lines))

    def test_warns_when_the_gate_cannot_read_the_renderers(self):
        lines = suite_run.start_lines(options("--lockdown"), "0")
        self.assertTrue(any("unprivileged_proc_debug is 0" in l for l in lines))

    def test_no_warning_without_the_lockdown_or_the_sysctl(self):
        self.assertFalse(any("unprivileged_proc_debug" in l
                             for l in suite_run.start_lines(options(), "0")))
        self.assertFalse(any("unprivileged_proc_debug" in l
                             for l in suite_run.start_lines(options("--lockdown"), None)))

    def test_no_switch_line_without_switches(self):
        self.assertFalse(any(l.startswith("Browser switches")
                             for l in suite_run.start_lines(options(), None)))


if __name__ == "__main__":
    unittest.main()
