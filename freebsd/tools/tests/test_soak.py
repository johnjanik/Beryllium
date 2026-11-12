# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the browser suite's repeat mode, ledger and tally
(freebsd/tests/browser/berytest/soak.py and the run script's use of it).

The tally decides when the renderer lockdown may become the default
(plan/18 section 3.2), so what counts and what resets the count is pinned
down here."""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.abspath(os.path.join(HERE, "..", "..", "tests", "browser"))
sys.path.insert(0, SUITE)

from berytest import soak  # noqa: E402

loader = importlib.machinery.SourceFileLoader("suite_run_for_soak", os.path.join(SUITE, "run"))
spec = importlib.util.spec_from_loader("suite_run_for_soak", loader)
suite_run = importlib.util.module_from_spec(spec)
loader.exec_module(suite_run)


def entry(outcome=soak.CLEAN, package="beryllium-0.20.3.18", boot=100, lockdown=True,
          whole=True, headless=False, started="2026-11-12 01:00:00", gate=soak.GATE):
    made = {"started": started, "seconds": 190, "boot": boot, "package": package,
            "lockdown": lockdown, "whole": whole, "headless": headless, "outcome": outcome,
            "counts": {}, "results": "/r",
            "not_passed": [] if outcome == soak.CLEAN else ["fail tests.test_50_sandbox.X.test_y"]}
    if gate is not None:   # None: a line written before the ledger had the mark
        made["gate"] = gate
    return made


REPORT = {
    "started": "2026-11-12 01:00:00", "seconds": 189,
    "info": {"beryllium_package": "beryllium-0.20.3.18",
             "renderer_lockdown": "requested (the sandbox tests are a gate)"},
    "options": {"groups": [], "headless": False},
    "results": [{"test": "tests.test_10_startup.Startup.test_starts", "outcome": "pass"},
                {"test": "tests.test_80_youtube.YouTube.test_plays", "outcome": "skip"},
                {"test": "tests.test_50_sandbox.Sandbox.test_policy", "outcome": "pass"}],
}


class BootTime(unittest.TestCase):
    def test_freebsd(self):
        self.assertEqual(soak.parse_boot_time(
            sysctl_text="{ sec = 1794382740, usec = 311519 } Wed Nov 11 02:19:00 2026\n"),
            1794382740)

    def test_linux(self):
        self.assertEqual(soak.parse_boot_time(
            proc_stat="cpu  1 2 3\nbtime 1794382740\nprocesses 5\n"), 1794382740)

    def test_neither(self):
        self.assertIsNone(soak.parse_boot_time(sysctl_text="unknown oid", proc_stat="cpu 1\n"))
        self.assertIsNone(soak.parse_boot_time())


class Entry(unittest.TestCase):
    def test_a_clean_whole_lockdown_run(self):
        e = soak.entry_from_report(REPORT, 1794382740, "/results/run-001")
        self.assertEqual(e["outcome"], soak.CLEAN)
        self.assertEqual(e["package"], "beryllium-0.20.3.18")
        self.assertTrue(e["lockdown"])
        self.assertTrue(e["whole"])
        self.assertFalse(e["headless"])
        self.assertEqual(e["counts"], {"pass": 2, "skip": 1})
        self.assertEqual(e["boot"], 1794382740)
        self.assertTrue(soak.counts_toward_the_bar(e))

    def test_a_failure_or_an_error_makes_the_run_not_clean(self):
        for outcome in ("FAIL", "ERROR", "unexpected success"):
            report = dict(REPORT, results=REPORT["results"] + [
                {"test": "tests.test_50_sandbox.Sandbox.test_gate", "outcome": outcome}])
            e = soak.entry_from_report(report, 1, "/r")
            self.assertEqual(e["outcome"], soak.FAILED, outcome)
            self.assertEqual(e["not_passed"],
                             [f"{outcome} tests.test_50_sandbox.Sandbox.test_gate"])

    def test_some_groups_or_no_lockdown_do_not_count(self):
        groups = dict(REPORT, options={"groups": ["sandbox"], "headless": False})
        self.assertFalse(soak.counts_toward_the_bar(soak.entry_from_report(groups, 1, "/r")))
        plain = dict(REPORT, info=dict(REPORT["info"], renderer_lockdown="not requested"))
        self.assertFalse(soak.counts_toward_the_bar(soak.entry_from_report(plain, 1, "/r")))

    def test_a_report_with_no_package_is_still_recorded(self):
        e = soak.entry_from_report(dict(REPORT, info={}), None, "/r")
        self.assertEqual(e["package"], "unknown")
        self.assertFalse(e["lockdown"])


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = os.path.join(self.tmp.name, "sub", "ledger.jsonl")

    def test_append_and_read(self):
        self.assertEqual(soak.read(self.ledger), [])
        soak.append(self.ledger, entry(started="a"))
        soak.append(self.ledger, entry(started="b"))
        self.assertEqual([e["started"] for e in soak.read(self.ledger)], ["a", "b"])

    def test_a_line_cut_short_is_skipped(self):
        soak.append(self.ledger, entry(started="a"))
        with open(self.ledger, "a") as f:
            f.write('{"started": "b", "outco\n\n[1, 2]\n')
        soak.append(self.ledger, entry(started="c"))
        self.assertEqual([e["started"] for e in soak.read(self.ledger)], ["a", "c"])


class Tally(unittest.TestCase):
    def test_clean_runs_in_a_row(self):
        t = soak.tally([entry(boot=1), entry(boot=1), entry(boot=2, headless=True)])
        p = t["beryllium-0.20.3.18"]
        self.assertEqual((p["runs"], p["clean"], p["streak"], p["boots"], p["windows"]),
                         (3, 3, 3, 2, 2))
        self.assertFalse(p["met"])

    def test_a_failure_starts_the_count_again(self):
        for bad in (soak.FAILED, soak.HUNG, soak.DIED):
            t = soak.tally([entry(boot=1), entry(boot=1), entry(bad, boot=2),
                            entry(boot=3), entry(boot=3)])
            p = t["beryllium-0.20.3.18"]
            self.assertEqual((p["runs"], p["clean"], p["streak"], p["boots"], p["windows"]),
                             (5, 4, 2, 1, 2), bad)
            self.assertEqual(p["last_bad"]["outcome"], bad)

    def test_runs_that_do_not_count_change_nothing(self):
        t = soak.tally([entry(), entry(soak.FAILED, lockdown=False),
                        entry(soak.FAILED, whole=False), entry()])
        p = t["beryllium-0.20.3.18"]
        self.assertEqual((p["runs"], p["streak"]), (2, 2))
        self.assertIsNone(p["last_bad"])

    def test_each_package_version_is_counted_alone(self):
        t = soak.tally([entry(package="beryllium-0.20.3.17"),
                        entry(soak.FAILED, package="beryllium-0.20.3.18"),
                        entry(package="beryllium-0.20.3.17")])
        self.assertEqual(t["beryllium-0.20.3.17"]["streak"], 2)
        self.assertEqual(t["beryllium-0.20.3.18"]["streak"], 0)
        self.assertEqual(list(t), ["beryllium-0.20.3.17", "beryllium-0.20.3.18"])

    def test_the_bar(self):
        def runs(n, boots, headless_after):
            return [entry(boot=i % boots, headless=i >= headless_after) for i in range(n)]
        name = "beryllium-0.20.3.18"
        self.assertTrue(soak.tally(runs(soak.BAR_RUNS, soak.BAR_BOOTS, soak.BAR_WINDOWS))
                        [name]["met"])
        self.assertFalse(soak.tally(runs(soak.BAR_RUNS - 1, soak.BAR_BOOTS, soak.BAR_WINDOWS))
                         [name]["met"])
        self.assertFalse(soak.tally(runs(soak.BAR_RUNS, soak.BAR_BOOTS - 1, soak.BAR_WINDOWS))
                         [name]["met"])
        self.assertFalse(soak.tally(runs(soak.BAR_RUNS, soak.BAR_BOOTS, soak.BAR_WINDOWS - 1))
                         [name]["met"])

    def test_a_run_with_no_boot_time_adds_no_boot(self):
        t = soak.tally([entry(boot=None), entry(boot=None)])
        self.assertEqual(t["beryllium-0.20.3.18"]["boots"], 0)

    def test_the_bar_is_what_the_plan_says(self):
        """plan/18 section 3.2 states the numbers; a change here without a
        change there would move the bar silently."""
        with open(os.path.join(HERE, "..", "..", "..", "plan", "18-REMAINING-WORK.md")) as f:
            plan = " ".join(f.read().split())
        for words in (f"{soak.BAR_RUNS} consecutive whole-suite lockdown runs",
                      f"at least {soak.BAR_BOOTS} boots",
                      f"at least {soak.BAR_WINDOWS} of them with windows"):
            self.assertTrue(words in plan, f"plan/18 does not say: {words}")


class GateMark(unittest.TestCase):
    """The lockdown gate read the last 200 lines of the lockdown's log
    until 12 November 2026, the end of it only from 0.20.3.13. A run made
    then is evidence and is not in the count (plan/18 section 3.2)."""

    def test_a_new_line_carries_the_mark(self):
        self.assertEqual(soak.entry_from_report(REPORT, 100, "/r")["gate"], soak.GATE)
        self.assertEqual(soak.entry_without_report(soak.HUNG, 0, 1800, 100, "p", True, True,
                                                   False, "/r")["gate"], soak.GATE)

    def test_a_line_without_the_mark_is_kept_and_not_counted(self):
        old = [entry(gate=None) for _ in range(3)]
        self.assertEqual(soak.tally(old), {})
        mixed = old + [entry(), entry()]
        self.assertEqual(soak.tally(mixed)["beryllium-0.20.3.18"]["streak"], 2)
        self.assertEqual(soak.tally(mixed)["beryllium-0.20.3.18"]["runs"], 2)

    def test_a_failure_before_the_mark_does_not_break_a_later_count(self):
        runs = [entry(soak.FAILED, gate=None), entry(), entry()]
        self.assertEqual(soak.tally(runs)["beryllium-0.20.3.18"]["streak"], 2)
        self.assertIsNone(soak.tally(runs)["beryllium-0.20.3.18"]["last_bad"])

    def test_the_tally_says_what_it_left_out(self):
        text = "\n".join(soak.tally_lines([entry(gate=None), entry(gate=None), entry()]))
        self.assertIn("beryllium-0.20.3.18: 2 whole-suite lockdown runs made before the gate "
                      "read the whole of the lockdown's log (12 November 2026): kept, not "
                      "counted", text)
        self.assertIn("beryllium-0.20.3.18: 1 whole-suite lockdown runs, 1 clean", text)
        only_old = soak.tally_lines([entry(gate=None)])
        self.assertIn("1 whole-suite lockdown run made before", only_old[0])
        self.assertIn("No whole-suite lockdown run that counts", only_old[1])
        # runs that never counted (no lockdown, some groups) are not "left out"
        self.assertEqual(soak.made_before_the_gate_read_the_whole_log(
            [entry(lockdown=False, gate=None), entry(whole=False, gate=None)]), {})


class TallyWords(unittest.TestCase):
    def test_nothing_yet(self):
        self.assertIn("No whole-suite lockdown run", soak.tally_lines([])[0])
        self.assertIn("No whole-suite lockdown run",
                      soak.tally_lines([entry(lockdown=False)])[0])

    def test_not_yet_says_what_is_missing(self):
        lines = soak.tally_lines([entry(boot=1), entry(soak.FAILED, boot=1), entry(boot=2)])
        text = "\n".join(lines)
        self.assertIn("beryllium-0.20.3.18: 3 whole-suite lockdown runs, 2 clean, 1 not", text)
        self.assertIn("clean in a row, counting back from the latest: 1 (over 1 boot, "
                      "1 with windows)", text)
        self.assertIn(f"not yet, needs {soak.BAR_RUNS - 1} more runs, "
                      f"{soak.BAR_BOOTS - 1} more boots, "
                      f"{soak.BAR_WINDOWS - 1} more with windows", text)
        self.assertIn("last run that was not clean: 2026-11-12 01:00:00, failed", text)
        self.assertIn("fail tests.test_50_sandbox.X.test_y", text)

    def test_met(self):
        runs = [entry(boot=i % soak.BAR_BOOTS) for i in range(soak.BAR_RUNS)]
        self.assertTrue(any(line.endswith("): met") for line in soak.tally_lines(runs)))

    def test_only_one_package(self):
        runs = [entry(package="a"), entry(package="b")]
        self.assertTrue(soak.tally_lines(runs, only="b")[0].startswith("b: "))
        self.assertEqual(soak.tally_lines(runs, only="c"), [])


class Repeat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = os.path.join(self.tmp.name, "ledger.jsonl")
        self.said = []

    def describe(self, outcome, started, seconds, results):
        return soak.entry_without_report(outcome, started, seconds, 7, "beryllium-0.20.3.18",
                                         True, True, False, results)

    def repeat(self, times, launch):
        return soak.repeat(times, os.path.join(self.tmp.name, "res"), self.ledger, launch,
                           self.describe, say=self.said.append, pause=0)

    def test_each_run_has_its_own_directory_and_line(self):
        seen = []

        def launch(results):
            seen.append(os.path.basename(results))
            soak.append(self.ledger, dict(entry(), results=results))
            return 0, 190.2
        self.assertEqual(self.repeat(3, launch), 0)
        self.assertEqual(seen, ["run-001", "run-002", "run-003"])
        self.assertEqual(len(soak.read(self.ledger)), 3)
        self.assertIn("run 3 of 3: clean (190 s)", self.said[-3])
        self.assertIn("clean in a row, counting back from the latest: 3", self.said[-1])

    def test_a_failing_run_does_not_end_the_night(self):
        outcomes = iter([soak.CLEAN, soak.FAILED, soak.CLEAN])

        def launch(results):
            outcome = next(outcomes)
            soak.append(self.ledger, entry(outcome))
            return (0 if outcome == soak.CLEAN else 1), 1
        self.assertEqual(self.repeat(3, launch), 1)
        self.assertEqual([e["outcome"] for e in soak.read(self.ledger)],
                         [soak.CLEAN, soak.FAILED, soak.CLEAN])

    def test_a_run_that_hangs_or_dies_is_a_run_that_failed(self):
        answers = iter([(None, 1800.0), (-11, 3.0)])
        self.assertEqual(self.repeat(2, lambda results: next(answers)), 1)
        entries = soak.read(self.ledger)
        self.assertEqual([e["outcome"] for e in entries], [soak.HUNG, soak.DIED])
        self.assertTrue(all(soak.counts_toward_the_bar(e) for e in entries))
        self.assertEqual(soak.tally(entries)["beryllium-0.20.3.18"]["streak"], 0)

    def test_a_run_you_stop_is_not_recorded(self):
        def launch(results):
            raise KeyboardInterrupt
        self.assertEqual(self.repeat(5, launch), 130)
        self.assertEqual(soak.read(self.ledger), [])
        self.assertIn("stopped by you", self.said[-1])


def gone(pid):
    """True once a process has ended. A zombie still answers kill(pid, 0)
    until it is reaped; Linux says so in /proc, and elsewhere it is reaped
    soon enough for the caller's retries."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] == "Z"
    except OSError:
        return False


class RunOnce(unittest.TestCase):
    def start(self, code):
        return lambda: subprocess.Popen([sys.executable, "-c", code], start_new_session=True)

    def test_exit_status(self):
        status, seconds = soak.run_once(self.start("raise SystemExit(3)"))
        self.assertEqual(status, 3)
        self.assertGreaterEqual(seconds, 0)

    def test_a_hung_run_is_stopped_with_its_children(self):
        """The child starts a grandchild (as a run starts browsers) and both
        sleep; stopping the run must leave neither."""
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = os.path.join(tmp, "pid")
            code = ("import subprocess, sys, time\n"
                    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
                    f"open({pidfile!r}, 'w').write(str(p.pid))\n"
                    "time.sleep(600)\n")
            status, _ = soak.run_once(self.start(code), timeout=3)
            self.assertIsNone(status)
            with open(pidfile) as f:
                grandchild = int(f.read())
            for _ in range(50):
                if gone(grandchild):
                    break
                time.sleep(0.1)
            else:
                self.fail("the hung run's child process is still running")


class RunScript(unittest.TestCase):
    def options(self, *argv):
        return suite_run.options(list(argv) + ["--results", "/nonexistent/results"])

    def test_repeat_and_ledger_options(self):
        o = self.options("--lockdown", "--repeat", "100", "--ledger", "/x/ledger.jsonl")
        self.assertEqual(o.repeat, 100)
        self.assertEqual(o.ledger, "/x/ledger.jsonl")
        self.assertEqual(self.options().repeat, 0)
        self.assertTrue(self.options().ledger.endswith("beryllium-test-results/ledger.jsonl"))

    def test_a_run_made_by_a_repeat_does_not_repeat(self):
        with mock.patch.dict(os.environ, {suite_run.REPEAT_CHILD: "1"}):
            self.assertEqual(self.options("--repeat", "100").repeat, 0)

    def test_a_repeat_that_cannot_count_says_so(self):
        counting = "\n".join(suite_run.repeat_lines(self.options("--lockdown", "--repeat", "5")))
        self.assertIn("Repeat: 5 runs", counting)
        self.assertNotIn("do not count", counting)
        for argv in (("--repeat", "5"), ("--lockdown", "--repeat", "5", "sandbox")):
            self.assertIn("do not count toward the bar",
                          "\n".join(suite_run.repeat_lines(self.options(*argv))))


if __name__ == "__main__":
    unittest.main()
