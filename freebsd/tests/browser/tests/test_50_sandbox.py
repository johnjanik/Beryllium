# SPDX-License-Identifier: GPL-3.0-only
"""Sandbox status (RT-17): what the browser claims against what the kernel
says. Lists every Beryllium process and whether it is in Capsicum
capability mode (procstat -s shows C in FLAGS)."""

import collections
import os
import shutil
import signal
import subprocess
import time
import unittest

from berytest import capsicum
from berytest.base import BrowserTest
from berytest.browser import DIRECT_BINARY
from berytest.cdp import CDPError, TargetCrashed

# The first build with the kernel check at connect, the status page, the
# senders' cut on links between children and the receive-limits switch.
BUILD_21 = (0, 20, 3, 21)
# The first build whose lockdown also gives up privileges, forking, core
# files and tracing, and whose trap switch reports instead of ending.
BUILD_22 = (0, 20, 3, 22)


capability_mode = capsicum.capability_mode


def no_new_privileges(pid, run=None):
    """What proccontrol(1) says of pid's PROC_NO_NEW_PRIVS state: "enabled",
    "disabled", or "" when it cannot say (no such tool, no such process).
    The kernel answers this for any process the asker may see, so a
    renderer that has disabled tracing of itself answers too."""
    run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True,
                                             timeout=10).stdout)
    try:
        said = run(["proccontrol", "-m", "nonewprivs", "-q", "-p", str(pid)]).strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return said if said in ("enabled", "disabled") else ""


class Processes(BrowserTest):
    def test_process_list(self):
        """Record the browser's processes."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        self.note("\n".join(f"{p['type']:<10} pid {p['id']}" for p in procs))
        types = {p["type"] for p in procs}
        self.assertIn("browser", types)
        self.assertIn("renderer", types)


class ChildPrivileges(BrowserTest):
    """From 0.20.3.22 every child process, confined or not and with or
    without the lockdown, sets PROC_NO_NEW_PRIVS_CTL where its sandbox would
    begin (S-HRD-01): an exec of a set-user-ID file from it gains nothing.
    The browser process does not; it starts helper programs."""

    NEEDS_FREEBSD = True

    def test_children_cannot_gain_privileges(self):
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        time.sleep(1.0)
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        said = {p["id"]: (p["type"], no_new_privileges(p["id"])) for p in procs}
        self.note("\n".join(f"{kind:<10} pid {pid}: new privileges "
                            f"{ {'enabled': 'ruled out', 'disabled': 'possible'}.get(state, 'not read') }"
                            for pid, (kind, state) in sorted(said.items())))
        children = {pid: v for pid, v in said.items() if v[0] != "browser" and v[1]}
        if not children:
            self.skipTest("proccontrol(1) said nothing about any child process")
        version = capsicum.installed_version()
        if version and version < BUILD_22 and not any(s == "enabled" for _, s in children.values()):
            self.skipTest("this build's children do not give up new privileges "
                          "(that comes with 0.20.3.22)")
        open_to_it = sorted(f"{kind} pid {pid}" for pid, (kind, state) in children.items()
                            if state != "enabled")
        self.assertEqual(open_to_it, [], "child processes that could still gain privileges "
                                         "by executing a set-user-ID file")


class Gate(BrowserTest):
    """What the sandbox classes share: with the lockdown requested
    (lockdown_requested) their tests are a gate, and fail on anything short
    of every renderer confined and every observation available; otherwise
    they survey and skip. No tests of its own."""

    NEEDS_FREEBSD = True
    # The senders' cuts are VLOG(1) lines of capsicum_rights.cc. From
    # 0.20.3.22 a locked-down renderer disables tracing of itself, and with
    # it procstat -f and -C, which these classes read every renderer with:
    # they ask for a traceable renderer, and their reports say so. What the
    # default does is the Untraceable class's to show.
    BROWSER_ARGS = ("--vmodule=capsicum_rights=1", capsicum.TRACEABLE_SWITCH)
    TRACEABLE = True
    # How long a renderer the browser has just listed may take to reach its
    # lockdown point before it counts as unconfined.
    GRACE_SECONDS = 5.0

    def strict(self):
        return capsicum.lockdown_requested(self.ctx.options)

    def renderer_modes(self, procs):
        """{pid: mode} for the renderers; under the gate a renderer that is
        not yet confined gets GRACE_SECONDS to reach its lockdown point (a
        survey has nothing to wait for: by default no renderer is confined)."""
        return capsicum.capability_modes([p["id"] for p in procs if p["type"] == "renderer"],
                                         grace=self.GRACE_SECONDS if self.strict() else 0)

    @staticmethod
    def unconfined(modes):
        """Renderers that are neither confined nor gone: False (not in
        capability mode) or None (alive but unreadable)."""
        return {pid: ("unreadable" if m is None else "not in capability mode")
                for pid, m in modes.items() if m is not True and m != "gone"}

    def unavailable(self, why):
        """A missing observation: a failure under the gate, a skip otherwise."""
        if self.strict():
            self.fail(why + " (the lockdown was requested, so this is a failure)")
        self.skipTest(why)

    def older_build(self, what):
        """A check that needs a build from 0.20.3.21: a skip on an older
        package, and what unavailable() makes of it on a newer one, where
        its absence is a fault."""
        version = capsicum.installed_version()
        if version and version < BUILD_21:
            self.skipTest(f"{what}: this is build {'.'.join(map(str, version))}, and it "
                          "comes with 0.20.3.21")
        self.unavailable(what)

    def before_build_22(self, what):
        """The same for what comes with 0.20.3.22."""
        version = capsicum.installed_version()
        if version and version < BUILD_22:
            self.skipTest(f"{what}: this is build {'.'.join(map(str, version))}, and it "
                          "comes with 0.20.3.22")
        self.unavailable(what)

    def read_sandbox_page(self, page):
        """beryllium://sandbox loaded in page, as parse_sandbox_page gives
        it. Each load makes the browser write the page afresh."""
        page.navigate(self.browser.url("sandbox"), timeout=30)
        return capsicum.parse_sandbox_page(
            page.eval("document.body ? document.body.innerText : ''"))

    def descriptors_follow_the_policy(self):
        """With the lockdown on, every descriptor a renderer holds has a type
        the policy allows and no more rights than the policy gives that type
        (S-REN-04, S-REN-05); files are read-only resource files."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        renderers = [p for p in procs if p["type"] == "renderer"]
        modes = self.renderer_modes(procs)
        confined = [p for p in renderers if modes.get(p["id"]) is True]
        if self.strict():
            self.assertEqual(self.unconfined(modes), {},
                             f"renderers not in capability mode {self.GRACE_SECONDS:g} s after "
                             "the browser listed them, or unreadable, although the lockdown "
                             "was requested")
        elif not confined:
            self.skipTest("no renderer in capability mode; this run did not switch the "
                          "lockdown on (run --lockdown)")
        # Every socket of every Beryllium process, so a socket a renderer holds
        # can be traced to the process holding its other end.
        types = {p["id"]: p["type"] for p in procs}
        sockets = {p["id"]: capsicum.socket_peers(p["id"]) for p in procs}
        holders = capsicum.socket_holders(sockets, types)
        problems, lines, unread, gone = [], [], [], []
        for p in confined:
            fds, caps = capsicum.descriptors(p["id"]), capsicum.rights(p["id"])
            if not caps:
                (unread if capsicum.process_alive(p["id"]) else gone).append(p["id"])
                continue
            found = capsicum.policy_problems(fds, caps)
            problems += [f"renderer {p['id']}: {x}" for x in found]
            lines.append(f"renderer {p['id']}: {len(caps)} descriptors, "
                         f"{len(found)} outside the policy")
            socks = sockets.get(p["id"], {})
            for d in fds:  # procstat -f knows whether a socket is blocking
                if d["fd"] in socks:
                    socks[d["fd"]]["flags"] = d["flags"]
            notes = capsicum.socket_notes(caps, socks, holders, p["id"])
            if notes:
                waiting = capsicum.threads_waiting_on_sockets(capsicum.threads(p["id"]))
                notes.append("threads waiting on a socket: " + (", ".join(waiting) or "none"))
            lines += [f"    {x}" for x in notes]
        if gone:
            lines.append(f"renderers that ended before they were read: {gone}")
        if unread and len(unread) + len(gone) == len(confined):
            self.unavailable("procstat could not read renderer descriptors "
                             "(security.bsd.unprivileged_proc_debug=0?)")
        if unread and self.strict():
            problems.append(f"descriptors unreadable for renderers {unread}")
        self.note("\n".join(lines + problems))
        self.assertEqual(problems, [], "confined renderers hold descriptors outside the policy")


