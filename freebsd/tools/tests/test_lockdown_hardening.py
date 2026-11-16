# SPDX-License-Identifier: GPL-3.0-only
"""What build 0.20.3.22 adds to the renderer lockdown, as the test suite
reads it:

- the calls made beside capability mode (no new privileges, no core, no
  fork, no tracing), named at the end of each lockdown line;
- the switch that leaves a renderer traceable, which the classes that read
  a renderer's descriptors ask for, and the class that does not;
- the trap switch's report of each call capability mode refuses.

The browser is not run here. The parsers are tested on the text the patches
write, and the patches are checked to still write that text."""

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_sandbox_status import (LOCKDOWN, LOG, build, capsicum, gate_case,  # noqa: E402
                                 line, modes_are, patch_text, patched_text, sandbox)

from berytest.browser import merge_feature_switches  # noqa: E402

TRACEABLE = "no-new-privileges,no-core,no-fork,traceable"
UNTRACEABLE = "no-new-privileges,no-core,no-fork,untraceable"


def locked(pid, hardening=None):
    text = (f"renderer pid={pid} capability_mode=1 closed_directories=0 limited=9 threads=1 "
            "thread_names=CrRendererMain")
    return line(pid, text + (f" hardening={hardening}" if hardening is not None else ""))


# The line the trap report's own code wrote on 16 November 2026: the handler
# and the module list, taken from the patched file and run on Linux, where a
# breakpoint stood in for the kernel's capability trap (so the system call
# number and the error are 0). The first frame is the function that trapped,
# the second its caller.
FROM_THE_CODE = ("beryllium-sandbox: renderer pid=990 refused in capability mode: syscall=0 "
                 "errno=0 thread=990 frames: trap_linux+0x1225 trap_linux+0x1239 "
                 "trap_linux+0x1326 libc.so.6+0x2a1ca libc.so.6+0x2a28b trap_linux+0x1155")
# As it would read on FreeBSD for the one call every survey has seen.
REFUSED = ("beryllium-sandbox: renderer pid=201 refused in capability mode: syscall=487 "
           "errno=94 thread=100321 frames: libc.so.7+0x9d2ca libc.so.7+0x8f1b0 "
           "beryllium+0x5a1c2f0 beryllium+0x5a1c100 0x8204b1c40")
REPORTING = line(201, "renderer pid=201 reports refused calls (BerylliumCapsicumTrap), "
                      "87 modules listed")


class FeatureSwitches(unittest.TestCase):
    def test_the_run_and_the_class_share_one_switch(self):
        self.assertEqual(
            merge_feature_switches(["--enable-features=BerylliumCapsicumRenderer",
                                    "--vmodule=capsicum_rights=1",
                                    "--enable-features=BerylliumRendererTraceable"]),
            ["--enable-features=BerylliumCapsicumRenderer,BerylliumRendererTraceable",
             "--vmodule=capsicum_rights=1"])

    def test_enabled_and_disabled_features_are_kept_apart(self):
        self.assertEqual(
            merge_feature_switches(["--a", "--enable-features=X", "--disable-features=Q",
                                    "--enable-features=Y,X", "--disable-features=R"]),
            ["--a", "--enable-features=X,Y", "--disable-features=Q,R"])

    def test_other_switches_are_left_as_they_are(self):
        args = ["--no-sandbox", "--vmodule=capsicum_rights=1", "about:blank"]
        self.assertEqual(merge_feature_switches(args), args)
        self.assertEqual(merge_feature_switches([]), [])

    def test_the_classes_that_read_descriptors_ask_for_a_traceable_renderer(self):
        for cls in (sandbox.SandboxHonesty, sandbox.SenderAlone, sandbox.ThreadsAtLockdown,
                    sandbox.TrapReport):
            self.assertIn(capsicum.TRACEABLE_SWITCH, cls.BROWSER_ARGS, cls.__name__)
        for cls in (sandbox.Untraceable, sandbox.UnconfinedRenderer):
            self.assertNotIn(capsicum.TRACEABLE_SWITCH, cls.BROWSER_ARGS, cls.__name__)
        # and each class's switches still merge with the run's into one
        merged = merge_feature_switches(LOCKDOWN + list(sandbox.TrapReport.BROWSER_ARGS))
        self.assertEqual([a for a in merged if a.startswith("--enable-features=")],
                         ["--enable-features=BerylliumCapsicumRenderer,"
                          "BerylliumRendererTraceable,BerylliumCapsicumTrap"])


