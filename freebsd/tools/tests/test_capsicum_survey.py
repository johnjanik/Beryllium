# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the browser suite's Capsicum survey parser
(freebsd/tests/browser/berytest/capsicum.py)."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests", "browser"))
from berytest import capsicum  # noqa: E402

KDUMP = """\
 4242 beryllium NAMI  "/usr/local/share/fonts/NotoSansCJK.ttc"
 4242 beryllium CAP   system call not allowed: openat
 4242 beryllium NAMI  "/usr/share/zoneinfo/UTC"
 4242 beryllium CAP   system call not allowed: openat
 4242 beryllium SCTL  "vm.stats.vm.v_page_count"
 4242 beryllium SCTL  "hw.ncpu"
 4242 100123 beryllium CAP   restricted VFS lookup: AT_FDCWD
 5151 beryllium CAP   system call not allowed: socket
 7777 beryllium CAP   system call not allowed: openat
 4242 beryllium CALL  read(0x3,0x1000,0x10)
garbage line
"""

PROCSTAT_F = """\
  PID COMM                FD T V FLAGS    REF  OFFSET PRO NAME
 4242 beryllium            0 v c r-------   1       0 -   /dev/null
 4242 beryllium            3 s - rw------   1       0 UDS 0 0
 4242 beryllium            9 v r r-------   1    4096 -   /usr/local/share/beryllium/resources.pak
"""
PROCSTAT_E = """\
  PID COMM             ENVIRONMENT
 4242 beryllium        HOME=/home/u DISPLAY=:0 TOKEN=a b=c LD_LIBRARY_PATH=/x
"""
PROCSTAT_L = """\
  PID COMM             RLIMIT                  SOFT             HARD
 4242 beryllium        datasize           4194304 KB       4194304 KB
 4242 beryllium        coredumpsize                0 B              0 B
 4242 beryllium        cputime              infinity         infinity
"""
# procstat -C -f: rights in short names, right-aligned, "-" for none; an
# unlimited descriptor lists every right (abridged here to the markers).
PROCSTAT_C = """\
  PID COMM                FD T FLAGS    CAPABILITIES                     PRO NAME
 4242 beryllium         text v r------- -                                -   /usr/local/share/beryllium/beryllium
 4242 beryllium            3 s rw------ rd,wr,se,mm,cr,fe,fy,ft,cd,cf,cm,cn,ct,fk UDS 0 0
 4242 beryllium           19 h rw------ rd,wr,se,mm,fc,fs,prd,pwr,mmr,mmw,mrw -   memfd:shared-memory-region
 4242 beryllium           24 h rw------     rd,se,mm,fc,fs,prd,mmr -   memfd:shared-memory-region
 4242 beryllium           25 h rw------ rd,wr,se,mm,fe,fy,ft,cd,cm,cn,ct,fk,mmx -   anon
 4242 beryllium            9 v r------- -                                -   /usr/local/share/beryllium/resources.pak
"""
MARKER_HEX = " ".join(f"{b:02x}" for b in b"BERYLLIUM-LOCKDOWN")
KDUMP_MARKED = f"""\
 6000 beryllium NAMI  "/libexec/ld-elf.so.1"
 6000 beryllium CAP   system call not allowed: open
 6000 beryllium SCTL  "kern.proc.pid.6000"
 6000 beryllium USER  18  {MARKER_HEX}
 6000 beryllium NAMI  "/etc/localtime"
 6000 beryllium CAP   system call not allowed: __realpathat
 6000 beryllium CAP   cpuset_getaffinity: restricted cpuset operation
 6000 beryllium SCTL  "vm.stats.vm.v_page_count"
 6000 beryllium SCTL  "sysctl.name.1.30.214748238"
"""


