# SPDX-License-Identifier: GPL-3.0-only
"""Sandbox status (RT-17): what the browser claims against what the kernel
says. Lists every Beryllium process and whether it is in Capsicum
capability mode (procstat -s shows C in FLAGS)."""

import subprocess

from berytest import capsicum
from berytest.base import BrowserTest


def capability_mode(pid):
    """True/False from procstat -s, None if it cannot be read."""
    try:
        out = subprocess.run(["procstat", "-s", str(pid)], capture_output=True,
                             text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if len(out) < 2:
        return None
    header, row = out[0].split(), out[1].split()
    if "FLAGS" not in header or len(row) < len(header):
        return None
    return "C" in row[header.index("FLAGS")]


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
    NEEDS_FREEBSD = True

    def test_capability_mode_per_process(self):
        """Every process's capability mode, from the kernel."""
        self.browser.new_page(self.ctx.fixtures().url("busy.html"))
        procs = self.browser.conn.send("SystemInfo.getProcessInfo")["processInfo"]
        rows = [(p["type"], p["id"], capability_mode(p["id"])) for p in procs]
        self.note("\n".join(f"{t:<10} pid {pid:<7} capability mode: "
                            f"{'yes' if c else 'no' if c is False else 'unknown'}"
                            for t, pid, c in rows))
        self.assertTrue(any(c is not None for _, _, c in rows), "procstat gave no answer")

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
            self.skipTest("procstat could not read renderer descriptors "
                          "(security.bsd.unprivileged_proc_debug=0?)")
        self.note("\n".join(details) or f"{read} renderers: none")
        self.assertEqual(problems, [], "renderers hold descriptors they must not")

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
            self.skipTest("procstat could not read renderer descriptors "
                          "(security.bsd.unprivileged_proc_debug=0?)")
        self.note("\n".join(lines) or f"{read} renderers: no shared memory objects")
        self.assertGreater(objects, 0, "no renderer holds a shared memory object: "
                           "is shared memory still kept as files in TMPDIR?")
        self.assertEqual(problems, [], "shared memory descriptors with too many rights")