class Hardening(unittest.TestCase):
    def test_the_lockdown_line_says_what_was_set(self):
        lines = [locked(201, TRACEABLE), locked(202, UNTRACEABLE), locked(203, "-"),
                 locked(204)]
        self.assertEqual(capsicum.hardening_at_lockdown(lines),
                         {201: TRACEABLE.split(","), 202: UNTRACEABLE.split(","), 203: []})
        # the older readers of the same line are not disturbed by the new field
        self.assertEqual(capsicum.threads_at_lockdown(lines), [1, 1, 1, 1])
        self.assertEqual(capsicum.thread_names_at_lockdown(lines), [["CrRendererMain"]] * 4)
        self.assertEqual(capsicum.locked_pids(lines), [201, 202, 203, 204])

    def test_every_call_must_be_there_and_tracing_as_the_run_asked(self):
        both = capsicum.hardening_at_lockdown([locked(201, TRACEABLE), locked(202, UNTRACEABLE)])
        self.assertEqual(capsicum.hardening_problems({201: both[201]}, traceable=True), [])
        self.assertEqual(capsicum.hardening_problems({202: both[202]}, traceable=False), [])
        problems = capsicum.hardening_problems(both, traceable=True)
        self.assertEqual(len(problems), 1)
        self.assertIn("pid 202", problems[0])
        self.assertIn("expects traceable", problems[0])
        lacking = capsicum.hardening_problems({201: ["no-core", "traceable"]}, traceable=True)
        self.assertEqual(lacking, ["renderer pid 201: its lockdown did not set "
                                   "no-new-privileges, no-fork"])
        nothing = capsicum.hardening_problems({201: []}, traceable=False)
        self.assertEqual(len(nothing), 2)


class Refused(unittest.TestCase):
    def test_the_line_the_code_wrote_is_read_whole(self):
        calls = capsicum.refused_calls(["noise", FROM_THE_CODE])
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["pid"], calls[0]["syscall"], calls[0]["thread"]), (990, 0, 990))
        self.assertEqual(calls[0]["frames"][:2], [("trap_linux", 0x1225), ("trap_linux", 0x1239)])
        self.assertEqual(len(calls[0]["frames"]), 6)

    def test_a_bare_address_and_the_last_report_are_read(self):
        text = REFUSED + " (no further refused calls are reported)"
        calls = capsicum.refused_calls([text])
        self.assertEqual(calls[0]["frames"][-1], (None, 0x8204b1c40))
        self.assertEqual(len(calls[0]["frames"]), 5)
        self.assertEqual((calls[0]["syscall"], calls[0]["errno"]), (487, 94))

    def test_system_calls_are_named_from_the_header(self):
        header = ("#define\tSYS_exit\t1\n#define\tSYS_cpuset_getaffinity\t487\n"
                  "#define\tSYS_MAXSYSCALL\t600\n/* a comment */\n")
        names = capsicum.syscall_names(text=header)
        self.assertEqual(names[1], "exit")
        self.assertEqual(names[487], "cpuset_getaffinity")
        self.assertNotIn(600, names)
        # without the header the one known call still has its name
        self.assertEqual(capsicum.syscall_names(header="/nonexistent/syscall.h")[487],
                         "cpuset_getaffinity")

    def test_the_same_call_from_the_same_code_is_one_line(self):
        other = REFUSED.replace("pid=201", "pid=202")
        different = REFUSED.replace("syscall=487", "syscall=5").replace("0x5a1c2f0", "0x111")
        calls = capsicum.refused_calls([REFUSED, REFUSED, other, different])
        asked = []

        def symbolizer(cmd, text):
            asked.append(text.split())
            return "".join(f"Function{i}()\n??:0\n\n" for i, _ in enumerate(text.split()))

        with mock.patch.object(capsicum.shutil, "which", return_value="/usr/bin/llvm-symbolizer"):
            described = capsicum.describe_refused(calls, "/usr/local/share/beryllium/beryllium",
                                                  names={487: "cpuset_getaffinity"},
                                                  run=symbolizer)
        self.assertEqual(len(described), 2)
        self.assertTrue(described[0].startswith(
            "cpuset_getaffinity (ECAPMODE), 3 times in 2 renderers: libc.so.7+0x9d2ca < "
            "libc.so.7+0x8f1b0 < Function"), described[0])
        self.assertTrue(described[0].endswith("< ?+0x8204b1c40"), described[0])
        self.assertTrue(described[1].startswith("syscall 5 (ECAPMODE), 1 times in 1 renderers"),
                        described[1])
        # only the browser's own frames go to the symbolizer, each once
        self.assertEqual(asked, [["0x111", "0x5a1c100", "0x5a1c2f0"]])

    def test_no_lines_no_description(self):
        self.assertEqual(capsicum.refused_calls(LOG), [])
        self.assertEqual(capsicum.describe_refused([], "/x/beryllium"), [])