class SandboxHonesty(Gate):
    """The gate itself (see Gate)."""

    def test_capability_mode_per_process(self):
        """Every process's capability mode, from the kernel; with the lockdown
        requested, every renderer must be in it."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        modes = self.renderer_modes(procs)
        rows = [(p["type"], p["id"], modes.get(p["id"], capability_mode(p["id"])))
                for p in procs]
        words = {True: "yes", False: "no", None: "unknown", "gone": "ended before it was read"}
        self.note("\n".join(f"{t:<10} pid {pid:<7} capability mode: {words[c]}"
                            for t, pid, c in rows))
        if not any(c in (True, False) for _, _, c in rows):
            self.unavailable("procstat gave no answer")
        if self.strict():
            self.assertTrue(modes, "no renderer to check")
            self.assertEqual(self.unconfined(modes), {},
                             f"renderers not in capability mode {self.GRACE_SECONDS:g} s after "
                             "the browser listed them, or unreadable, although the lockdown "
                             "was requested")

    def test_gpu_sandbox_claim_matches_kernel(self):
        """beryllium://gpu "Sandboxed" equals the GPU process's capability mode."""
        info = self.browser.conn.send("SystemInfo.getInfo", timeout=30)
        claim = info.get("gpu", {}).get("auxAttributes", {}).get("sandboxed")
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        gpu = [p for p in procs if p["type"].lower() == "gpu"]
        self.assertTrue(gpu, "no GPU process")
        actual = capability_mode(gpu[0]["id"])
        self.note(f"GPU process pid {gpu[0]['id']}: claims sandboxed={claim}, "
                  f"kernel capability mode={actual}")
        self.assertIsNotNone(actual, "procstat could not read the GPU process")
        self.assertEqual(bool(claim), bool(actual),
                         "the browser's sandbox claim does not match the kernel (RT-17)")

    def test_renderers_hold_no_directories_or_writable_files(self):
        """No renderer holds a directory or a writable file (S-IPC-01, S-REN-06)."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        problems, details, read = [], [], 0
        # Every vnode of every Beryllium process, by file system and inode, so a
        # file that has no name any more can still be traced to who else holds it.
        files = {p["id"]: capsicum.file_identities(p["id"]) for p in procs}
        holders = {}
        for p in procs:
            for fd, ident in files[p["id"]].items():
                holders.setdefault((ident["mount"], ident["inode"]), []).append(
                    (p["type"], p["id"], fd))
        for p in procs:
            if p["type"] != "renderer":
                continue
            fds = capsicum.descriptors(p["id"])
            if fds:
                read += 1
            for x in capsicum.risky_descriptors(fds):
                problems.append(f"renderer {p['id']}: {x}")
                details.append(problems[-1])
                if "no name" in x:
                    fd = x.split()[1]
                    ident = files[p["id"]].get(fd)
                    others = [h for h in holders.get((ident["mount"], ident["inode"]), [])
                              if h[1] != p["id"]] if ident else []
                    details.append("    " + capsicum.describe_file(ident, others))
        if not read:
            self.unavailable("procstat could not read renderer descriptors "
                             "(security.bsd.unprivileged_proc_debug=0?)")
        self.note("\n".join(details) or f"{read} renderers: none")
        self.assertEqual(problems, [], "renderers hold descriptors they must not")

    def test_confined_renderer_descriptors_follow_the_policy(self):
        """With the lockdown on, every descriptor a renderer holds has a type
        the policy allows and no more rights than the policy gives that type
        (S-REN-04, S-REN-05); files are read-only resource files."""
        self.descriptors_follow_the_policy()

    def test_sandbox_page_matches_the_kernel(self):
        """beryllium://sandbox (from 0.20.3.21) against procstat -s: every
        line's capability mode is the kernel's for that pid, the summary is
        the sum of the lines, and with the lockdown on every renderer was
        asked to lock down and attested (S-STA-02, S-STA-03). A renderer the
        page lists while it is still starting gets GRACE_SECONDS to show as
        confined and attested in a later reading, or to be gone. From
        0.20.3.22 the page says which renderers are starting, and one it
        lists as unattested without that word fails at once."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        page = self.browser.new_page()
        try:
            status = self.read_sandbox_page(page)
            if status is None:
                self.older_build("beryllium://sandbox is not Beryllium's status page")
            modes = capsicum.capability_modes([r["pid"] for r in status["rows"]])
            # The page is written while its own renderer is starting, so
            # with the lockdown on that renderer shows as not confined and
            # not attested yet ("no" on 0.20.3.21, "not yet (starting)"
            # from 0.20.3.22). It, and any other caught the same way, is
            # judged by what a later reading says of it.
            starting = capsicum.starting_renderers(status) if self.strict() else set()
            still, latest = set(starting), status
            deadline = time.monotonic() + self.GRACE_SECONDS
            while still and time.monotonic() < deadline:
                time.sleep(0.5)
                again = self.read_sandbox_page(page)
                if again is None:
                    break
                latest = again
                still &= capsicum.unattested_renderers(latest)
        finally:
            self.browser.close_page(page)
        problems = capsicum.sandbox_page_problems(status, modes, self.strict(), starting)
        problems += [f"renderer pid {pid}: still not confined and attested "
                     f"{self.GRACE_SECONDS:g} s after the page first listed it"
                     for pid in sorted(still)]
        ended = latest["settings"].get("ended_total")
        if self.strict() and ended != "0":
            problems.append(f"the page counts {ended} renderers ended by the browser's check, "
                            "in a run where every renderer should have locked down")
        self.note("\n".join(
            [f"{r['kind']} pid {r['pid']}: page {r['mode']}, procstat "
             f"{ {True: 'yes', False: 'no', None: 'unreadable'}.get(modes.get(r['pid']), 'gone') }"
             f"; requested {r['requested']}, attested {r['attested']}" for r in status["rows"]]
            + [f"summary: {status['summary']}"
               + (f", starting {status['starting_count']}"
                  if status["starting_count"] is not None else "")]
            + [f"{k}: {v}" for k, v in sorted(status["settings"].items())]
            + ([f"renderers the page caught while they were starting: {sorted(starting)}; "
                + ("each was confined and attested, or gone, in a later reading" if not still
                   else f"still not there after {self.GRACE_SECONDS:g} s: {sorted(still)}")]
               if starting else [])
            + problems))
        self.assertEqual(problems, [], "beryllium://sandbox disagrees with the kernel "
                                       "or with itself (RT-17)")

    def test_lockdown_log(self):
        """What the lockdown wrote to the browser's log (shared by its
        children): with the lockdown requested, renderers must have reported
        capability mode, and no confined process may have received a
        descriptor the policy has no kind for (the receive path says so as it
        removes every right) or failed to limit one."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        # The whole log, not its end: one refusal anywhere in it fails the
        # gate. (Until 12 November 2026 this read the last 200 lines, which
        # from 0.20.3.13, the first build to log what the browser cuts, was
        # less than the log: three or four of some eight lockdown reports.)
        lines = self.browser.log_lines("beryllium-sandbox", limit=None)
        locked = capsicum.renderer_lockdown_lines(lines)
        received = [l for l in lines if "beryllium-sandbox: received" in l]
        failed = [l for l in lines if "could not" in l]
        # One line a pair. The first pair at each place in each process is
        # followed by a line with its call stack ("the first socket pair
        # made at ... came from frames"), which is not another pair: counted
        # as one until 12 November 2026, it doubled the number.
        made = [l for l in lines if "socket pair made" in l and "came from" not in l]
        makers = capsicum.socket_pair_makers(made)
        threads_at_lockdown = capsicum.threads_at_lockdown(locked)
        # The kernel's names for those threads, per renderer. Up to 0.20.3.16
        # they say nothing: this port's PlatformThread::SetName() never told
        # the kernel, so every thread carries the process's name, and
        # "beryllium,beryllium" is the main thread and one other. Which
        # other, ThreadsAtLockdown below finds from the stacks.
        name_sets = capsicum.thread_name_sets(capsicum.thread_names_at_lockdown(locked))
        names_note = ", ".join(f"{n} x [{names}]" for names, n in sorted(name_sets.items()))
        own_name = os.path.basename(DIRECT_BINARY)
        if name_sets and all(set(names.split(",")) <= {own_name} for names in name_sets):
            names_note += (" (the process's own name: this build gives its threads no "
                           "kernel names; see the ThreadsAtLockdown test for which they are)")
        cuts = capsicum.sent_cuts(lines)
        refused = [l for l in lines if "bound for confined renderer" in l and "every right removed" in l]
        # From 0.20.3.21: who cut (the browser, and the children that hold a
        # link to a renderer), and the browser's check of each renderer with
        # the kernel when its channel connects.
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        senders = capsicum.cuts_by_sender(lines, {p["id"]: p["type"] for p in procs})
        attested, ended = capsicum.attestations(lines)
        limits_off = [l for l in lines if "receive-side limits are off" in l]
        # From 0.20.3.22: what each renderer gave up at its lockdown besides
        # ambient authority (no new privileges, no core, no fork), and
        # whether it left itself traceable, which this class asks for.
        hardening = capsicum.hardening_at_lockdown(locked)
        hardening_problems = capsicum.hardening_problems(hardening, self.TRACEABLE)
        # From 0.20.3.22: the browser invites a renderer only once the
        # kernel says it has locked down, and nothing can have been sent to
        # it before that.
        invited = capsicum.invitations(lines)
        sent_early = capsicum.cuts_before_invitation(lines)
        # Why the thread count failed, if it did (0.20.3.14 logs the sysctl
        # error), and the stack trace behind the first socket pair at each
        # site and thread (one per renderer process; the first of each kind).
        thread_errors = [l for l in lines if "kern.proc.pid" in l]
        # 0.20.3.15 logs return addresses as module+offset, named here with
        # llvm-symbolizer on the installed binary; 0.20.3.14 logged a stack
        # trace that was empty (no unwind tables in the official build).
        traces = capsicum.describe_frames(capsicum.frames_logged(lines), DIRECT_BINARY)
        if not traces:
            seen_sites = set()
            for block in self.browser.log_context("came from:", after=18, limit=40):
                site = block.split("came from:")[0].split("made at", 1)[-1]
                if site not in seen_sites:
                    seen_sites.add(site)
                    traces.append(block)
        self.note(f"{len(lines)} lines of the lockdown's log read, all of it: "
                  f"{len(locked)} lockdown reports, {len(received)} received descriptors "
                  f"outside the policy, {len(failed)} failures, {len(made)} socket pairs made "
                  f"by confined processes" + (f": {makers}" if makers else "")
                  + (f"\nthreads at the lockdown point: {threads_at_lockdown}"
                     + (f"; the kernel's names for them, per renderer: {names_note}"
                        if names_note else "")
                     if threads_at_lockdown else "")
                  + f"\ndescriptors the browser cut before sending, per renderer: {cuts or 'none'}"
                  + (f"; refused outright: {len(refused)}" if refused else "")
                  + f"\ncuts by the process that made them: {senders or 'none'}"
                  + f"\nrenderers the kernel attested when they connected: {len(attested)}"
                  + (f"; ended by that check: {ended}" if ended else "")
                  + (f"\nrenderers invited once in capability mode: {len(invited)}; "
                     f"milliseconds from launch to that: {capsicum.spread(invited.values())}"
                     + (f"; descriptors cut for a renderer before its invitation: {sent_early}"
                        if sent_early else "") if invited else "")
                  + ("\nwhat each lockdown set besides capability mode: "
                     + "; ".join(f"{n} x [{h}]" for h, n in sorted(collections.Counter(
                         ",".join(v) or "-" for v in hardening.values()).items()))
                     + " (this class asks for traceable renderers, so that procstat can "
                       "read their descriptors)" if hardening else "") + "\n"
                  + "\n".join((received + failed + refused + made[:10])[:60])
                  + (("\nthread count errors:\n" + "\n".join(thread_errors[:6])) if thread_errors else "")
                  + (("\nwhere the socket pairs are made:\n" + "\n".join(traces)) if traces else ""))
        if self.strict():
            self.assertTrue(locked, "no renderer reported its lockdown in the browser log")
            self.assertEqual(received + failed, [],
                             "the lockdown logged received descriptors outside the policy, "
                             "or failures")
            # The sweep is single-threaded by Chromium's ordering (RendererMain
            # locks down before RenderThreadImpl exists); from 0.20.3.13 the
            # lockdown records the thread count, and this checks the claim.
            if threads_at_lockdown:
                self.assertEqual(set(threads_at_lockdown), {1},
                                 "a renderer had other threads at its lockdown point"
                                 + (f" (kernel names: {names_note})" if names_note else "")
                                 + ", or the count could not be read (-1):\n"
                                 + "\n".join(thread_errors[:6]))
                # The same builds carry the sender's side (S-IPC-01): the
                # browser must have cut something before sending to its
                # confined renderers.
                self.assertTrue(cuts, "the browser cut no descriptor before sending it to a "
                                      "confined renderer (is --vmodule=capsicum_rights=1 on?)")
                self.assertEqual(refused, [], "the browser sent a confined renderer a descriptor "
                                              "the policy has no kind for")
            # From 0.20.3.21 the browser asks the kernel about every renderer
            # it launched with the lockdown on. A build that writes these
            # lines must have attested every renderer that reported its own
            # lockdown, and ended none.
            if attested or ended:
                self.assertEqual(ended, {}, "the browser ended renderers the kernel did not "
                                            "attest, in a run where every renderer should "
                                            "have locked down")
                missing = sorted(set(capsicum.locked_pids(locked)) - set(attested))
                if missing:
                    # A renderer reports its lockdown a moment before its
                    # channel connects, which is when the browser checks.
                    time.sleep(1.5)
                    again = self.browser.log_lines("beryllium-sandbox", limit=None)
                    missing = sorted(set(missing) - set(capsicum.attestations(again)[0]))
                self.assertEqual(missing, [], "renderers that reported their lockdown and "
                                              "were not attested by the browser's check")
            self.assertEqual(limits_off, [], "a renderer ran with its receive-side limits "
                                             "off in the ordinary gate")
            # From 0.20.3.22 a renderer is invited only after its lockdown.
            # A build that writes the invitation lines must have invited
            # every renderer it attested, and sent none of them a descriptor
            # before.
            if invited:
                self.assertEqual(sorted(set(attested) - set(invited)), [],
                                 "renderers the browser attested and had not invited after "
                                 "their lockdown")
                self.assertEqual(sent_early, {}, "descriptors the browser cut for a renderer "
                                                 "before it invited that renderer")
            elif attested:
                version = capsicum.installed_version()
                if version and version >= BUILD_22:
                    self.fail("the browser attested renderers and wrote no line about "
                              "inviting them after their lockdown, on a build that should "
                              "(is BerylliumInviteAfterLockdown off?)")
            # From 0.20.3.22 every lockdown line says what else was set.
            if locked and not hardening:
                version = capsicum.installed_version()
                if version and version >= BUILD_22:
                    self.fail("no lockdown line says what the renderer gave up besides "
                              "ambient authority (hardening=), on a build that should")
            self.assertEqual(hardening_problems, [],
                             "a renderer's lockdown did not set what it should have")

    def test_renderer_shared_memory_is_anonymous_and_limited(self):
        """Renderers hold shared memory only as memfd objects, none of which
        can be truncated, mapped executable or changed (S-SHM-01, S-SHM-02)."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        problems, read, objects, lines = [], 0, 0, []
        for p in procs:
            if p["type"] != "renderer":
                continue
            caps = capsicum.rights(p["id"])
            if caps:
                read += 1
            shm = {fd: r for fd, r in caps.items() if r["type"] == "h"}
            objects += len(shm)
            lines += [f"renderer {p['id']}: fd {fd} {r['name'] or '-'} "
                      f"[{capsicum.rights_summary(r['rights'])}]"
                      for fd, r in sorted(shm.items(), key=lambda kv: int(kv[0]))]
            problems += [f"renderer {p['id']}: {x}"
                         for x in capsicum.shared_memory_problems(caps)]
        if not read:
            self.unavailable("procstat could not read renderer descriptors "
                             "(security.bsd.unprivileged_proc_debug=0?)")
        self.note("\n".join(lines) or f"{read} renderers: no shared memory objects")
        self.assertGreater(objects, 0, "no renderer holds a shared memory object: "
                           "is shared memory still kept as files in TMPDIR?")
        self.assertEqual(problems, [], "shared memory descriptors with too many rights")


