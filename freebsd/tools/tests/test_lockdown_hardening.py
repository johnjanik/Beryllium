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
            "cpuset_getaffinity (ECAPMODE), 3 times in 2 processes: libc.so.7+0x9d2ca < "
            "libc.so.7+0x8f1b0 < Function"), described[0])
        self.assertTrue(described[0].endswith("< ?+0x8204b1c40"), described[0])
        self.assertTrue(described[1].startswith("syscall 5 (ECAPMODE), 1 times in 1 processes"),
                        described[1])
        # only the browser's own frames go to the symbolizer, each once
        self.assertEqual(asked, [["0x111", "0x5a1c100", "0x5a1c2f0"]])

    def test_no_lines_no_description(self):
        self.assertEqual(capsicum.refused_calls(LOG), [])
        self.assertEqual(capsicum.describe_refused([], "/x/beryllium"), [])


def invited(pid, ms=180):
    return line(100, f"renderer pid={pid} invited {ms} ms after its launch, in capability "
                     "mode by the kernel's account")


def uninvited(pid, ms=0):
    return line(100, f"renderer pid={pid} is not in capability mode by the kernel's account; "
                     f"ended before it was sent anything, {ms} ms after its launch")


def cut(pid):
    return line(100, f"cut shared memory (fd 40) bound for confined renderer pid {pid}")


class Invitations(unittest.TestCase):
    def test_the_time_from_launch_to_lockdown_is_read(self):
        log = [invited(201, 180), invited(202, 95), uninvited(203, 10000)]
        self.assertEqual(capsicum.invitations(log), {201: 180, 202: 95})
        self.assertEqual(capsicum.ended_uninvited(log), {203})
        self.assertEqual(capsicum.spread([180, 95, 240]), "95 to 240, median 180")
        self.assertEqual(capsicum.spread([]), "")

    def test_a_renderer_ended_uninvited_is_still_an_ended_renderer(self):
        attested, ended = capsicum.attestations([uninvited(203)])
        self.assertEqual((attested, sorted(ended)), ([], [203]))

    def test_a_cut_before_the_invitation_is_counted_and_one_after_is_not(self):
        log = [cut(201), invited(201), cut(201), cut(201), invited(202), cut(202)]
        self.assertEqual(capsicum.cuts_before_invitation(log), {201: 1})
        self.assertEqual(capsicum.cuts_before_invitation([invited(201), cut(201)]), {})
        # a build that invites at launch writes no such line, and nothing is counted
        self.assertEqual(capsicum.cuts_before_invitation([cut(201), cut(202)]), {})


class PatchesWriteWhatTheSuiteReads(unittest.TestCase):
    def test_the_invitation_lines(self):
        patch = patch_text("beryllium-invite-after-lockdown.patch")
        said = patched_text(patch)
        for piece in ("beryllium-sandbox: renderer pid=", " invited ",
                      " ms after its launch, in capability mode by the kernel's account",
                      " is not in capability mode by the kernel's account",
                      " has no answer from the kernel about its capability mode",
                      "; ended before it was sent anything, "):
            self.assertTrue(piece in said, f"the patch does not write {piece!r}")
        self.assertIn("BASE_FEATURE(kBerylliumInviteAfterLockdown, FEATURE_ENABLED_BY_DEFAULT)",
                      said)
        code = patch.split("\n--- a/", 1)[1]
        self.assertNotIn("could not", patched_text(code, added_only=True))

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

    def test_passes_when_every_attested_renderer_was_invited_first(self):
        t = self.run_log_test([invited(201, 180)] + with_hardening(LOG, TRACEABLE))
        self.assertIn("renderers invited once in capability mode: 1; milliseconds from "
                      "launch to that: 180 to 180, median 180", t.note.call_args[0][0])

    def test_fails_when_an_attested_renderer_was_never_invited_that_way(self):
        log = [invited(555)] + with_hardening(LOG, TRACEABLE)
        with self.assertRaises(AssertionError) as e:
            self.run_log_test(log)
        self.assertIn("had not invited after their lockdown", str(e.exception))

    def test_fails_when_something_was_cut_for_a_renderer_before_its_invitation(self):
        log = with_hardening(LOG, TRACEABLE) + [invited(201)]
        with self.assertRaises(AssertionError) as e:
            self.run_log_test(log)
        self.assertIn("before it invited that renderer", str(e.exception))

    def test_a_build_that_should_invite_after_the_lockdown_fails_without_the_lines(self):
        with build((0, 20, 3, 22)), self.assertRaises(AssertionError) as e:
            self.run_log_test(with_hardening(LOG, TRACEABLE))
        self.assertIn("BerylliumInviteAfterLockdown", str(e.exception))

    def test_a_build_that_should_write_it_fails_without_it(self):
        with build((0, 20, 3, 22)), self.assertRaises(AssertionError) as e:
            self.run_log_test([invited(201)] + LOG)
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