class PatchesWriteWhatTheSuiteReads(unittest.TestCase):
    def test_the_hardening_field(self):
        patch = patch_text("beryllium-renderer-hardening.patch")
        said = patched_text(patch)
        self.assertIn(' hardening=', said)
        for call in capsicum.HARDENING_CALLS:
            self.assertIn(f'"{call},"', patch, call)
        for word in ('"traceable"', '"untraceable"'):
            self.assertIn(word, patch, word)
        for feature in ("kBerylliumRendererHardening", "kBerylliumRendererTraceable"):
            self.assertIn(f"BASE_FEATURE({feature},", said, feature)
        self.assertEqual(capsicum.TRACEABLE_SWITCH,
                         "--enable-features=BerylliumRendererTraceable")
        # the message a traced renderer ends with names the switch
        self.assertIn(capsicum.TRACEABLE_SWITCH, said)

    def test_the_trap_report(self):
        patch = patch_text("beryllium-capability-trap-report.patch")
        said = patched_text(patch)
        for piece in ("beryllium-sandbox: renderer pid=", " refused in capability mode: syscall=",
                      " errno=", " thread=", " frames:", " reports refused calls",
                      " (no further refused calls are reported)"):
            self.assertIn(piece, said, piece)
        # every fixed piece of the line the code wrote is still in the patch
        for piece in ("refused in capability mode: syscall=", "errno=", "thread=", "frames:"):
            self.assertIn(piece, FROM_THE_CODE)
        self.assertIn("absl::base_internal::NumCPUs()", said)

    def test_neither_writes_a_word_the_gate_takes_for_a_failed_lockdown(self):
        for name in ("beryllium-renderer-hardening.patch",
                     "beryllium-capability-trap-report.patch"):
            code = patch_text(name).split("\n--- a/", 1)[1]
            added = patched_text(code, added_only=True)
            self.assertNotIn("could not", added, name)
            self.assertNotIn("beryllium-sandbox: received", added, name)

    def test_both_are_in_the_series_after_the_lockdown(self):
        with open(os.path.join(os.path.dirname(HERE), "..", "..", "patches", "series"),
                  encoding="utf-8") as f:
            series = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        order = [series.index(f"security/{n}.patch") for n in
                 ("beryllium-capsicum-renderer", "beryllium-renderer-hardening",
                  "beryllium-capability-trap-report")]
        self.assertEqual(order, sorted(order))


PROCS = [{"id": 100, "type": "browser"}, {"id": 201, "type": "renderer"},
         {"id": 300, "type": "GPU"}, {"id": 301, "type": "utility"}]


def with_hardening(log, hardening):
    """LOG with the renderer's lockdown line carrying hardening=."""
    return [l + f" hardening={hardening}" if "capability_mode=1" in l else l for l in log]


class GateReadsTheHardening(unittest.TestCase):
    def run_log_test(self, log, cls=sandbox.SandboxHonesty):
        t = gate_case(cls, "test_lockdown_log", LOCKDOWN, log=log, processes=PROCS)
        with mock.patch.object(sandbox.time, "sleep"):
            t.test_lockdown_log()
        return t

    def test_passes_with_every_call_and_a_traceable_renderer(self):
        t = self.run_log_test(with_hardening(LOG, TRACEABLE))
        self.assertIn(f"1 x [{TRACEABLE}]", t.note.call_args[0][0])

    def test_fails_when_a_call_is_missing(self):
        with self.assertRaises(AssertionError) as e:
            self.run_log_test(with_hardening(LOG, "no-core,traceable"))
        self.assertIn("did not set no-new-privileges, no-fork", str(e.exception))

    def test_fails_when_the_renderer_is_not_traceable_in_a_class_that_asked(self):
        with self.assertRaises(AssertionError) as e:
            self.run_log_test(with_hardening(LOG, UNTRACEABLE))
        self.assertIn("expects traceable", str(e.exception))

    def test_an_older_build_writes_no_such_field_and_passes_as_before(self):
        with build((0, 20, 3, 21)):
            self.run_log_test(LOG)

    def test_a_build_that_should_write_it_fails_without_it(self):
        with build((0, 20, 3, 22)), self.assertRaises(AssertionError) as e:
            self.run_log_test(LOG)
        self.assertIn("hardening=", str(e.exception))