class ThreadsAtLockdown(BrowserTest):
    """Which threads a renderer has at its lockdown point, from their stacks.
    The descriptor sweep there is complete only if no other thread can make
    or receive a descriptor meanwhile, and the lockdown has counted two
    threads since 0.20.3.15. A renderer started with
    --renderer-startup-dialog pauses when RendererMain begins; lldb lists
    its threads, runs it on to the lockdown's marker and lists them again.
    A record, not a gate: the count is checked in test_lockdown_log."""

    NEEDS_FREEBSD = True
    # The debugger is attached before the lockdown; from 0.20.3.22 the
    # lockdown refuses to go on in a traced renderer unless it was asked to
    # stay traceable.
    BROWSER_ARGS = ("--renderer-startup-dialog", capsicum.TRACEABLE_SWITCH)

    def paused_renderers(self, wait=20):
        deadline = time.monotonic() + wait
        while True:
            pids = [int(m.group(1)) for l in self.browser.log_lines("paused waiting for debugger")
                    for m in [capsicum.PAUSED.search(l)] if m]
            if pids or time.monotonic() > deadline:
                return pids
            time.sleep(0.5)

    def test_threads_at_the_lockdown_point(self):
        """Every thread of one renderer, when RendererMain begins and at the
        lockdown, with where each was started and what it waits in."""
        if not shutil.which("lldb"):
            self.skipTest("no lldb to read the threads' stacks")
        pids = self.paused_renderers()
        if not pids:
            self.skipTest("no renderer paused for --renderer-startup-dialog")
        pid = pids[0]
        try:
            text = capsicum.run_to_lockdown(pid)
        finally:
            for other in self.paused_renderers(wait=0):
                try:
                    os.kill(other, signal.SIGUSR1)  # let the rest start as well
                except OSError:
                    pass
        with open(self.ctx.artifact("threads-at-lockdown.txt"), "w") as f:
            f.write(text)
        dumps, images = capsicum.parse_lldb(text)
        moments = ["when RendererMain begins (paused by --renderer-startup-dialog)",
                   "at the lockdown point (stopped at the lockdown's utrace marker or cap_enter)"]
        lines = [f"renderer {pid} under lldb; its whole output is threads-at-lockdown.txt"]
        for moment, dump in zip(moments, dumps):
            lines.append(f"{moment}: {len(dump)} thread(s)")
            lines += ["  " + l for l in capsicum.describe_dump(dump, images, DIRECT_BINARY)]
        if len(dumps) < 2:
            lines.append("lldb did not get as far as the lockdown; the end of its output:")
            lines += ["  " + l for l in text.splitlines()[-12:]]
        self.note("\n".join(lines))