class Marker(unittest.TestCase):
    def test_split_at_lockdown_marker(self):
        p = capsicum.parse_kdump(KDUMP_MARKED.splitlines())[6000]
        self.assertTrue(p["marker"])
        self.assertEqual(p["cap"]["system call not allowed: open"], 1)
        self.assertNotIn("system call not allowed: open", p["cap_after"])
        self.assertEqual(p["cap_after"]["system call not allowed: __realpathat"], 1)
        self.assertEqual(dict(p["sysctl_after"]),
                         {"vm.stats.vm.v_page_count": 1, "sysctl.name.<oid>": 1})
        self.assertIn("kern.proc.pid.<pid>", p["sysctl"])

    def test_paths_per_phase(self):
        p = capsicum.parse_kdump(KDUMP_MARKED.splitlines())[6000]
        self.assertEqual(p["cap_paths_before"]["system call not allowed: open"],
                         ["/libexec/ld-elf.so.1"])
        self.assertNotIn("system call not allowed: open", p["cap_paths_after"])
        self.assertEqual(p["cap_paths_after"]["system call not allowed: __realpathat"],
                         ["/etc/localtime"])

    def test_paths_only_for_lookups(self):
        p = capsicum.parse_kdump(KDUMP_MARKED.splitlines())[6000]
        self.assertEqual(p["cap_paths"]["system call not allowed: __realpathat"],
                         ["/etc/localtime"])
        self.assertEqual(p["cap_paths"].get("cpuset_getaffinity: restricted cpuset operation"), [])

    def test_report_with_marker(self):
        procs = capsicum.parse_kdump(KDUMP_MARKED.splitlines())
        summary = capsicum.summarise(procs, {6000: "renderer"}, readable={"hw.ncpu"})
        text = capsicum.report(summary, {}, "oracle-16.0-CURRENT-20261101.json")
        self.assertIn("1 of these processes wrote the lockdown marker", text)
        after = text.index("AFTER the lockdown point")
        before = text.index("Before the lockdown point")
        self.assertLess(after, before)
        self.assertIn("__realpathat", text[after:before])
        self.assertIn("system call not allowed: open", text[before:])

    def test_marker_decoding(self):
        self.assertTrue(capsicum.is_marker(f"18  {MARKER_HEX}"))
        self.assertTrue(capsicum.is_marker('"BERYLLIUM-LOCKDOWN"'))
        self.assertFalse(capsicum.is_marker("4  de ad be ef"))
        self.assertFalse(capsicum.is_marker("RTLD: dlopen"))


