# SPDX-License-Identifier: GPL-3.0-only
"""What build 0.20.3.21 adds to the sandbox, as the test suite reads it:

- the browser's check of each renderer with the kernel when its channel
  connects (the "attested" and "ended" lines);
- beryllium://sandbox, written by the browser as plain lines, and from
  0.20.3.22 its word for a renderer that is still starting;
- the cut lines of senders other than the browser;
- the switch that turns a renderer's receive-side limits off.

The browser is not run here. The parsers are tested on the text the patches
write, and the patches are checked to still write that text, so the two
cannot drift apart without a failure."""

import argparse
import importlib.util
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUITE = os.path.join(REPO, "freebsd", "tests", "browser")
sys.path.insert(0, SUITE)

spec = importlib.util.spec_from_file_location(
    "test_50_sandbox_status", os.path.join(SUITE, "tests", "test_50_sandbox.py"))
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)
capsicum = sandbox.capsicum

LOCKDOWN = ["--enable-features=BerylliumCapsicumRenderer"]


def patch_text(name):
    with open(os.path.join(REPO, "patches", "security", name), encoding="utf-8") as f:
        return f.read()


def patched_text(patch, added_only=False):
    """What a patch leaves in the files it changes, as far as the patch
    shows it: its added lines, and its context lines unless added_only,
    with string literals that the compiler would join (one ending a line,
    the next starting the following line) joined here too."""
    keep = "+" if added_only else "+ "
    lines = [l[1:] for l in patch.splitlines()
             if l[:1] in keep and not l.startswith("+++")]
    text = re.sub(r'"\s*\n\s*"', "", "\n".join(lines))
    return text.replace("\\n", "\n").replace('\\"', '"')


STARTING = "not yet (starting)"


FINE = {"kernel_capability_mode": "available", "kernel_signals_refused": "yes"}


STATED = ("browser", "renderer", "GPU", "network service", "storage service", "audio service",
          "video capture", "other utilities")


def page(rows, lockdown="on", summary=None, attested=3, ended=0, limits="on",
         starting_count=None, build=21, kernel_check=FINE, statements=STATED):
    """The page as beryllium-sandbox-status-page.patch writes it: build 21
    as 0.20.3.21 has it, build 22 with the count of starting renderers,
    which the summary's "N of M" then leaves out."""
    marked = [r for r in rows if r[4] == STARTING]
    if build < 22:
        assert not marked and starting_count is None, "0.20.3.21 has no word for starting"
    renderers = [r for r in rows if r[0] == "renderer" and r not in marked]
    others = [r for r in rows if r[0] not in ("renderer", "browser")]
    if summary is None:
        summary = (sum(r[2] == "yes" for r in renderers), len(renderers),
                   sum(r[2] == "yes" for r in others), len(others))
    if starting_count is None:
        starting_count = len(marked)
    counted = ("" if build < 22 else f"renderers starting: {starting_count}; ")
    lines = ["Beryllium sandbox status", "",
             "Every value below was read in the browser when this page was loaded:", "",
             "summary: renderers in capability mode: %d of %d; " % summary[:2] + counted +
             "other child processes in capability mode: %d of %d; "
             "the browser process is not confined" % summary[2:], ""]
    for kind, pid, mode, requested, was in rows:
        lines.append(f"process: {kind} | pid: {pid} | capability mode by the kernel: {mode}"
                     f" | lockdown requested: {requested} | attested at connect: {was}")
    lines += ["", f"renderer lockdown (BerylliumCapsicumRenderer): {lockdown}",
              f"renderers attested by the kernel at connect, this session: {attested}",
              f"renderers ended because the kernel did not attest them, this session: {ended}",
              f"receive-side limits (BerylliumReceiveSideLimits): {limits}",
              "switches in effect that weaken a sandbox: none",
              "kernel: FreeBSD 16.0-CURRENT"]
    if build >= 22:
        lines += [capsicum.PAGE_SETTINGS[key] + said for key, said in kernel_check.items()]
        lines += [""] + [f"not confined: {kind} | a reason" for kind in statements]
    return "\n".join(lines)


CONFINED = [("browser", 100, "no", "no", "not applicable"),
            ("renderer", 201, "yes", "yes", "yes"),
            ("renderer", 202, "yes", "yes", "yes"),
            ("GPU (GPU)", 300, "no", "no", "not applicable"),
            ("Utility (network.mojom.NetworkService)", 301, "no", "no", "not applicable")]
OPEN = [("browser", 100, "no", "no", "not applicable"),
        ("renderer", 201, "no", "no", "not applicable"),
        ("GPU (GPU)", 300, "no", "no", "not applicable")]


def kernel(rows):
    return {pid: mode == "yes" for _, pid, mode, _, _ in rows}