class SenderAlone(Gate):
    """The lockdown on and the receiver's half off (BerylliumReceiveSideLimits
    disabled, from 0.20.3.21): a confined renderer does nothing to what it
    receives, as a renderer that had been taken over would not. Every
    descriptor of every renderer must still be inside the policy, which
    holds only if every sender cuts: the browser, the GPU process, the
    network service and the storage service (S-IPC-01, review finding
    BER-05). A survey without the lockdown has nothing to show here."""

    BROWSER_ARGS = Gate.BROWSER_ARGS + ("--disable-features=BerylliumReceiveSideLimits",)

    def test_the_senders_cut_alone_keeps_the_policy(self):
        if not self.strict():
            self.skipTest("the lockdown was not requested (run --lockdown)")
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        time.sleep(1.0)
        lines = self.browser.log_lines("beryllium-sandbox", limit=None)
        off = [l for l in lines if "receive-side limits are off" in l]
        if not off:
            # No renderer said its limits are off: the build has no such
            # switch, or it did not take, and the test below would pass for
            # the wrong reason.
            self.older_build("no renderer reported its receive-side limits off")
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        senders = capsicum.cuts_by_sender(lines, {p["id"]: p["type"] for p in procs})
        self.note(f"renderers that said their receive-side limits are off: {len(off)}"
                  f"\ncuts by the process that made them: {senders or 'none'}")
        self.descriptors_follow_the_policy()