class Parse(unittest.TestCase):
    def test_kdump(self):
        procs = capsicum.parse_kdump(KDUMP.splitlines())
        self.assertEqual(sorted(procs), [4242, 5151, 7777])
        p = procs[4242]
        self.assertEqual(p["cap"]["system call not allowed: openat"], 2)
        self.assertEqual(p["cap_paths"]["system call not allowed: openat"],
                         ["/usr/local/share/fonts/NotoSansCJK.ttc", "/usr/share/zoneinfo/UTC"])
        self.assertEqual(p["cap"]["restricted VFS lookup: AT_FDCWD"], 1)  # with a thread id
        self.assertEqual(dict(p["sysctl"]), {"vm.stats.vm.v_page_count": 1, "hw.ncpu": 1})
        self.assertEqual(p["lookups"], 2)

    def test_procstat_views(self):
        fds = capsicum.descriptors(4242, PROCSTAT_F)
        self.assertEqual([d["fd"] for d in fds], ["0", "3", "9"])
        self.assertEqual(fds[2]["name"], "/usr/local/share/beryllium/resources.pak")
        self.assertEqual(fds[1]["type"], "s")
        self.assertEqual(capsicum.environment_names(4242, PROCSTAT_E),
                         ["DISPLAY", "HOME", "LD_LIBRARY_PATH", "TOKEN", "b"])
        lim = capsicum.limits(4242, PROCSTAT_L)
        self.assertEqual(lim["coredumpsize"], ("0 B", "0 B"))
        self.assertEqual(lim["datasize"], ("4194304 KB", "4194304 KB"))
        self.assertEqual(lim["cputime"], ("infinity", "infinity"))

    def test_risky_descriptors(self):
        text = (PROCSTAT_F
                + " 4242 beryllium           20 v d r-------   1       0 -   /\n"
                + " 4242 beryllium           64 v r -w------   1       0 -   /home/u/.config/beryllium/LOG\n"
                + " 4242 beryllium            2 v r -w------   1       0 -   /tmp/stderr.log\n"
                + " 4242 beryllium         root v d r-------   -       - -   /\n")
        risky = capsicum.risky_descriptors(capsicum.descriptors(4242, text))
        self.assertEqual(risky, ["fd 20 directory /",
                                 "fd 64 writable file /home/u/.config/beryllium/LOG"])

    def test_unnamed_writable_file_is_called_unlinked(self):
        text = PROCSTAT_F + " 4242 beryllium           21 v r rw------   1       0 -   -                 \n"
        self.assertEqual(capsicum.risky_descriptors(capsicum.descriptors(4242, text)),
                         ["fd 21 writable file with no name (unlinked)"])

    def test_rights(self):
        r = capsicum.rights(4242, PROCSTAT_C)
        self.assertEqual(sorted(r, key=int), ["3", "9", "19", "24", "25"])  # no "text"
        self.assertEqual(r["19"]["type"], "h")
        self.assertEqual(r["19"]["name"], "memfd:shared-memory-region")
        self.assertIn("mrw", r["19"]["rights"])
        self.assertEqual(r["9"]["rights"], [])
        self.assertEqual(capsicum.rights_summary(r["3"]["rights"]), "all")
        self.assertEqual(capsicum.rights_summary(r["24"]["rights"]), "rd,se,mm,fc,fs,prd,mmr")
        self.assertEqual(capsicum.rights_summary([]), "none")

    def test_shared_memory_problems(self):
        problems = capsicum.shared_memory_problems(capsicum.rights(4242, PROCSTAT_C))
        # 19 (writable, limited) and 24 (read-only twin) pass; 3 is a socket.
        self.assertEqual(problems, ["fd 25 shared memory can truncate, map executable, "
                                    "execute, chmod, chown (rights: all)"])

    def test_environment_values_never_kept(self):
        names = capsicum.environment_names(4242, PROCSTAT_E)
        self.assertNotIn("/home/u", " ".join(names))

    def test_readable_sysctls_by_kernel_major(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "oracle-16.0-CURRENT-20261101.json"), "w") as f:
                json.dump({"caprd_sysctls": {"readable": ["hw.ncpu", "kern.ostype"]}}, f)
            readable, source = capsicum.readable_sysctls(d, "16.0-CURRENT")
            self.assertEqual(readable, {"hw.ncpu", "kern.ostype"})
            self.assertEqual(source, "oracle-16.0-CURRENT-20261101.json")
            self.assertEqual(capsicum.readable_sysctls(d, "15.1-RELEASE"), (None, None))

    def test_summary_and_report(self):
        procs = capsicum.parse_kdump(KDUMP.splitlines())
        types = {4242: "renderer", 5151: "gpu", 7777: "browser"}
        summary = capsicum.summarise(procs, types, readable={"hw.ncpu"})
        self.assertNotIn("browser", summary)
        self.assertEqual(summary["renderer"]["sysctl_blocked"], ["vm.stats.vm.v_page_count"])
        samples = {4242: {"pid": 4242, "type": "renderer", "workloads": ["text"],
                          "fds": capsicum.descriptors(4242, PROCSTAT_F),
                          "rights": capsicum.rights(4242, PROCSTAT_C),
                          "env": ["HOME"], "limits": {}},
                   9999: {"pid": 9999, "type": "utility", "workloads": ["pdf"],
                          "fds": [], "env": [], "limits": {}}}
        text = capsicum.report(summary, samples, "oracle-16.0-CURRENT-20261101.json")
        self.assertLess(text.index("== renderer"), text.index("== gpu"))
        self.assertIn("vm.stats.vm.v_page_count  REFUSED in capability mode", text)
        self.assertIn("hw.ncpu  ok", text)
        self.assertIn("resources.pak  [none]", text)
        self.assertIn("0 0  [all]", text)
        self.assertIn("== utility (1 processes)", text)  # sampled, no trace lines


if __name__ == "__main__":
    unittest.main()