class Page(unittest.TestCase):
    def test_the_page_is_read_line_by_line(self):
        status = capsicum.parse_sandbox_page(page(CONFINED))
        self.assertEqual([r["pid"] for r in status["rows"]], [100, 201, 202, 300, 301])
        self.assertEqual(status["rows"][1], {"kind": "renderer", "pid": 201, "mode": "yes",
                                             "requested": "yes", "attested": "yes"})
        self.assertEqual(status["summary"], (2, 2, 0, 2))
        self.assertEqual(status["settings"]["lockdown"], "on")
        self.assertEqual(status["settings"]["attested_total"], "3")
        self.assertEqual(status["settings"]["kernel"], "FreeBSD 16.0-CURRENT")

    def test_another_page_is_not_the_status_page(self):
        for text in ("", None, "Sandbox Status\nYou are not adequately sandboxed."):
            self.assertIsNone(capsicum.parse_sandbox_page(text))

    def test_a_page_that_agrees_with_the_kernel_has_no_problems(self):
        for rows, lockdown in ((CONFINED, True), (OPEN, False)):
            text = page(rows, lockdown="on" if lockdown else "off")
            self.assertEqual(capsicum.sandbox_page_problems(
                capsicum.parse_sandbox_page(text), kernel(rows), lockdown), [])

    def test_a_line_that_differs_from_procstat_is_a_problem(self):
        status = capsicum.parse_sandbox_page(page(CONFINED))
        modes = kernel(CONFINED)
        modes[202] = False
        problems = capsicum.sandbox_page_problems(status, modes, True)
        self.assertEqual(len(problems), 1)
        self.assertIn("pid 202: the page says capability mode yes, procstat says no", problems[0])

    def test_a_process_that_ended_meanwhile_is_not_a_problem_and_an_unreadable_one_is(self):
        status = capsicum.parse_sandbox_page(page(CONFINED))
        modes = kernel(CONFINED)
        modes[202] = "gone"
        self.assertEqual(capsicum.sandbox_page_problems(status, modes, True), [])
        modes[202] = None
        self.assertIn("procstat could not read it",
                      capsicum.sandbox_page_problems(status, modes, True)[0])

    def test_the_summary_must_be_the_sum_of_the_lines(self):
        status = capsicum.parse_sandbox_page(page(CONFINED, summary=(2, 2, 1, 2)))
        problems = capsicum.sandbox_page_problems(status, kernel(CONFINED), True)
        self.assertTrue(any("the summary says" in p for p in problems), problems)

    def test_the_lockdown_line_must_match_the_run(self):
        status = capsicum.parse_sandbox_page(page(OPEN, lockdown="on"))
        problems = capsicum.sandbox_page_problems(status, kernel(OPEN), False)
        self.assertTrue(any("the page says the lockdown is 'on'" in p for p in problems), problems)

    def test_with_the_lockdown_on_every_renderer_was_asked_and_attested(self):
        rows = list(CONFINED)
        rows[2] = ("renderer", 202, "yes", "yes", "no")
        status = capsicum.parse_sandbox_page(page(rows))
        problems = capsicum.sandbox_page_problems(status, kernel(rows), True)
        self.assertTrue(any("pid 202: lockdown requested yes, attested no" in p
                            for p in problems), problems)

    def test_an_empty_page_is_a_problem(self):
        status = capsicum.parse_sandbox_page("Beryllium sandbox status\n")
        self.assertEqual(capsicum.sandbox_page_problems(status, {}, False),
                         ["the page lists no process"])

    def test_the_page_of_0_20_3_21_has_no_count_of_starting_renderers(self):
        self.assertIsNone(capsicum.parse_sandbox_page(page(CONFINED))["starting_count"])
        self.assertEqual(capsicum.parse_sandbox_page(page(CONFINED, build=22))["starting_count"], 0)


# The page from 0.20.3.22, as the patch's own code wrote it on 16 November
# 2026: the function that builds the page, taken from the patched file and
# run on Linux with stand-ins for what it calls, for a browser with four
# renderers the browser asked to lock down. 201 is attested; 202 and 203 are
# not ready yet, and 203 has locked down already; 204 is ready and was not
# attested, which is a renderer the browser refused. (The body's text, as
# the suite reads it from the page.)
FROM_THE_CODE = """Beryllium sandbox status

Every value below was read in the browser when this page was loaded:
capability mode from the kernel (kern.proc.pid, what procstat -s
prints as C), the rest from the browser's own records. Nothing here
is a process's own report. Reload the page to read again.

A renderer marked starting was launched a moment ago and has not
connected to the browser yet. The browser asks the kernel about
it when it connects, and ends it unless the kernel says it is
confined. When this page opens in a new tab, its own renderer
is one. Reload the page to see what became of it.

summary: renderers in capability mode: 1 of 2; renderers starting: 2; other child processes in capability mode: 0 of 1; the browser process is not confined

process: browser | pid: 100 | capability mode by the kernel: no | lockdown requested: no | attested at connect: not applicable
process: renderer | pid: 201 | capability mode by the kernel: yes | lockdown requested: yes | attested at connect: yes
process: renderer | pid: 202 | capability mode by the kernel: no | lockdown requested: yes | attested at connect: not yet (starting)
process: renderer | pid: 203 | capability mode by the kernel: yes | lockdown requested: yes | attested at connect: not yet (starting)
process: renderer | pid: 204 | capability mode by the kernel: no | lockdown requested: yes | attested at connect: no
process: GPU (GPU) | pid: 300 | capability mode by the kernel: no | lockdown requested: no | attested at connect: not applicable

renderer lockdown (BerylliumCapsicumRenderer): on
renderers attested by the kernel at connect, this session: 1
renderers ended because the kernel did not attest them, this session: 0
receive-side limits (BerylliumReceiveSideLimits): on
switches in effect that weaken a sandbox: none
kernel: FreeBSD 16.0-CURRENT
kernel check: capability mode: available
kernel check: a process in capability mode is refused signals to other processes (FreeBSD-SA-26:28.capsicum): yes

With the lockdown off, no process is confined, and a page that
takes over a renderer has the access you have. With it on, the
renderers are confined and the browser, GPU, network and storage
processes are not. man beryllium-sandbox says what that means.

Processes that are not confined, and why (decided 12 November 2026):
not confined: browser | it holds the profile, the network and the windows of every tab; other browsers leave this process unconfined too, except OpenBSD's port, whose limits still allow files, processes and the network
not confined: renderer | only while the renderer lockdown is off, which it is unless switched on; with it on, a renderer the kernel does not have in capability mode is ended
not confined: GPU | the graphics driver opens devices and files by path whenever it likes, and NVIDIA's is closed code that cannot be changed to ask first
not confined: network service | it makes every connection and keeps the cache by path; confining it needs a broker for both, which is described in the plan and not scheduled
not confined: storage service | it opens the profile's databases by path; Chromium has a mode in which the browser opens them for it, which has not been tried here yet
not confined: audio service | it reaches the sound server by path; a policy is to follow the utilities
not confined: video capture | it opens cameras by path; Chromium leaves it unconfined on every desktop system
not confined: other utilities | a utility is confined once a survey shows that it needs nothing by path after its start; --enable-features=BerylliumCapsicumUtilities confines the first three candidates, as an experiment
Confined or not, a child process gives up the means to gain privileges where its sandbox would begin (BerylliumChildNoNewPrivileges, on unless switched off); proccontrol -m nonewprivs -q -p PID shows it.
"""
FROM_THE_CODE_KERNEL = {100: False, 201: True, 202: False, 203: True, 204: False, 300: False}