class Untraceable(Gate):
    """The default from 0.20.3.22: at its lockdown a renderer disables
    tracing of itself (PROC_TRACE_CTL, S-HRD-01), so that another process
    of the same user cannot attach a debugger to it, ktrace it or read its
    descriptor table. The other sandbox classes ask for traceable renderers
    in order to read those tables; this one does not, and requires that it
    cannot read them. What the kernel says of the process's capability
    mode stays readable, and is checked."""

    BROWSER_ARGS = ("--vmodule=capsicum_rights=1",)
    TRACEABLE = False

    def test_a_locked_down_renderer_cannot_be_read(self):
        if not self.strict():
            self.skipTest("the lockdown was not requested (run --lockdown)")
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        renderers = [p["id"] for p in procs if p["type"] == "renderer"]
        modes = self.renderer_modes(procs)
        lines = self.browser.log_lines("beryllium-sandbox", limit=None)
        hardening = capsicum.hardening_at_lockdown(lines)
        if not hardening:
            self.before_build_22("no lockdown line says what the renderer gave up (hardening=)")
        browser_pid = next((p["id"] for p in procs if p["type"] == "browser"), None)
        own = len(capsicum.rights(browser_pid)) if browser_pid else 0
        readable = {pid: len(capsicum.rights(pid)) for pid in renderers
                    if modes.get(pid) is True}
        self.note(f"the browser's own descriptors read by procstat: {own}"
                  + "\n" + "\n".join(
                      f"renderer {pid}: capability mode "
                      f"{ {True: 'yes', False: 'no', None: 'unreadable'}.get(modes.get(pid), 'gone') }"
                      f"; lockdown set {','.join(hardening.get(pid, [])) or 'nothing recorded'}"
                      f"; descriptors procstat could read: {readable.get(pid, 'not asked')}"
                      for pid in renderers))
        self.assertEqual(self.unconfined(modes), {},
                         "renderers not in capability mode although the lockdown was requested")
        if not own:
            # Nothing is readable on this machine, so an unreadable renderer
            # would show nothing about the renderer.
            self.unavailable("procstat cannot read the browser's own descriptors "
                             "(security.bsd.unprivileged_proc_debug=0?), so this run cannot "
                             "tell a renderer that refuses to be read from one nobody may read")
        problems = capsicum.hardening_problems(
            {pid: h for pid, h in hardening.items() if pid in renderers}, traceable=False)
        problems += [f"renderer pid {pid}: procstat read {n} of its descriptors, although "
                     "its lockdown disabled tracing" for pid, n in sorted(readable.items()) if n]
        self.assertTrue(readable, "no confined renderer to try")
        self.assertEqual(problems, [], "a locked-down renderer can still be read by another "
                                       "process of the same user")


