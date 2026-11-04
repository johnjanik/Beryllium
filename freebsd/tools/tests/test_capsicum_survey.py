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
 4242 beryllium        datasize           8589934592       8589934592
 4242 beryllium        coredumpsize                0                0
"""


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
        self.assertEqual(capsicum.limits(4242, PROCSTAT_L)["coredumpsize"], ("0", "0"))

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
                          "env": ["HOME"], "limits": {}},
                   9999: {"pid": 9999, "type": "utility", "workloads": ["pdf"],
                          "fds": [], "env": [], "limits": {}}}
        text = capsicum.report(summary, samples, "oracle-16.0-CURRENT-20261101.json")
        self.assertLess(text.index("== renderer"), text.index("== gpu"))
        self.assertIn("vm.stats.vm.v_page_count  REFUSED in capability mode", text)
        self.assertIn("hw.ncpu  ok", text)
        self.assertIn("resources.pak", text)
        self.assertIn("== utility (1 processes)", text)  # sampled, no trace lines


if __name__ == "__main__":
    unittest.main()