MARKED = [("browser", 100, "no", "no", "not applicable"),
          ("renderer", 201, "yes", "yes", "yes"),
          ("renderer", 202, "no", "yes", STARTING),
          ("GPU (GPU)", 300, "no", "no", "not applicable")]
SETTLED = [("renderer", 202, "yes", "yes", "yes") if r[1] == 202 else r for r in MARKED]


class PageThatMarksStartingRenderers(unittest.TestCase):
    """beryllium://sandbox from 0.20.3.22."""

    def test_the_text_the_code_wrote_is_read_whole(self):
        status = capsicum.parse_sandbox_page(FROM_THE_CODE)
        self.assertEqual([(r["pid"], r["mode"], r["attested"]) for r in status["rows"]],
                         [(100, "no", "not applicable"), (201, "yes", "yes"),
                          (202, "no", STARTING), (203, "yes", STARTING),
                          (204, "no", "no"), (300, "no", "not applicable")])
        self.assertEqual(status["summary"], (1, 2, 0, 1))
        self.assertEqual(status["starting_count"], 2)
        self.assertEqual(len(status["settings"]), len(capsicum.PAGE_SETTINGS))

    def test_only_the_marked_renderers_are_starting(self):
        status = capsicum.parse_sandbox_page(FROM_THE_CODE)
        self.assertEqual(capsicum.starting_renderers(status), {202, 203})
        self.assertEqual(capsicum.unattested_renderers(status), {202, 203, 204})

    def test_a_renderer_the_browser_refused_is_a_problem_at_once(self):
        status = capsicum.parse_sandbox_page(FROM_THE_CODE)
        problems = capsicum.sandbox_page_problems(
            status, FROM_THE_CODE_KERNEL, True, capsicum.starting_renderers(status))
        self.assertEqual(problems, ["renderer pid 204: lockdown requested yes, attested no, "
                                    "with the lockdown on"])

    def test_the_summary_leaves_starting_renderers_out_and_counts_them(self):
        ok = capsicum.parse_sandbox_page(page(MARKED, build=22))
        self.assertEqual((ok["summary"], ok["starting_count"]), ((1, 1, 0, 1), 1))
        self.assertEqual(capsicum.sandbox_page_problems(
            ok, kernel(MARKED), True, capsicum.starting_renderers(ok)), [])
        # counted with the rest, as 0.20.3.21 did
        old = capsicum.parse_sandbox_page(page(MARKED, build=22, summary=(1, 2, 0, 1)))
        self.assertTrue(any("the summary says (1, 2, 0, 1)" in p for p in
                            capsicum.sandbox_page_problems(old, kernel(MARKED), True, {202})))
        miscounted = capsicum.parse_sandbox_page(page(MARKED, build=22, starting_count=0))
        self.assertIn("the summary says 0 renderers starting and 1 lines are marked so",
                      capsicum.sandbox_page_problems(miscounted, kernel(MARKED), True, {202}))

    def test_starting_is_a_word_for_a_process_asked_to_lock_down(self):
        rows = [("renderer", 202, "no", "no", STARTING) if r[1] == 202 else r for r in MARKED]
        status = capsicum.parse_sandbox_page(page(rows, build=22, lockdown="off"))
        problems = capsicum.sandbox_page_problems(status, kernel(rows), False)
        self.assertTrue(any("pid 202: marked starting, which is for a process asked to lock "
                            "down" in p for p in problems), problems)

    def test_a_mark_without_a_count_is_a_problem(self):
        text = page(MARKED, build=22).replace("renderers starting: 1; ", "")
        status = capsicum.parse_sandbox_page(text)
        self.assertIsNone(status["starting_count"])
        problems = capsicum.sandbox_page_problems(status, kernel(MARKED), True, {202})
        self.assertTrue(any("does not count starting renderers" in p for p in problems), problems)

    def test_the_kernel_check_is_on_the_page_and_must_be_fine_under_the_lockdown(self):
        status = capsicum.parse_sandbox_page(FROM_THE_CODE)
        self.assertEqual({k: status["settings"][k] for k in FINE}, FINE)
        self.assertEqual(capsicum.KERNEL_CHECK_FINE, FINE)
        bad = dict(FINE, kernel_signals_refused="no, this kernel needs the fix")
        status = capsicum.parse_sandbox_page(page(MARKED, build=22, kernel_check=bad))
        problems = capsicum.sandbox_page_problems(status, kernel(MARKED), True, {202})
        self.assertEqual(problems, [capsicum.PAGE_SETTINGS["kernel_signals_refused"]
                                    + "no, this kernel needs the fix"])
        # without the lockdown the page only reports it
        rows = [r for r in OPEN]
        status = capsicum.parse_sandbox_page(page(rows, build=22, lockdown="off",
                                                  kernel_check=bad))
        self.assertEqual(capsicum.sandbox_page_problems(status, kernel(rows), False), [])
        # a page from 0.20.3.22 without the lines is wrong either way
        status = capsicum.parse_sandbox_page(page(rows, build=22, lockdown="off",
                                                  kernel_check={}))
        problems = capsicum.sandbox_page_problems(status, kernel(rows), False)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all(p.startswith("the page has no line") for p in problems), problems)
        # and 0.20.3.21's page, which has no such lines, is not held to them
        status = capsicum.parse_sandbox_page(page(rows, lockdown="off"))
        self.assertEqual(capsicum.sandbox_page_problems(status, kernel(rows), False), [])

    def test_every_unconfined_kind_of_process_has_its_reason_on_the_page(self):
        status = capsicum.parse_sandbox_page(FROM_THE_CODE)
        self.assertEqual(sorted(status["statements"]), sorted(STATED))
        for row_kind, kind in (("browser", "browser"), ("renderer", "renderer"),
                               ("GPU (GPU)", "GPU"),
                               ("Utility (network.mojom.NetworkService)", "network service"),
                               ("Utility (storage.mojom.StorageService)", "storage service"),
                               ("Utility (audio.mojom.AudioService)", "audio service"),
                               ("Utility (video_capture.mojom.VideoCaptureService)",
                                "video capture"),
                               ("Utility (unzip.mojom.Unzipper)", "other utilities")):
            self.assertEqual(capsicum.statement_kind(row_kind), kind)
        without = [k for k in STATED if k != "GPU"]
        status = capsicum.parse_sandbox_page(page(MARKED, build=22, statements=without))
        problems = capsicum.sandbox_page_problems(status, kernel(MARKED), True, {202})
        self.assertEqual(problems, ['the page has unconfined processes of the kind "GPU" and '
                                    'no "not confined:" line for it'])

    def test_a_process_is_confined_or_not_as_the_browser_means_it_to_be(self):
        # a utility the browser told to lock down, confined and attested
        rows = MARKED + [("Utility (unzip.mojom.Unzipper)", 400, "yes", "yes", "yes")]
        status = capsicum.parse_sandbox_page(page(rows, build=22))
        self.assertEqual(capsicum.sandbox_page_problems(status, kernel(rows), True, {202}), [])
        # one still starting is marked, and not counted among the renderers
        rows = MARKED + [("Utility (unzip.mojom.Unzipper)", 400, "no", "yes", STARTING)]
        status = capsicum.parse_sandbox_page(page(rows, build=22, starting_count=1))
        self.assertEqual(capsicum.sandbox_page_problems(status, kernel(rows), True, {202}), [])
        # a process in capability mode that the browser does not list as asked
        modes = kernel(MARKED)
        modes[300] = True
        status = capsicum.parse_sandbox_page(page(MARKED, build=22))
        problems = capsicum.sandbox_page_problems(status, modes, True, {202})
        self.assertIn("GPU (GPU) pid 300: in capability mode by procstat, and the browser "
                      "does not list it as asked to lock down", problems)

    def test_a_starting_renderer_that_locked_down_meanwhile_is_not_a_disagreement(self):
        status = capsicum.parse_sandbox_page(page(MARKED, build=22))
        modes = kernel(MARKED)
        modes[202] = True
        self.assertEqual(capsicum.sandbox_page_problems(status, modes, True, {202}), [])