class TrapReport(Gate):
    """Nothing is refused after the lockdown (plan/18 section 3.2, P2). With
    BerylliumCapsicumTrap the kernel traps every call capability mode
    refuses a renderer, and from 0.20.3.22 the renderer writes a line for
    each, with the code that made the call, and goes on. Every survey up to
    0.20.3.21 showed one such call, cpuset_getaffinity, which 0.20.3.22
    answers before the lockdown. Under the gate any line fails, and names
    what reached for what. Before 0.20.3.22 the switch ended a renderer at
    its first refused call, so the class is skipped there."""

    BROWSER_ARGS = Gate.BROWSER_ARGS + ("--enable-features=BerylliumCapsicumTrap",)
    # Long enough for a page's workers and timers to have run.
    SETTLE_SECONDS = 4.0

    @classmethod
    def setUpClass(cls):
        version = capsicum.installed_version()
        if version and version < BUILD_22:
            raise unittest.SkipTest("the trap switch ends a renderer at its first refused "
                                    "call before 0.20.3.22, which reports instead")
        super().setUpClass()

    def test_nothing_is_refused_after_the_lockdown(self):
        if not self.strict():
            self.skipTest("the lockdown was not requested (run --lockdown)")
        fixtures = self.ctx.fixtures()
        for name in ("busy.html", "text.html"):
            self.browser.new_page(fixtures.url(name))
        clips, _ = self.ctx.media()
        for clip in ("h264_aac.mp4", "vp9_opus.webm"):
            if clip in clips:
                self.browser.new_page(self.ctx.add_fixture(
                    f"trap-video-{clip}.html",
                    f'<!doctype html><title>video</title><video src="{clip}" '
                    'autoplay muted loop width="320"></video>'))
        time.sleep(self.SETTLE_SECONDS)
        lines = self.browser.log_lines("beryllium-sandbox", limit=None)
        reporting = [int(m.group(1)) for m in map(capsicum.TRAP_REPORTING_RE.search, lines) if m]
        calls = capsicum.refused_calls(lines)
        described = capsicum.describe_refused(calls, DIRECT_BINARY)
        self.note(f"renderers that report refused calls: {len(reporting)}; refused calls "
                  f"reported: {len(calls)}"
                  + ("\n" + "\n".join(described) if described else ""))
        if not reporting:
            self.before_build_22("no renderer said that it reports refused calls "
                                 "(BerylliumCapsicumTrap)")
        self.assertEqual(described, [], "calls capability mode refused a renderer after its "
                                        "lockdown, with the code that made each")