class UnconfinedRendererIsSentNothing(unittest.TestCase):
    METHOD = "test_an_unconfined_renderer_is_ended"

    def case(self, log):
        t = gate_case(sandbox.UnconfinedRenderer, self.METHOD, LOCKDOWN, log=log)
        t.browser.new_page.side_effect = sandbox.CDPError("the target is gone")
        return t

    def test_passes_when_each_was_ended_before_it_was_sent_anything(self):
        with mock.patch.object(sandbox.time, "sleep"), build((0, 20, 3, 22)):
            t = self.case([uninvited(201), uninvited(202)])
            t.test_an_unconfined_renderer_is_ended()
        self.assertIn("ended before they were sent anything: [201, 202]",
                      t.note.call_args[0][0])

    def test_fails_on_this_build_when_one_was_ended_only_at_connect(self):
        at_connect = line(100, "renderer pid=202 is not in capability mode by the kernel's "
                               "account; ended")
        with mock.patch.object(sandbox.time, "sleep"), build((0, 20, 3, 22)), \
                self.assertRaises(AssertionError) as e:
            self.case([uninvited(201), at_connect]).test_an_unconfined_renderer_is_ended()
        self.assertIn("only after it had sent them its invitation", str(e.exception))

    def test_the_build_before_ended_them_at_connect_and_still_passes(self):
        at_connect = line(100, "renderer pid=202 is not in capability mode by the kernel's "
                               "account; ended")
        with mock.patch.object(sandbox.time, "sleep"), build((0, 20, 3, 21)):
            self.case([at_connect]).test_an_unconfined_renderer_is_ended()


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
        self.assertIn("cpuset_getaffinity (ECAPMODE), 1 times in 1 processes", str(e.exception))
        self.assertIn("libc.so.7+0x9d2ca", str(e.exception))

    def test_a_run_in_which_no_renderer_reports_proves_nothing(self):
        with build((0, 20, 3, 22)), self.assertRaises(AssertionError):
            self.case(LOG).test_nothing_is_refused_after_the_lockdown()
        with build((0, 20, 3, 21)), self.assertRaises(unittest.SkipTest):
            self.case(LOG).test_nothing_is_refused_after_the_lockdown()


def utility_locked(pid, service="data_decoder.mojom.DataDecoderService", threads=1):
    return line(pid, f"utility pid={pid} service={service} capability_mode=1 "
                     f"closed_directories=0 limited=7 threads={threads} "
                     f"thread_names=CrUtilityMain hardening={TRACEABLE}")


def utility_invited(pid, ms=140):
    return line(100, f"utility pid={pid} invited {ms} ms after its launch, in capability mode "
                     "by the kernel's account")


