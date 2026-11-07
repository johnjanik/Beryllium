# SPDX-License-Identifier: GPL-3.0-only
"""The sandbox tests as a gate (plan/16 BER-04).

freebsd/tests/browser/tests/test_50_sandbox.py surveys when the browser runs
with its defaults (no process confined) and must fail, not skip or pass, on
anything short of complete confinement when the run requests the lockdown
(--browser-arg=--enable-features=BerylliumCapsicumRenderer). These tests
run its methods against controlled observations: the three scenarios of
the adversarial review of 7 November 2026 (every renderer unconfined, one
confined and one not, rights unreadable for one renderer) and a few more.
"""

import argparse
import importlib.util
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUITE = os.path.join(REPO, "freebsd", "tests", "browser")
sys.path.insert(0, SUITE)

spec = importlib.util.spec_from_file_location(
    "test_50_sandbox", os.path.join(SUITE, "tests", "test_50_sandbox.py"))
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)

LOCKDOWN = ["--enable-features=BerylliumCapsicumRenderer"]
RIGHTS_OK = {"10": {"type": "h", "rights": ["rd", "wr", "se", "mm", "fs", "fc"], "name": ""}}


def case(method, browser_args, processes):
    """A SandboxHonesty test case wired to fake observations."""
    t = sandbox.SandboxHonesty(method)
    t.browser = mock.Mock()
    t.browser.conn.send.return_value = {"processInfo": processes}
    t.ctx = mock.Mock()
    t.ctx.options = argparse.Namespace(browser_args=list(browser_args))
    return t


def modes(by_pid):
    return mock.patch.object(sandbox, "capability_mode", side_effect=lambda pid: by_pid.get(pid))


RENDERERS = [{"type": "browser", "id": 1}, {"type": "renderer", "id": 2},
             {"type": "renderer", "id": 3}]


class CapabilityModeTest(unittest.TestCase):
    def run_case(self, browser_args, by_pid):
        t = case("test_capability_mode_per_process", browser_args, RENDERERS)
        with modes(by_pid):
            t.test_capability_mode_per_process()

    def test_survey_records_an_unconfined_default(self):
        self.run_case([], {1: False, 2: False, 3: False})

    def test_gate_fails_when_every_renderer_is_unconfined(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(LOCKDOWN, {1: False, 2: False, 3: False})
        self.assertIn("[2, 3]", str(e.exception))

    def test_gate_fails_on_one_unconfined_renderer(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(LOCKDOWN, {1: False, 2: True, 3: False})
        self.assertIn("[3]", str(e.exception))

    def test_gate_fails_on_an_unreadable_renderer(self):
        with self.assertRaises(AssertionError):
            self.run_case(LOCKDOWN, {1: False, 2: True, 3: None})

    def test_gate_fails_without_any_answer(self):
        with self.assertRaises(AssertionError):
            self.run_case(LOCKDOWN, {})

    def test_survey_skips_without_any_answer(self):
        with self.assertRaises(unittest.SkipTest):
            self.run_case([], {})

    def test_gate_passes_when_every_renderer_is_confined(self):
        self.run_case(LOCKDOWN, {1: False, 2: True, 3: True})


class PolicyTest(unittest.TestCase):
    def run_case(self, browser_args, by_pid, rights_by_pid, problems=()):
        t = case("test_confined_renderer_descriptors_follow_the_policy", browser_args, RENDERERS)
        with modes(by_pid), \
                mock.patch.object(sandbox.capsicum, "descriptors", return_value=[]), \
                mock.patch.object(sandbox.capsicum, "rights",
                                  side_effect=lambda pid: rights_by_pid.get(pid, {})), \
                mock.patch.object(sandbox.capsicum, "policy_problems", return_value=list(problems)):
            t.test_confined_renderer_descriptors_follow_the_policy()

    def test_survey_skips_when_nothing_is_confined(self):
        with self.assertRaises(unittest.SkipTest):
            self.run_case([], {2: False, 3: False}, {})

    def test_gate_fails_when_nothing_is_confined(self):
        with self.assertRaises(AssertionError):
            self.run_case(LOCKDOWN, {2: False, 3: False}, {})

    def test_survey_inspects_the_confined_renderer_only(self):
        self.run_case([], {2: True, 3: False}, {2: RIGHTS_OK})

    def test_gate_fails_on_a_mixed_set(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(LOCKDOWN, {2: True, 3: False}, {2: RIGHTS_OK, 3: RIGHTS_OK})
        self.assertIn("[3]", str(e.exception))

    def test_survey_tolerates_one_unreadable_renderer(self):
        self.run_case([], {2: True, 3: True}, {2: RIGHTS_OK})

    def test_gate_fails_on_one_unreadable_renderer(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(LOCKDOWN, {2: True, 3: True}, {2: RIGHTS_OK})
        self.assertIn("unreadable for renderers [3]", str(e.exception))

    def test_gate_fails_when_no_renderer_is_readable(self):
        with self.assertRaises(AssertionError):
            self.run_case(LOCKDOWN, {2: True, 3: True}, {})

    def test_survey_skips_when_no_renderer_is_readable(self):
        with self.assertRaises(unittest.SkipTest):
            self.run_case([], {2: True, 3: True}, {})

    def test_policy_problems_fail_either_way(self):
        for args in ([], LOCKDOWN):
            with self.assertRaises(AssertionError) as e:
                self.run_case(args, {2: True, 3: True}, {2: RIGHTS_OK, 3: RIGHTS_OK},
                              problems=["fd 7: socket has cd"])
            self.assertIn("fd 7", str(e.exception))

    def test_gate_passes_when_every_renderer_is_confined_and_clean(self):
        self.run_case(LOCKDOWN, {2: True, 3: True}, {2: RIGHTS_OK, 3: RIGHTS_OK})


if __name__ == "__main__":
    unittest.main()