class UntraceableTest(unittest.TestCase):
    METHOD = "test_a_locked_down_renderer_cannot_be_read"

    def case(self, args=LOCKDOWN, hardening=UNTRACEABLE, rights=None, modes=None):
        log = with_hardening(LOG, hardening) if hardening is not None else LOG
        t = gate_case(sandbox.Untraceable, self.METHOD, args, log=log, processes=PROCS)
        rights = {100: {"3": {}}, 201: {}} if rights is None else rights
        self.patches = [
            mock.patch.object(capsicum, "rights", side_effect=lambda pid: rights.get(pid, {})),
            modes_are({201: True} if modes is None else modes),
        ]
        return t

    def run_case(self, t):
        with self.patches[0], self.patches[1]:
            t.test_a_locked_down_renderer_cannot_be_read()

    def test_skipped_without_the_lockdown(self):
        with self.assertRaises(unittest.SkipTest):
            self.run_case(self.case(args=[]))

    def test_passes_when_the_browser_is_readable_and_the_renderer_is_not(self):
        self.run_case(self.case())

    def test_fails_when_procstat_reads_the_renderer(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(self.case(rights={100: {"3": {}}, 201: {"3": {}, "4": {}}}))
        self.assertIn("procstat read 2 of its descriptors", str(e.exception))

    def test_fails_when_the_lockdown_left_the_renderer_traceable(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(self.case(hardening=TRACEABLE))
        self.assertIn("expects untraceable", str(e.exception))

    def test_fails_when_the_renderer_is_not_confined(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(self.case(modes={201: False}))
        self.assertIn("not in capability mode", str(e.exception))

    def test_a_machine_where_nothing_is_readable_shows_nothing(self):
        with self.assertRaises(AssertionError) as e:
            self.run_case(self.case(rights={}))
        self.assertIn("cannot read the browser's own descriptors", str(e.exception))

    def test_an_older_build_is_skipped_and_a_newer_one_without_the_field_fails(self):
        with build((0, 20, 3, 21)), self.assertRaises(unittest.SkipTest):
            self.run_case(self.case(hardening=None))
        with build((0, 20, 3, 22)), self.assertRaises(AssertionError):
            self.run_case(self.case(hardening=None))


class TrapReportTest(unittest.TestCase):
    METHOD = "test_nothing_is_refused_after_the_lockdown"

    def case(self, log, args=LOCKDOWN):
        t = gate_case(sandbox.TrapReport, self.METHOD, args, log=log, processes=PROCS)
        t.SETTLE_SECONDS = 0
        t.ctx.media.return_value = ({}, None)
        return t

    def test_the_class_asks_for_the_trap_and_a_traceable_renderer(self):
        self.assertIn("--enable-features=BerylliumCapsicumTrap", sandbox.TrapReport.BROWSER_ARGS)

    def test_no_browser_is_started_on_a_build_whose_trap_ends_the_renderer(self):
        with build((0, 20, 3, 21)), \
                mock.patch.object(sandbox.Gate, "setUpClass") as start, \
                self.assertRaises(unittest.SkipTest):
            sandbox.TrapReport.setUpClass()
        start.assert_not_called()
        with build((0, 20, 3, 22)), mock.patch.object(sandbox.Gate, "setUpClass") as start:
            sandbox.TrapReport.setUpClass()
        start.assert_called_once_with()

    def test_skipped_without_the_lockdown(self):
        with self.assertRaises(unittest.SkipTest):
            self.case([REPORTING], args=[]).test_nothing_is_refused_after_the_lockdown()

    def test_passes_when_renderers_report_and_nothing_was_refused(self):
        t = self.case(LOG + [REPORTING])
        t.test_nothing_is_refused_after_the_lockdown()
        self.assertIn("renderers that report refused calls: 1; refused calls reported: 0",
                      t.note.call_args[0][0])

    def test_fails_on_a_refused_call_and_names_it(self):
        t = self.case(LOG + [REPORTING, REFUSED])
        with self.assertRaises(AssertionError) as e:
            t.test_nothing_is_refused_after_the_lockdown()
        self.assertIn("cpuset_getaffinity (ECAPMODE), 1 times in 1 renderers", str(e.exception))
        self.assertIn("libc.so.7+0x9d2ca", str(e.exception))

    def test_a_run_in_which_no_renderer_reports_proves_nothing(self):
        with build((0, 20, 3, 22)), self.assertRaises(AssertionError):
            self.case(LOG).test_nothing_is_refused_after_the_lockdown()
        with build((0, 20, 3, 21)), self.assertRaises(unittest.SkipTest):
            self.case(LOG).test_nothing_is_refused_after_the_lockdown()


if __name__ == "__main__":
    unittest.main()