class ConfinedUtilities(Gate):
    """Utility services locked down as renderers are (from 0.20.3.22, an
    experiment behind BerylliumCapsicumUtilities; S-PRC-01). The browser
    tells a service on its list to lock down, cuts what it sends it, and
    sends it nothing until the kernel says capability mode. Which services
    can stand it is not known yet: none has been surveyed after its start.
    So this class records, with the trap report on, which of them started,
    whether each locked down, and every call each was refused, with the
    code that made it. It fails only on what is wrong whatever the answer:
    a utility that says it locked down and is not in capability mode by
    the kernel, or one the browser invited before that."""

    BROWSER_ARGS = Gate.BROWSER_ARGS + (
        "--enable-features=BerylliumCapsicumUtilities,BerylliumCapsicumTrap",)
    SETTLE_SECONDS = 4.0

    @classmethod
    def setUpClass(cls):
        version = capsicum.installed_version()
        if version and version < BUILD_22:
            raise unittest.SkipTest("utility services are confined from 0.20.3.22, and the "
                                    "trap switch ends a process at its first refused call "
                                    "before that")
        super().setUpClass()

    def test_confined_utilities_are_confined(self):
        if not self.strict():
            self.skipTest("the lockdown was not requested (run --lockdown)")
        fixtures = self.ctx.fixtures()
        for name in ("busy.html", "text.html"):
            self.browser.new_page(fixtures.url(name))
        # A page that names a search description makes the browser fetch it
        # and parse its XML in the data decoder service, where that is not
        # switched off.
        self.ctx.add_fixture("osdd.xml", OPENSEARCH_DESCRIPTION)
        self.browser.new_page(self.ctx.add_fixture(
            "osdd.html", '<!doctype html><title>search</title><link rel="search" '
            'type="application/opensearchdescription+xml" title="t" href="osdd.xml">'))
        time.sleep(self.SETTLE_SECONDS)
        lines = self.browser.log_lines("beryllium-sandbox", limit=None)
        locked, failed, ended = capsicum.confined_utilities(lines)
        modes = capsicum.capability_modes(sorted(locked)) if locked else {}
        calls = [c for c in capsicum.refused_calls(lines) if c["pid"] in locked]
        described = capsicum.describe_refused(calls, DIRECT_BINARY)
        word = {True: "yes", False: "no", None: "unreadable"}
        self.note(
            "\n".join(
                [f"utility {pid} ({u['service']}): locked down with {u['threads']} threads; "
                 f"capability mode by procstat: {word.get(modes.get(pid), 'gone')}; invited "
                 + (f"{u['invited_ms']} ms after its launch" if u["invited_ms"] is not None
                    else "with no line saying when")
                 for pid, u in sorted(locked.items())]
                + [f"utility {pid}: ended at its lockdown: {why}" for pid, why in
                   sorted(failed.items())]
                + [f"utility {pid}: ended by the browser before it was sent anything"
                   for pid in sorted(ended)]
                + (["what the confined utilities were refused:"] + described if described
                   else [])) or "no utility service on the browser's list started in this run")
        if not locked and not failed and not ended:
            self.skipTest("no utility service on the browser's list started in this run, "
                          "so there is nothing to check")
        problems = [f"utility {pid} ({u['service']}) says it locked down and procstat says "
                    f"capability mode {word.get(modes.get(pid))}"
                    for pid, u in sorted(locked.items())
                    if modes.get(pid) is not True and modes.get(pid) != "gone"]
        problems += [f"utility {pid} ({u['service']}) locked down and no line says the browser "
                     "invited it after that" for pid, u in sorted(locked.items())
                     if u["invited_ms"] is None]
        self.assertEqual(problems, [], "a utility service the browser confines is not "
                                       "confined as the browser believes")


