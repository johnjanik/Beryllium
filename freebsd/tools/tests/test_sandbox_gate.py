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


def case(method, browser_args, processes, grace=0):
    """A SandboxHonesty test case wired to fake observations."""
    t = sandbox.SandboxHonesty(method)
    t.GRACE_SECONDS = grace
    t.browser = mock.Mock()
    t.browser.conn.send.return_value = {"processInfo": processes}
    t.browser.log_lines.return_value = []
    t.ctx = mock.Mock()
    t.ctx.options = argparse.Namespace(browser_args=list(browser_args))
    return t


class modes:
    """Patches the kernel's answers: by_pid maps a pid to its capability mode,
    or to a list of answers given in turn (the last one repeats). Processes
    not listed are gone. Time is simulated so a grace period costs nothing."""

    def __init__(self, by_pid):
        self.by_pid = {pid: list(v) if isinstance(v, list) else [v] for pid, v in by_pid.items()}
        self.clock = 0.0

    def answer(self, pid):
        answers = self.by_pid.get(pid, [None])
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def __enter__(self):
        c = sandbox.capsicum
        self.patches = [
            mock.patch.object(sandbox, "capability_mode", side_effect=self.answer),
            mock.patch.object(c, "capability_mode", side_effect=self.answer),
            mock.patch.object(c, "process_alive", side_effect=lambda pid: pid in self.by_pid),
            mock.patch.object(c, "_clock", side_effect=lambda: self.clock),
            mock.patch.object(c, "_sleep", side_effect=self.advance),
        ]
        for p in self.patches:
            p.start()
        return self

    def advance(self, seconds):
        self.clock += seconds

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


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
        self.assertIn("2: 'not in capability mode', 3: 'not in capability mode'", str(e.exception))

    def test_gate_fails_on_one_unconfined_renderer(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(LOCKDOWN, {1: False, 2: True, 3: False})
        self.assertIn("{3: 'not in capability mode'}", str(e.exception))

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

    def test_gate_waits_for_a_renderer_that_is_still_starting(self):
        """The browser lists a renderer before it reaches its lockdown point."""
        t = case("test_capability_mode_per_process", LOCKDOWN, RENDERERS, grace=5.0)
        with modes({1: False, 2: True, 3: [False, False, True]}) as m:
            t.test_capability_mode_per_process()
        self.assertGreater(m.clock, 0)
        self.assertLess(m.clock, 5.0)

    def test_gate_fails_on_a_renderer_still_unconfined_after_the_grace(self):
        t = case("test_capability_mode_per_process", LOCKDOWN, RENDERERS, grace=5.0)
        with modes({1: False, 2: True, 3: False}) as m, self.assertRaises(AssertionError) as e:
            t.test_capability_mode_per_process()
        self.assertAlmostEqual(m.clock, 5.0, places=3)
        self.assertIn("3: 'not in capability mode'", str(e.exception))

    def test_gate_ignores_a_renderer_that_ended(self):
        t = case("test_capability_mode_per_process", LOCKDOWN, RENDERERS, grace=1.0)
        with modes({1: False, 2: True}):  # 3 is gone: procstat answers nothing
            t.test_capability_mode_per_process()

    def test_gate_fails_on_a_live_unreadable_renderer(self):
        t = case("test_capability_mode_per_process", LOCKDOWN, RENDERERS, grace=1.0)
        with modes({1: False, 2: True, 3: None}), self.assertRaises(AssertionError) as e:
            t.test_capability_mode_per_process()
        self.assertIn("3: 'unreadable'", str(e.exception))


class PolicyTest(unittest.TestCase):
    def run_case(self, browser_args, by_pid, rights_by_pid, problems=()):
        t = case("test_confined_renderer_descriptors_follow_the_policy", browser_args, RENDERERS)
        with modes(by_pid), \
                mock.patch.object(sandbox.capsicum, "descriptors", return_value=[]), \
                mock.patch.object(sandbox.capsicum, "socket_peers", return_value={}), \
                mock.patch.object(sandbox.capsicum, "threads", return_value=[]), \
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
        self.assertIn("{3: 'not in capability mode'}", str(e.exception))

    def test_survey_tolerates_one_unreadable_renderer(self):
        self.run_case([], {2: True, 3: True}, {2: RIGHTS_OK})

    def test_gate_fails_on_one_unreadable_renderer(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(LOCKDOWN, {2: True, 3: True}, {2: RIGHTS_OK})
        self.assertIn("unreadable for renderers [3]", str(e.exception))

    def test_gate_ignores_a_confined_renderer_that_ended_before_it_was_read(self):
        """modes() answers True for 3 but it is gone when its descriptors are read."""
        t = case("test_confined_renderer_descriptors_follow_the_policy", LOCKDOWN, RENDERERS)
        with modes({1: False, 2: True, 3: True}), \
                mock.patch.object(sandbox.capsicum, "process_alive", side_effect=lambda pid: pid != 3), \
                mock.patch.object(sandbox.capsicum, "descriptors", return_value=[]), \
                mock.patch.object(sandbox.capsicum, "socket_peers", return_value={}), \
                mock.patch.object(sandbox.capsicum, "threads", return_value=[]), \
                mock.patch.object(sandbox.capsicum, "rights",
                                  side_effect=lambda pid: RIGHTS_OK if pid == 2 else {}), \
                mock.patch.object(sandbox.capsicum, "policy_problems", return_value=[]):
            t.test_confined_renderer_descriptors_follow_the_policy()
        self.assertIn("ended before they were read: [3]", t.ctx.note.call_args[0][1])

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

    def test_unlimited_sockets_say_where_they_lead(self):
        t = case("test_confined_renderer_descriptors_follow_the_policy", LOCKDOWN, RENDERERS)
        rights = {"13": {"type": "s", "rights": sorted(sandbox.capsicum.UNLIMITED_MARKERS | {"rd"}),
                         "name": ""}}
        socks = {2: {"13": {"domain": "local", "type": "stream", "pcb": "a13", "peer": "b88",
                            "conn": "<->"}},
                 1: {"88": {"domain": "local", "type": "stream", "pcb": "b88", "peer": "a13",
                            "conn": "<->"}}}
        with modes({1: False, 2: True, 3: True}), \
                mock.patch.object(sandbox.capsicum, "descriptors", return_value=[]), \
                mock.patch.object(sandbox.capsicum, "socket_peers",
                                  side_effect=lambda pid: socks.get(pid, {})), \
                mock.patch.object(sandbox.capsicum, "threads", return_value=[
                    {"tid": "1", "name": "ThreadPoolForeg", "state": "sleep", "wchan": "sbwait"}]), \
                mock.patch.object(sandbox.capsicum, "rights",
                                  side_effect=lambda pid: rights if pid == 2 else RIGHTS_OK), \
                self.assertRaises(AssertionError):
            t.test_confined_renderer_descriptors_follow_the_policy()
        noted = t.ctx.note.call_args[0][1]
        self.assertIn("fd 13: socket with every right: unix stream, other end: browser pid 1 fd 88",
                      noted)
        self.assertIn("threads waiting on a socket: ThreadPoolForeg", noted)
        self.assertIn("fd 13 (s): rights not limited", noted)


class LogTest(unittest.TestCase):
    def run_case(self, browser_args, lines):
        t = case("test_lockdown_log", browser_args, RENDERERS)
        t.browser.log_lines.return_value = list(lines)
        t.test_lockdown_log()

    LOCKED = "[1:1:1107/000000.000000:WARNING:sandbox_freebsd.cc(400)] beryllium-sandbox: renderer pid=2 capability_mode=1 closed_directories=0 limited=12"
    RECEIVED = "[2:5:1107/000000.000000:ERROR:capsicum_rights.cc(330)] beryllium-sandbox: received device (fd 40), which a confined process may not hold: every right removed"

    def test_gate_needs_lockdown_reports(self):
        with self.assertRaises(AssertionError):
            self.run_case(LOCKDOWN, [])
        self.run_case(LOCKDOWN, [self.LOCKED])

    def test_gate_fails_on_a_received_descriptor_outside_the_policy(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(LOCKDOWN, [self.LOCKED, self.RECEIVED])
        self.assertIn("received descriptors outside the policy", str(e.exception))

    def test_survey_only_records(self):
        self.run_case([], [])
        self.run_case([], [self.RECEIVED])


if __name__ == "__main__":
    unittest.main()