def line(pid, text):
    return f"[{pid}:{pid}:1115/100000.000000:WARNING:x.cc:1] beryllium-sandbox: {text}"


LOG = [
    line(201, "renderer pid=201 capability_mode=1 closed_directories=0 limited=9 threads=1 "
              "thread_names=CrRendererMain"),
    line(100, "renderer pid=201 attested: in capability mode by the kernel's account"),
    line(100, "cut shared memory (fd 40) bound for confined renderer pid 201"),
    line(300, "cut shared memory (fd 12) bound for confined renderer on a link the browser marked"),
    line(300, "cut socket (fd 13) bound for confined renderer on a link the browser marked"),
    line(301, "cut socket (fd 9) bound for confined renderer on a link the browser marked"),
]


class Log(unittest.TestCase):
    def test_cuts_are_counted_by_the_process_that_made_them(self):
        types = {100: "browser", 300: "GPU", 301: "utility"}
        self.assertEqual(capsicum.cuts_by_sender(LOG, types),
                         {"GPU": 2, "browser": 1, "utility": 1})
        # the browser's own count, per renderer, is as before
        self.assertEqual(capsicum.sent_cuts(LOG), {201: 1})

    def test_a_sender_that_is_no_longer_listed_keeps_its_pid(self):
        self.assertEqual(capsicum.cuts_by_sender(LOG, {100: "browser"}),
                         {"browser": 1, "pid 300": 2, "pid 301": 1})

    def test_attested_and_ended_renderers(self):
        log = LOG + [
            line(100, "renderer pid=202 is not in capability mode by the kernel's account; ended"),
            line(100, "renderer pid=203 has no answer from the kernel about its capability "
                      "mode; ended"),
        ]
        attested, ended = capsicum.attestations(log)
        self.assertEqual(attested, [201])
        self.assertEqual(sorted(ended), [202, 203])
        self.assertIn("has no answer from the kernel", ended[203])
        self.assertEqual(capsicum.locked_pids(log), [201])

    def test_versions(self):
        self.assertEqual(capsicum.version_tuple("beryllium-0.20.3.21"), (0, 20, 3, 21))
        self.assertEqual(capsicum.version_tuple("0.21.3.1\n"), (0, 21, 3, 1))
        self.assertEqual(capsicum.version_tuple(""), ())
        self.assertLess(capsicum.version_tuple("0.20.3.20"), sandbox.BUILD_21)
        self.assertGreater(capsicum.version_tuple("0.21.3.1"), sandbox.BUILD_21)