OPENSEARCH_DESCRIPTION = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
    "<ShortName>Beryllium test</ShortName><Description>A search description for the "
    "sandbox tests</Description>"
    '<Url type="text/html" template="http://127.0.0.1/?q={searchTerms}"/>'
    "</OpenSearchDescription>")


class UnconfinedRenderer(BrowserTest):
    """A renderer that does not lock down while the browser expects it to
    (from 0.20.3.21, S-STA-01). --no-sandbox makes RendererMain skip the
    lockdown; with the lockdown feature on, the browser still registers the
    renderer as a confined peer, asks the kernel when its channel connects,
    is told no, and ends it. The page must never be usable."""

    NEEDS_FREEBSD = True
    BROWSER_ARGS = ("--no-sandbox",)

    def test_an_unconfined_renderer_is_ended(self):
        if not capsicum.lockdown_requested(self.ctx.options):
            self.skipTest("the lockdown was not requested (run --lockdown)")
        answered, problem = None, ""
        try:
            page = self.browser.new_page(self.ctx.fixtures().url("busy.html"), timeout=20)
            time.sleep(1.0)
            answered = page.eval("document.title", timeout=10)
        except (TargetCrashed, CDPError) as e:
            problem = f"{type(e).__name__}: {e}"
        lines = self.browser.log_lines("beryllium-sandbox", limit=None)
        attested, ended = capsicum.attestations(lines)
        uninvited = capsicum.ended_uninvited(lines)
        self.note(f"renderers ended by the browser's check: {ended or 'none'}; attested: "
                  f"{attested or 'none'}; ended before they were sent anything: "
                  f"{sorted(uninvited) or 'none'}; the page: "
                  + (f"answered a script with {answered!r}" if problem == "" else problem))
        if not attested and not ended:
            version = capsicum.installed_version()
            if version and version < BUILD_21:
                self.skipTest("this build does not ask the kernel about its renderers "
                              "(the check comes with 0.20.3.21)")
            self.fail("the browser wrote nothing about checking its renderers with the kernel")
        self.assertTrue(ended, "no renderer was ended, although none could lock down")
        self.assertEqual(attested, [], "a renderer was attested with --no-sandbox, where "
                                       "RendererMain skips the lockdown")
        self.assertNotEqual(problem, "", "a page in a renderer that never locked down "
                                         f"answered a script ({answered!r})")
        # From 0.20.3.22 such a renderer is ended before the browser has sent
        # it anything; 0.20.3.21 ended it when its channel connected, after
        # the invitation and whatever was queued behind it.
        version = capsicum.installed_version()
        if uninvited or (version and version >= BUILD_22):
            self.assertEqual(sorted(set(ended) - uninvited), [],
                             "renderers the browser ended only after it had sent them "
                             "its invitation")