class Utilities(unittest.TestCase):
    def test_a_confined_utility_is_read_apart_from_the_renderers(self):
        log = LOG + [utility_locked(401), utility_invited(401, 140),
                     utility_locked(402, "unzip.mojom.Unzipper"),
                     line(403, "utility pid=403 could not enter capability mode: fd 9: a "
                               "writable file"),
                     line(100, "utility pid=404 is not in capability mode by the kernel's "
                               "account; ended before it was sent anything, 10003 ms after "
                               "its launch")]
        locked, failed, ended = capsicum.confined_utilities(log)
        self.assertEqual(locked, {
            401: {"service": "data_decoder.mojom.DataDecoderService", "threads": 1,
                  "invited_ms": 140},
            402: {"service": "unzip.mojom.Unzipper", "threads": 1, "invited_ms": None}})
        self.assertEqual(failed, {403: "fd 9: a writable file"})
        self.assertEqual(ended, {404})
        # the renderers' readers see the renderer only
        self.assertEqual(len(capsicum.renderer_lockdown_lines(log)), 1)
        self.assertEqual(capsicum.locked_pids(log), [201])
        self.assertEqual(capsicum.invitations(log), {})
        self.assertEqual(capsicum.hardening_at_lockdown(
            capsicum.renderer_lockdown_lines(log)), {})

    def test_a_utilitys_refused_calls_are_read_with_the_renderers(self):
        text = REFUSED.replace("renderer pid=201", "utility pid=401")
        self.assertEqual(capsicum.refused_calls([text])[0]["pid"], 401)
        reporting = line(401, "utility pid=401 reports refused calls (BerylliumCapsicumTrap), "
                              "60 modules listed")
        self.assertTrue(capsicum.TRAP_REPORTING_RE.search(reporting))

    def test_the_patch_writes_these_lines(self):
        said = patched_text(patch_text("beryllium-utility-lockdown.patch"))
        for piece in ('"utility"', '"renderer"', " service=", "BerylliumCapsicumUtilities",
                      '"beryllium-lockdown"', '"beryllium-confine-services"',
                      "data_decoder.mojom.DataDecoderService", "unzip.mojom.Unzipper",
                      "patch.mojom.FilePatcher"):
            self.assertTrue(piece in said or piece.strip('"') in said,
                            f"the patch does not write {piece}")
        self.assertIn("BASE_FEATURE(kBerylliumCapsicumUtilities, FEATURE_DISABLED_BY_DEFAULT)",
                      said)
        other = patched_text(patch_text("beryllium-unconfined-processes.patch"))
        self.assertIn("BASE_FEATURE(kBerylliumChildNoNewPrivileges, "
                      "base::FEATURE_ENABLED_BY_DEFAULT)", other)
        for name in ("beryllium-utility-lockdown.patch", "beryllium-unconfined-processes.patch"):
            code = patch_text(name).split("\n--- a/", 1)[1]
            added = patched_text(code, added_only=True)
            # the one failure line a utility's lockdown shares with a renderer's
            self.assertEqual(added.count("could not"), added.count("could not enter capability "
                                                                   "mode"), name)

    def test_the_class_asks_for_the_feature_the_trap_and_a_traceable_process(self):
        merged = merge_feature_switches(LOCKDOWN + list(sandbox.ConfinedUtilities.BROWSER_ARGS))
        self.assertEqual([a for a in merged if a.startswith("--enable-features=")],
                         ["--enable-features=BerylliumCapsicumRenderer,"
                          "BerylliumRendererTraceable,BerylliumCapsicumUtilities,"
                          "BerylliumCapsicumTrap"])