class PatchesWriteWhatTheSuiteReads(unittest.TestCase):
    """The parsers above against the text of the patches themselves."""

    def page_patches(self):
        """What the page's patches write: the page itself, and from
        0.20.3.22 the two lines of the kernel check."""
        return "\n".join(patched_text(patch_text(name)) for name in
                         ("beryllium-sandbox-status-page.patch",
                          "beryllium-kernel-check.patch",
                          "beryllium-utility-lockdown.patch",
                          "beryllium-unconfined-processes.patch"))

    def test_the_status_page(self):
        said = self.page_patches()
        self.assertIn(capsicum.PAGE_TITLE, said)
        for prefix in capsicum.PAGE_SETTINGS.values():
            self.assertTrue(prefix in said, f"no patch writes {prefix!r}")
        for kind in STATED:
            self.assertTrue(f"not confined: {kind} | " in said,
                            f"no patch states why the {kind} is not confined")
        for piece in ("process: ", " | pid: ", " | capability mode by the kernel: ",
                      " | lockdown requested: ", " | attested at connect: ",
                      "summary: renderers in capability mode: ",
                      "; other child processes in capability mode: ",
                      "; the browser process is not confined"):
            self.assertIn(piece, said, piece)
        for word in ('"yes"', '"no"', '"unknown"', '"not applicable"', '"renderer"',
                     '"browser"', '"on"', '"off"', f'"{capsicum.PAGE_STARTING}"'):
            self.assertIn(word, patch_text("beryllium-sandbox-status-page.patch"), word)
        self.assertEqual(capsicum.PAGE_STARTING, STARTING)
        self.assertIn("; renderers starting: ", said)

    def test_the_text_kept_from_the_code_is_what_the_patch_still_writes(self):
        """FROM_THE_CODE was written by the patched file's own function. Each
        of its lines that is fixed text must still be in the patch, so a
        change to the page's wording cannot leave the fixture behind."""
        said = self.page_patches()
        for text in FROM_THE_CODE.split("\n\n")[1:3] + FROM_THE_CODE.split("\n\n")[-1:]:
            for fixed in text.strip().splitlines():
                self.assertTrue(fixed in said, f"no patch writes {fixed!r}")
        for key, fine in FINE.items():
            self.assertIn(capsicum.PAGE_SETTINGS[key] + fine, FROM_THE_CODE)
            self.assertTrue(f'"{fine}"' in said, f"no patch writes {fine!r}")

    def test_the_attestation_lines(self):
        patch = patch_text("beryllium-kernel-attested-renderer.patch")
        said = patched_text(patch)
        for piece in ("beryllium-sandbox: renderer pid=",
                      " attested: in capability mode by the kernel's account",
                      " is not in capability mode by the kernel's account",
                      " has no answer from the kernel about its capability mode",
                      "; ended"):
            self.assertIn(piece, said, piece)
        # No wording the gate counts as a failure of the lockdown itself.
        self.assertNotIn("could not", patched_text(patch.split("\n--- a/", 1)[1],
                                                   added_only=True))

    def test_the_cut_lines(self):
        said = patched_text(patch_text("beryllium-sender-cut-on-child-links.patch"))
        self.assertIn("confined renderer pid ", said)
        self.assertIn("confined renderer on a link the browser marked", said)
        self.assertIn("beryllium-sandbox: cut ", said)
        self.assertIn(") bound for ", said)

    def test_the_receive_limits_line(self):
        said = patched_text(patch_text("beryllium-receive-limits-switch.patch"))
        self.assertIn("beryllium-sandbox: receive-side limits are off in pid ", said)
        # Not a line the gate takes for a refused descriptor.
        self.assertNotIn("beryllium-sandbox: received", said)


