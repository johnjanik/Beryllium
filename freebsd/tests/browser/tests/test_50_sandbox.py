# SPDX-License-Identifier: GPL-3.0-only
"""Sandbox status (RT-17): what the browser claims against what the kernel
says. Lists every Beryllium process and whether it is in Capsicum
capability mode (procstat -s shows C in FLAGS)."""

from berytest import capsicum
from berytest.base import BrowserTest


capability_mode = capsicum.capability_mode


class Processes(BrowserTest):
    def test_process_list(self):
        """Record the browser's processes."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        self.note("\n".join(f"{p['type']:<10} pid {p['id']}" for p in procs))
        types = {p["type"] for p in procs}
        self.assertIn("browser", types)
        self.assertIn("renderer", types)


class SandboxHonesty(BrowserTest):
    """With the lockdown requested (lockdown_requested), these tests are a
    gate: every renderer must be confined and every observation must be
    available, or they fail. Otherwise they survey and skip."""

    NEEDS_FREEBSD = True

    def strict(self):
        return capsicum.lockdown_requested(self.ctx.options)

    def unavailable(self, why):
        """A missing observation: a failure under the gate, a skip otherwise."""
        if self.strict():
            self.fail(why + " (the lockdown was requested, so this is a failure)")
        self.skipTest(why)

    def test_capability_mode_per_process(self):
        """Every process's capability mode, from the kernel; with the lockdown
        requested, every renderer must be in it."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        rows = [(p["type"], p["id"], capability_mode(p["id"])) for p in procs]
        self.note("\n".join(f"{t:<10} pid {pid:<7} capability mode: "
                            f"{'yes' if c else 'no' if c is False else 'unknown'}"
                            for t, pid, c in rows))
        if not any(c is not None for _, _, c in rows):
            self.unavailable("procstat gave no answer")
        if self.strict():
            renderers = [(pid, c) for t, pid, c in rows if t == "renderer"]
            self.assertTrue(renderers, "no renderer to check")
            self.assertEqual([pid for pid, c in renderers if c is not True], [],
                             "renderers not in capability mode (or unreadable) "
                             "although the lockdown was requested")

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
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        renderers = [p for p in procs if p["type"] == "renderer"]
        modes = {p["id"]: capability_mode(p["id"]) for p in renderers}
        confined = [p for p in renderers if modes[p["id"]]]
        if self.strict():
            self.assertEqual([p["id"] for p in renderers if modes[p["id"]] is not True], [],
                             "renderers not in capability mode (or unreadable) "
                             "although the lockdown was requested")
        elif not confined:
            self.skipTest("no renderer in capability mode; run with "
                          "--browser-arg=--enable-features=BerylliumCapsicumRenderer")
        problems, lines, unread = [], [], []
        for p in confined:
            fds, caps = capsicum.descriptors(p["id"]), capsicum.rights(p["id"])
            if not caps:
                unread.append(p["id"])
                continue
            found = capsicum.policy_problems(fds, caps)
            problems += [f"renderer {p['id']}: {x}" for x in found]
            lines.append(f"renderer {p['id']}: {len(caps)} descriptors, "
                         f"{len(found)} outside the policy")
        if len(unread) == len(confined):
            self.unavailable("procstat could not read renderer descriptors "
                             "(security.bsd.unprivileged_proc_debug=0?)")
        if unread and self.strict():
            problems.append(f"descriptors unreadable for renderers {unread}")
        self.note("\n".join(lines + problems))
        self.assertEqual(problems, [], "confined renderers hold descriptors outside the policy")

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