class ConfinedUtilitiesTest(unittest.TestCase):
    METHOD = "test_confined_utilities_are_confined"

    def case(self, log, args=LOCKDOWN):
        t = gate_case(sandbox.ConfinedUtilities, self.METHOD, args, log=log, processes=PROCS)
        t.SETTLE_SECONDS = 0
        return t

    def test_no_browser_is_started_on_an_older_build(self):
        with build((0, 20, 3, 21)), \
                mock.patch.object(sandbox.Gate, "setUpClass") as start, \
                self.assertRaises(unittest.SkipTest):
            sandbox.ConfinedUtilities.setUpClass()
        start.assert_not_called()

    def test_nothing_to_check_when_no_listed_service_started(self):
        with self.assertRaises(unittest.SkipTest):
            self.case(LOG).test_confined_utilities_are_confined()

    def test_passes_when_each_is_confined_by_the_kernel_and_was_invited_after(self):
        t = self.case(LOG + [utility_locked(401), utility_invited(401)])
        with modes_are({401: True}):
            t.test_confined_utilities_are_confined()
        self.assertIn("utility 401 (data_decoder.mojom.DataDecoderService): locked down with 1 "
                      "threads; capability mode by procstat: yes; invited 140 ms",
                      t.note.call_args[0][0])

    def test_a_utility_that_has_ended_since_is_not_a_failure(self):
        t = self.case(LOG + [utility_locked(401), utility_invited(401)])
        with modes_are({}):
            t.test_confined_utilities_are_confined()

    def test_fails_when_the_kernel_does_not_have_it_in_capability_mode(self):
        t = self.case(LOG + [utility_locked(401), utility_invited(401)])
        with modes_are({401: False}), self.assertRaises(AssertionError) as e:
            t.test_confined_utilities_are_confined()
        self.assertIn("says it locked down and procstat says capability mode no",
                      str(e.exception))

    def test_fails_when_no_line_says_it_was_invited_after_its_lockdown(self):
        t = self.case(LOG + [utility_locked(401)])
        with modes_are({401: True}), self.assertRaises(AssertionError) as e:
            t.test_confined_utilities_are_confined()
        self.assertIn("no line says the browser invited it after that", str(e.exception))

    def test_what_a_utility_was_refused_is_listed_and_does_not_fail_the_record(self):
        refused = REFUSED.replace("renderer pid=201", "utility pid=401")
        t = self.case(LOG + [utility_locked(401), utility_invited(401), refused])
        with modes_are({401: True}):
            t.test_confined_utilities_are_confined()
        self.assertIn("what the confined utilities were refused:", t.note.call_args[0][0])
        self.assertIn("cpuset_getaffinity (ECAPMODE)", t.note.call_args[0][0])


class ChildPrivilegesTest(unittest.TestCase):
    METHOD = "test_children_cannot_gain_privileges"

    def case(self, states):
        t = gate_case(sandbox.ChildPrivileges, self.METHOD, [], processes=PROCS)
        self.states = mock.patch.object(sandbox, "no_new_privileges",
                                        side_effect=lambda pid: states.get(pid, ""))
        return t

    def run_case(self, t):
        with self.states, mock.patch.object(sandbox.time, "sleep"):
            t.test_children_cannot_gain_privileges()

    def test_proccontrols_answer_is_read(self):
        self.assertEqual(sandbox.no_new_privileges(1, run=lambda cmd: "enabled\n"), "enabled")
        self.assertEqual(sandbox.no_new_privileges(1, run=lambda cmd: "disabled\n"), "disabled")
        self.assertEqual(sandbox.no_new_privileges(1, run=lambda cmd: "usage: ..."), "")

        def missing(cmd):
            raise OSError("no proccontrol")
        self.assertEqual(sandbox.no_new_privileges(1, run=missing), "")

    def test_passes_when_every_child_has_given_them_up(self):
        self.run_case(self.case({100: "disabled", 201: "enabled", 300: "enabled",
                                 301: "enabled"}))

    def test_fails_when_a_child_has_not(self):
        with build((0, 20, 3, 22)), self.assertRaises(AssertionError) as e:
            self.run_case(self.case({100: "disabled", 201: "enabled", 300: "disabled",
                                     301: "enabled"}))
        self.assertIn("GPU pid 300", str(e.exception))

    def test_an_older_build_is_skipped(self):
        with build((0, 20, 3, 21)), self.assertRaises(unittest.SkipTest):
            self.run_case(self.case({100: "disabled", 201: "disabled", 300: "disabled"}))

    def test_skipped_where_proccontrol_says_nothing(self):
        with self.assertRaises(unittest.SkipTest):
            self.run_case(self.case({}))


if __name__ == "__main__":
    unittest.main()