def gate_case(cls, method, browser_args, log=(), processes=(), page_text=""):
    t = cls(method)
    t.GRACE_SECONDS = 0
    t.browser = mock.Mock()
    t.browser.conn.send.return_value = {"processInfo": list(processes)}
    t.browser.log_lines.return_value = list(log)
    t.browser.log_context.return_value = []
    t.browser.url.side_effect = lambda path: f"beryllium://{path}"
    t.browser.new_page.return_value.eval.return_value = page_text
    t.ctx = mock.Mock()
    t.ctx.options = argparse.Namespace(browser_args=list(browser_args))
    t.note = mock.Mock()
    return t


def modes_are(by_pid):
    return mock.patch.object(capsicum, "capability_modes",
                             side_effect=lambda pids, **kw: {p: by_pid.get(p, "gone") for p in pids})


def build(version):
    return mock.patch.object(capsicum, "installed_version", return_value=version)


class PageTest(unittest.TestCase):
    METHOD = "test_sandbox_page_matches_the_kernel"

    def test_passes_when_the_page_and_the_kernel_agree(self):
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, LOCKDOWN, page_text=page(CONFINED))
        with modes_are(kernel(CONFINED)):
            t.test_sandbox_page_matches_the_kernel()

    def test_fails_when_a_renderer_the_page_calls_confined_is_not(self):
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, LOCKDOWN, page_text=page(CONFINED))
        modes = kernel(CONFINED)
        modes[201] = False
        with modes_are(modes), self.assertRaises(AssertionError) as e:
            t.test_sandbox_page_matches_the_kernel()
        self.assertIn("disagrees with the kernel", str(e.exception))

    def test_without_the_lockdown_it_checks_the_same_lines(self):
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, [], page_text=page(OPEN, lockdown="off"))
        with modes_are(kernel(OPEN)):
            t.test_sandbox_page_matches_the_kernel()

    def test_an_older_build_has_no_such_page_and_is_skipped(self):
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, LOCKDOWN, page_text="Sandbox Status")
        with build((0, 20, 3, 20)), self.assertRaises(unittest.SkipTest):
            t.test_sandbox_page_matches_the_kernel()

    def test_a_build_that_should_have_the_page_fails_the_gate_without_it(self):
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, LOCKDOWN, page_text="")
        with build((0, 20, 3, 21)), self.assertRaises(AssertionError):
            t.test_sandbox_page_matches_the_kernel()
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, [], page_text="")
        with build((0, 20, 3, 21)), self.assertRaises(unittest.SkipTest):
            t.test_sandbox_page_matches_the_kernel()  # a survey skips


# The page of the first lockdown run on 0.20.3.21 (15 November 2026), which
# failed this test as it was first written: two renderers were listed while
# they were still starting. By the time procstat ran, one had locked down
# and the other was gone.
FIRST_RUN = [("browser", 2598, "no", "no", "not applicable"),
             ("renderer", 41514, "yes", "yes", "yes"),
             ("renderer", 32136, "yes", "yes", "yes"),
             ("renderer", 5105, "yes", "yes", "yes"),
             ("renderer", 42213, "no", "yes", "no"),
             ("renderer", 3915, "yes", "yes", "yes"),
             ("renderer", 42199, "no", "yes", "no"),
             ("GPU (GPU)", 3065, "no", "no", "not applicable"),
             ("Utility (network.mojom.NetworkService)", 3347, "no", "no", "not applicable")]
FIRST_RUN_KERNEL = {2598: False, 41514: "gone", 32136: True, 5105: True, 42213: True,
                    3915: True, 42199: "gone", 3065: False, 3347: False}
LATER = [r for r in FIRST_RUN if r[1] not in (42213, 42199)] + \
        [("renderer", 42213, "yes", "yes", "yes")]


class clock:
    """Time for the test's waiting: each look at the clock is a second on."""

    def __enter__(self):
        self.now = 0.0
        self.patches = [mock.patch.object(sandbox.time, "sleep"),
                        mock.patch.object(sandbox.time, "monotonic", side_effect=self.tick)]
        for p in self.patches:
            p.start()
        return self

    def tick(self):
        self.now += 1.0
        return self.now

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


class StartingRenderers(unittest.TestCase):
    """A renderer the page lists before it has locked down and connected."""

    METHOD = "test_sandbox_page_matches_the_kernel"

    def status(self, rows=FIRST_RUN, **kw):
        return capsicum.parse_sandbox_page(page(rows, **kw))

    def test_they_are_the_requested_renderers_not_yet_confined_or_attested(self):
        self.assertEqual(capsicum.starting_renderers(self.status()), {42213, 42199})
        self.assertEqual(capsicum.starting_renderers(self.status(CONFINED)), set())
        # without the lockdown nothing was requested, so nothing is starting
        self.assertEqual(capsicum.starting_renderers(self.status(OPEN, lockdown="off")), set())

    def test_the_first_run_as_the_test_first_judged_it(self):
        problems = capsicum.sandbox_page_problems(self.status(), FIRST_RUN_KERNEL, True)
        self.assertEqual(problems, [
            "renderer pid 42213: the page says capability mode no, procstat says yes",
            "renderer pid 42213: lockdown requested yes, attested no, with the lockdown on",
            "renderer pid 42199: lockdown requested yes, attested no, with the lockdown on"])

    def test_a_starting_renderer_is_not_a_disagreement(self):
        status = self.status()
        self.assertEqual(capsicum.sandbox_page_problems(
            status, FIRST_RUN_KERNEL, True, capsicum.starting_renderers(status)), [])

    def test_no_process_leaves_capability_mode_starting_or_not(self):
        rows = [("renderer", 42213, "yes", "yes", "no") if r[1] == 42213 else r
                for r in FIRST_RUN]
        status = self.status(rows)
        modes = dict(FIRST_RUN_KERNEL)
        modes[42213] = False
        problems = capsicum.sandbox_page_problems(status, modes, True,
                                                  capsicum.starting_renderers(status))
        self.assertEqual(problems, ["renderer pid 42213: the page says capability mode yes, "
                                    "procstat says no"])

    def run_test(self, readings, browser_args=LOCKDOWN, kernel=FIRST_RUN_KERNEL):
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, browser_args)
        t.GRACE_SECONDS = 5.0
        t.browser.new_page.return_value.eval.side_effect = list(readings)
        with clock(), modes_are(kernel):
            t.test_sandbox_page_matches_the_kernel()
        return t

    def test_passes_when_a_later_reading_shows_them_confined_and_attested_or_gone(self):
        t = self.run_test([page(FIRST_RUN), page(LATER)])
        self.assertIn("caught while they were starting: [42199, 42213]", t.note.call_args[0][0])

    def test_fails_when_one_is_still_not_there_after_the_grace(self):
        with self.assertRaises(AssertionError) as e:
            self.run_test([page(FIRST_RUN)] * 12)
        self.assertIn("pid 42213: still not confined and attested", str(e.exception))

    def test_fails_when_the_browser_ended_a_renderer_meanwhile(self):
        with self.assertRaises(AssertionError) as e:
            self.run_test([page(FIRST_RUN), page(LATER, ended=1)])
        self.assertIn("counts 1 renderers ended", str(e.exception))

    def test_without_the_lockdown_a_renderer_that_became_confined_is_a_problem(self):
        with self.assertRaises(AssertionError) as e:
            self.run_test([page(OPEN, lockdown="off")], browser_args=[],
                          kernel={100: False, 201: True, 300: False})
        self.assertIn("the page says capability mode no, procstat says yes", str(e.exception))


class StartingRenderersMarkedByThePage(unittest.TestCase):
    """The same test on a page from 0.20.3.22, which says who is starting."""

    METHOD = "test_sandbox_page_matches_the_kernel"
    KERNEL = {100: False, 201: True, 202: True, 300: False}

    def run_test(self, readings, kernel=None):
        t = gate_case(sandbox.SandboxHonesty, self.METHOD, LOCKDOWN)
        t.GRACE_SECONDS = 5.0
        t.browser.new_page.return_value.eval.side_effect = list(readings)
        with clock(), modes_are(kernel or self.KERNEL):
            t.test_sandbox_page_matches_the_kernel()
        return t

    def test_passes_when_a_later_reading_shows_it_confined_and_attested(self):
        t = self.run_test([page(MARKED, build=22), page(SETTLED, build=22)])
        note = t.note.call_args[0][0]
        self.assertIn("caught while they were starting: [202]", note)
        self.assertIn("summary: (1, 1, 0, 1), starting 1", note)

    def test_fails_when_it_is_still_starting_after_the_grace(self):
        with self.assertRaises(AssertionError) as e:
            self.run_test([page(MARKED, build=22)] * 12)
        self.assertIn("pid 202: still not confined and attested", str(e.exception))

    def test_fails_when_the_starting_renderer_was_then_refused(self):
        refused = [("renderer", 202, "no", "yes", "no") if r[1] == 202 else r for r in MARKED]
        with self.assertRaises(AssertionError) as e:
            self.run_test([page(MARKED, build=22)] + [page(refused, build=22, ended=1)] * 11,
                          kernel={100: False, 201: True, 202: False, 300: False})
        self.assertIn("pid 202: still not confined and attested", str(e.exception))
        self.assertIn("counts 1 renderers ended", str(e.exception))

    def test_fails_on_an_unattested_renderer_the_page_does_not_call_starting(self):
        """However the starting ones turn out: here both are confined and
        attested in the next reading, and the refused one is gone from it."""
        later = [("browser", 100, "no", "no", "not applicable"),
                 ("renderer", 201, "yes", "yes", "yes"),
                 ("renderer", 202, "yes", "yes", "yes"),
                 ("renderer", 203, "yes", "yes", "yes"),
                 ("GPU (GPU)", 300, "no", "no", "not applicable")]
        with self.assertRaises(AssertionError) as e:
            self.run_test([FROM_THE_CODE, page(later, build=22)], kernel=FROM_THE_CODE_KERNEL)
        self.assertIn("pid 204: lockdown requested yes, attested no", str(e.exception))
        self.assertNotIn("still not confined", str(e.exception))


class UnconfinedRendererTest(unittest.TestCase):
    METHOD = "test_an_unconfined_renderer_is_ended"
    ENDED = [line(100, "renderer pid=201 is not in capability mode by the kernel's account; "
                       "ended")]

    def case(self, args, log, crash=True):
        t = gate_case(sandbox.UnconfinedRenderer, self.METHOD, args, log=log)
        if crash:
            t.browser.new_page.side_effect = sandbox.CDPError("the target is gone")
        else:
            t.browser.new_page.return_value.eval.return_value = "busy"
        return t

    def test_skipped_without_the_lockdown(self):
        with self.assertRaises(unittest.SkipTest):
            self.case([], self.ENDED).test_an_unconfined_renderer_is_ended()

    def test_passes_when_the_renderer_was_ended_and_the_page_never_answered(self):
        with mock.patch.object(sandbox.time, "sleep"):
            self.case(LOCKDOWN, self.ENDED).test_an_unconfined_renderer_is_ended()

    def test_fails_when_the_page_answered(self):
        with mock.patch.object(sandbox.time, "sleep"), self.assertRaises(AssertionError) as e:
            self.case(LOCKDOWN, self.ENDED, crash=False).test_an_unconfined_renderer_is_ended()
        self.assertIn("answered a script", str(e.exception))

    def test_fails_when_a_renderer_was_attested(self):
        log = [line(100, "renderer pid=201 attested: in capability mode by the kernel's account")]
        with mock.patch.object(sandbox.time, "sleep"), self.assertRaises(AssertionError) as e:
            self.case(LOCKDOWN, log).test_an_unconfined_renderer_is_ended()
        self.assertIn("no renderer was ended", str(e.exception))

    def test_a_build_without_the_check_is_skipped_and_a_newer_one_fails(self):
        with mock.patch.object(sandbox.time, "sleep"):
            with build((0, 20, 3, 20)), self.assertRaises(unittest.SkipTest):
                self.case(LOCKDOWN, []).test_an_unconfined_renderer_is_ended()
            with build((0, 20, 3, 21)), self.assertRaises(AssertionError):
                self.case(LOCKDOWN, []).test_an_unconfined_renderer_is_ended()


class SenderAloneTest(unittest.TestCase):
    METHOD = "test_the_senders_cut_alone_keeps_the_policy"

    def test_the_class_switches_the_receivers_half_off(self):
        self.assertIn("--disable-features=BerylliumReceiveSideLimits",
                      sandbox.SenderAlone.BROWSER_ARGS)
        self.assertIn("--vmodule=capsicum_rights=1", sandbox.SenderAlone.BROWSER_ARGS)

    def test_skipped_without_the_lockdown(self):
        t = gate_case(sandbox.SenderAlone, self.METHOD, [])
        with self.assertRaises(unittest.SkipTest):
            t.test_the_senders_cut_alone_keeps_the_policy()

    def test_a_run_in_which_no_renderer_said_its_limits_are_off_proves_nothing(self):
        with mock.patch.object(sandbox.time, "sleep"):
            t = gate_case(sandbox.SenderAlone, self.METHOD, LOCKDOWN, log=LOG)
            with build((0, 20, 3, 21)), self.assertRaises(AssertionError):
                t.test_the_senders_cut_alone_keeps_the_policy()
            t = gate_case(sandbox.SenderAlone, self.METHOD, LOCKDOWN, log=LOG)
            with build((0, 20, 3, 20)), self.assertRaises(unittest.SkipTest):
                t.test_the_senders_cut_alone_keeps_the_policy()

    def test_with_the_limits_off_it_goes_on_to_the_descriptor_policy(self):
        log = LOG + [line(201, "receive-side limits are off in pid 201 "
                               "(BerylliumReceiveSideLimits disabled, a test configuration)")]
        t = gate_case(sandbox.SenderAlone, self.METHOD, LOCKDOWN, log=log)
        t.descriptors_follow_the_policy = mock.Mock()
        with mock.patch.object(sandbox.time, "sleep"):
            t.test_the_senders_cut_alone_keeps_the_policy()
        t.descriptors_follow_the_policy.assert_called_once_with()


class GateReadsTheAttestation(unittest.TestCase):
    """test_lockdown_log, on a build that writes the attestation lines."""

    PROCS = [{"id": 100, "type": "browser"}, {"id": 201, "type": "renderer"},
             {"id": 300, "type": "GPU"}, {"id": 301, "type": "utility"}]

    def run_log_test(self, log):
        t = gate_case(sandbox.SandboxHonesty, "test_lockdown_log", LOCKDOWN, log=log,
                      processes=self.PROCS)
        with mock.patch.object(sandbox.time, "sleep"):
            t.test_lockdown_log()
        return t

    def test_passes_with_every_locked_renderer_attested(self):
        t = self.run_log_test(LOG)
        note = t.note.call_args[0][0]
        self.assertIn("cuts by the process that made them: {'GPU': 2, 'browser': 1, 'utility': 1}",
                      note)
        self.assertIn("renderers the kernel attested when they connected: 1", note)

    def test_fails_when_the_browser_ended_a_renderer(self):
        log = LOG + [line(100, "renderer pid=202 is not in capability mode by the kernel's "
                               "account; ended")]
        with self.assertRaises(AssertionError) as e:
            self.run_log_test(log)
        self.assertIn("ended renderers the kernel did not attest", str(e.exception))

    def test_fails_when_a_locked_renderer_was_never_attested(self):
        log = LOG + [line(202, "renderer pid=202 capability_mode=1 closed_directories=0 "
                               "limited=9 threads=1 thread_names=CrRendererMain")]
        with self.assertRaises(AssertionError) as e:
            self.run_log_test(log)
        self.assertIn("were not attested", str(e.exception))

    def test_fails_when_a_renderer_ran_with_its_limits_off(self):
        log = LOG + [line(201, "receive-side limits are off in pid 201")]
        with self.assertRaises(AssertionError) as e:
            self.run_log_test(log)
        self.assertIn("receive-side limits off in the ordinary gate", str(e.exception))

    def test_an_older_build_writes_no_such_lines_and_passes_as_before(self):
        self.run_log_test([l for l in LOG if "attested" not in l])


if __name__ == "__main__":
    unittest.main()
