# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the browser suite's Capsicum survey parser
(freebsd/tests/browser/berytest/capsicum.py)."""

import json
import os
import sys
import tempfile
import unittest
import unittest.mock

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
# fstat -p: vnodes have FD MOUNT INUM MODE SZ R/W; sockets and pipes do not.
FSTAT = """\
USER     CMD          PID   FD MOUNT      INUM MODE         SZ|DV R/W
john     beryllium   4242 text /usr/local 77001 -r-xr-xr-x 210000000  r
john     beryllium   4242    0 /dev          25 crw-rw-rw-     null  r
john     beryllium   4242    4* local stream fffff80012345678 <-> fffff80012345000
john     beryllium   4242   13* local stream fffff80012340013 <-> fffff80012340018
john     beryllium   4242   18* local stream fffff80012340018 <-> fffff80012340013
john     beryllium   4242   19* local seqpak fffff80012340019
john     beryllium   4242   20* local dgram fffff80012340020 -> fffff80012349999
john     beryllium   4242   21 /tmp       99123 -rw-------  2097152 rw
"""
FSTAT_BROWSER = """\
USER     CMD          PID   FD MOUNT      INUM MODE         SZ|DV R/W
john     beryllium   7777   88* local stream fffff80012345000 <-> fffff80012345678
"""
KDUMP_TEMP = """\
 7777 beryllium NAMI  "/tmp/.org.chromium.Chromium.a1B2c3"
 7777 beryllium NAMI  "/tmp/.org.chromium.Chromium.Zz9Yy8"
 5151 beryllium NAMI  "/tmp/.glAJD8Uk"
 4242 beryllium NAMI  "/tmp/berytest.abc/home/.config/beryllium/Local State"
 4242 beryllium NAMI  "/usr/local/share/beryllium/resources.pak"
 4242 beryllium NAMI  "/tmp"
"""
# A confined renderer after the lockdown, as procstat -f and -C show it.
CONFINED_F = """\
  PID COMM                FD T V FLAGS    REF  OFFSET PRO NAME
 5000 beryllium            0 v c r-------   1       0 -   /dev/null
 5000 beryllium            3 v r r-------   1    4096 -   /usr/local/share/beryllium/resources.pak
 5000 beryllium            4 s - rw------   1       0 UDS 0 0
 5000 beryllium            6 k - rw------   1       0 -   -
 5000 beryllium            7 E - rw---n--   1       0 -   -
 5000 beryllium           12 h - rw------   1       0 -   -
 5000 beryllium           40 v r rw------   1       0 -   /home/u/.config/beryllium/Default/Cookies
 5000 beryllium           41 v r r-------   1       0 -   /etc/passwd
 5000 beryllium           42 v c rw------   1       0 -   /dev/dri/renderD128
 5000 beryllium           43 v r r-------   1       0 -   /usr/local/share/fonts/dejavu/DejaVuSans.ttf
"""
CONFINED_C = """\
  PID COMM                FD T FLAGS    CAPABILITIES   PRO NAME
 5000 beryllium            0 v r------- rd,wr,se,fc,fs,ev,io -   /dev/null
 5000 beryllium            3 v r------- rd,se,mm,fc,fs,prd,mmr,re -   /usr/local/share/beryllium/resources.pak
 5000 beryllium            4 s rw------ rd,wr,fc,fs,gs,ss,sh,ev,re,sd UDS 0 0
 5000 beryllium            6 k rw------ ke,kc -   -
 5000 beryllium            7 E rw---n-- rd,wr,fc,fs,ev,re,sd -   -
 5000 beryllium           12 h rw------ rd,wr,se,mm,fc,fs,prd,pwr,mmr,mmw,mrw,re,sd -   -
 5000 beryllium           40 v rw------ rd,se,mm,fc,fs,prd,mmr,re -   /home/u/.config/beryllium/Default/Cookies
 5000 beryllium           41 v r------- rd,se,mm,fc,fs,prd,mmr,re -   /etc/passwd
 5000 beryllium           42 v rw------ rd,wr,se,mm,fc,fs,io,prd,pwr,mmr,mmw,mrw,re,sd -   /dev/dri/renderD128
 5000 beryllium           43 v r------- rd,se,mm,fc,fs,prd,mmr,re -   /usr/local/share/fonts/dejavu/DejaVuSans.ttf
"""
PROCSTAT_S = """\
  PID COMM             FLAGS
 5000 beryllium        C
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

    def test_file_identities(self):
        ids = capsicum.file_identities(4242, FSTAT)
        self.assertEqual(sorted(ids), ["0", "21"])  # not text, not the socket
        self.assertEqual(ids["21"], {"mount": "/tmp", "inode": "99123", "mode": "-rw-------",
                                     "size": "2097152", "rw": "rw"})
        self.assertEqual(capsicum.describe_file(ids["21"], [("browser", 7777, "88")]),
                         "on /tmp, inode 99123, 2097152 bytes, mode -rw-------; "
                         "also held by: browser pid 7777 fd 88")
        self.assertIn("could not identify", capsicum.describe_file(None))

    def test_socket_peers_and_holders(self):
        socks = capsicum.socket_peers(4242, FSTAT)
        self.assertEqual(sorted(socks, key=int), ["4", "13", "18", "19", "20"])
        self.assertEqual(socks["4"], {"domain": "local", "type": "stream",
                                      "pcb": "fffff80012345678", "peer": "fffff80012345000",
                                      "conn": "<->"})
        self.assertEqual(socks["19"]["peer"], "")
        self.assertEqual(socks["20"]["type"], "dgram")
        by_pid = {4242: socks, 7777: capsicum.socket_peers(7777, FSTAT_BROWSER)}
        holders = capsicum.socket_holders(by_pid, {4242: "renderer", 7777: "browser"})
        self.assertEqual(holders["fffff80012345000"], ("browser", 7777, "88"))
        self.assertEqual(capsicum.describe_socket(socks["4"], holders, 4242),
                         "unix stream, other end: browser pid 7777 fd 88")
        self.assertEqual(capsicum.describe_socket(socks["13"], holders, 4242),
                         "unix stream, other end is fd 18 of this same process (a pair made here)")
        self.assertEqual(capsicum.describe_socket(socks["19"], holders, 4242),
                         "unix seqpak, not connected")
        self.assertIn("no Beryllium process", capsicum.describe_socket(socks["20"], holders, 4242))
        self.assertIn("could not", capsicum.describe_socket(None, holders, 4242))
        rights = {"4": {"type": "s", "rights": ["rd", "wr", "ev", "fs"], "name": ""},
                  "13": {"type": "s", "rights": sorted(capsicum.UNLIMITED_MARKERS | {"rd"}), "name": ""},
                  "21": {"type": "v", "rights": sorted(capsicum.UNLIMITED_MARKERS), "name": ""}}
        notes = capsicum.socket_notes(rights, socks, holders, 4242)
        self.assertEqual(len(notes), 1)
        self.assertIn("fd 13: socket with every right: unix stream, other end is fd 18", notes[0])
        socks["13"]["flags"] = "rw---n--"
        self.assertTrue(capsicum.socket_notes(rights, socks, holders, 4242)[0].endswith(", non-blocking"))

    def test_process_alive(self):
        with unittest.mock.patch.object(capsicum, "_ps_state", return_value="S+"):
            self.assertTrue(capsicum.process_alive(4242))
        with unittest.mock.patch.object(capsicum, "_ps_state", return_value="Z"):
            self.assertFalse(capsicum.process_alive(4242))  # exited, not reaped: no fd table
        with unittest.mock.patch.object(capsicum, "_ps_state", return_value=""):
            self.assertFalse(capsicum.process_alive(4242))
        with unittest.mock.patch.object(capsicum, "_ps_state", return_value=None), \
                unittest.mock.patch.object(capsicum.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(capsicum.process_alive(4242))
        with unittest.mock.patch.object(capsicum, "_ps_state", return_value=None), \
                unittest.mock.patch.object(capsicum.os, "kill", return_value=None):
            self.assertTrue(capsicum.process_alive(4242))

    def test_lockdown_log_parsers(self):
        made = ["[2:7:...] beryllium-sandbox: socket pair made at base::SyncSocket::CreatePair "
                "on thread 'CrRendererMain' (fd 13, fd 14): limited",
                "[2:9:...] beryllium-sandbox: socket pair made at mojo::PlatformChannel on "
                "thread 'Compositor' (fd 19, fd 22): limited",
                "[3:7:...] beryllium-sandbox: socket pair made on thread 'CrRendererMain' "
                "(fd 13, fd 14): limited"]
        self.assertEqual(capsicum.socket_pair_makers(made),
                         {"? on CrRendererMain": 1,
                          "base::SyncSocket::CreatePair on CrRendererMain": 1,
                          "mojo::PlatformChannel on Compositor": 1})
        locked = ["[2:2:...] beryllium-sandbox: renderer pid=2 capability_mode=1 "
                  "closed_directories=0 limited=12 threads=1",
                  "[3:3:...] beryllium-sandbox: renderer pid=3 capability_mode=1 "
                  "closed_directories=0 limited=12"]
        self.assertEqual(capsicum.threads_at_lockdown(locked), [1])
        cuts = ["[1:5:...] beryllium-sandbox: cut shared memory (fd 71) bound for confined renderer pid 2",
                "[1:5:...] beryllium-sandbox: cut socket (fd 72) bound for confined renderer pid 2",
                "[1:5:...] beryllium-sandbox: cut read-only file (fd 80) bound for confined renderer pid 3",
                "[1:5:...] beryllium-sandbox: device (fd 81) bound for confined renderer pid 3, "
                "which it may not hold: every right removed before sending"]
        self.assertEqual(capsicum.sent_cuts(cuts), {2: 2, 3: 1})

    def test_threads(self):
        text = """\
  PID    TID COMM                TDNAME              CPU  PRI STATE   WCHAN
 4242 100123 beryllium           beryllium             2  120 sleep   kqread
 4242 100124 beryllium           Chrome_ChildIOT      -1  120 sleep   kqread
 4242 100125 beryllium           ThreadPoolForeg       3  152 sleep   sbwait
 4242 100126 beryllium           Compositor            0  120 run
"""
        ths = capsicum.threads(4242, text)
        self.assertEqual([t["name"] for t in ths],
                         ["beryllium", "Chrome_ChildIOT", "ThreadPoolForeg", "Compositor"])
        self.assertEqual(ths[3]["wchan"], "-")
        self.assertEqual(capsicum.threads_waiting_on_sockets(ths), ["ThreadPoolForeg"])
        self.assertEqual(capsicum.threads(4242, ""), [])

    def test_capability_modes_with_grace(self):
        clock = [0.0]
        answers = {1: iter([True]), 2: iter([False, False, True]), 3: iter([False]),
                   4: iter([None])}

        def mode(pid):
            try:
                return next(answers[pid])
            except StopIteration:
                return {1: True, 2: True, 3: False, 4: None}[pid]
        with unittest.mock.patch.object(capsicum, "capability_mode", side_effect=mode), \
                unittest.mock.patch.object(capsicum, "_clock", side_effect=lambda: clock[0]), \
                unittest.mock.patch.object(capsicum, "_sleep",
                                           side_effect=lambda t: clock.__setitem__(0, clock[0] + t)), \
                unittest.mock.patch.object(capsicum, "process_alive",
                                           side_effect=lambda pid: pid != 4):
            modes = capsicum.capability_modes([1, 2, 3, 4], grace=1.0, interval=0.2)
        self.assertEqual(modes, {1: True, 2: True, 3: False, 4: "gone"})
        self.assertAlmostEqual(clock[0], 1.0, places=5)  # the full grace, for the stragglers
        with unittest.mock.patch.object(capsicum, "capability_mode", return_value=False), \
                unittest.mock.patch.object(capsicum, "process_alive", return_value=True):
            self.assertEqual(capsicum.capability_modes([5], grace=0), {5: False})

    def test_temp_files(self):
        self.assertEqual(capsicum.temp_file_name("/tmp/.org.chromium.Chromium.a1B2c3"),
                         "/tmp/.org.chromium.Chromium.XXXXXX")
        self.assertIsNone(capsicum.temp_file_name("/tmp/berytest.abc/home/x"))
        self.assertIsNone(capsicum.temp_file_name("/tmp"))
        self.assertEqual(capsicum.temp_file_name("/tmp/.X11-unix"), "/tmp/.X11-unix")
        found = capsicum.temp_files(KDUMP_TEMP.splitlines(), {7777: "browser", 5151: "GPU"})
        self.assertEqual(dict(found["browser"]), {"/tmp/.org.chromium.Chromium.XXXXXX": 2})
        self.assertEqual(dict(found["GPU"]), {"/tmp/.glXXXXXX": 1})
        self.assertNotIn("unknown", found)
        text = capsicum.temp_files_report(found)
        self.assertLess(text.index("browser"), text.index("GPU"))
        self.assertIn("None.", capsicum.temp_files_report({}))

    def test_policy_allows_a_handed_over_writable_file_with_its_kind_s_rights(self):
        fds = [{"fd": "40", "type": "v", "vtype": "r", "flags": "rw------",
                "name": "/home/john/.config/beryllium/Default/File System/000/t/00/00000001"}]
        within = {"40": {"type": "v", "name": fds[0]["name"],
                         "rights": ["rd", "wr", "se", "mm", "fs", "fc", "ft", "fy", "prd", "pwr", "mmr", "mmw", "mrw"]}}
        self.assertEqual(capsicum.policy_problems(fds, within), [])
        beyond = {"40": {"type": "v", "name": fds[0]["name"],
                         "rights": ["rd", "wr", "se", "mm", "fs", "fc", "ft", "fy", "cm", "mmx"]}}
        problems = capsicum.policy_problems(fds, beyond)
        self.assertEqual(len(problems), 1)
        self.assertIn("beyond a handed-over file's: cm,mmx", problems[0])
        unlimited = {"40": {"type": "v", "name": fds[0]["name"],
                            "rights": sorted(capsicum.UNLIMITED_MARKERS | {"rd", "wr"})}}
        self.assertIn("rights not limited", capsicum.policy_problems(fds, unlimited)[0])

    def test_policy_problems(self):
        fds = capsicum.descriptors(5000, CONFINED_F)
        caps = capsicum.rights(5000, CONFINED_C)
        problems = capsicum.policy_problems(fds, caps)
        # 0 is stdio; 3, 4, 6, 7, 12 and 43 (a font file) are within the policy.
        self.assertEqual(problems, [
            "fd 40: writable file /home/u/.config/beryllium/Default/Cookies",
            "fd 41: file that is not a resource or font file: /etc/passwd",
            "fd 42: vnode type 'c' not allowed (/dev/dri/renderD128)",
        ])
        # Rights beyond the type's, and an unlimited descriptor.
        caps["4"]["rights"].append("co")
        caps["6"]["rights"] = ["ke", "kc", "ev", "fs", "wr"]
        caps["12"]["rights"] = ["rd", "wr", "se", "mm", "ft", "mmx", "re", "sd"]
        caps["7"]["rights"] = sorted(capsicum.UNLIMITED_MARKERS | {"rd", "wr"})
        problems = capsicum.policy_problems(fds, caps)
        self.assertIn("fd 4 (s): rights beyond the policy: co", problems)
        self.assertIn("fd 6 (k): rights beyond the policy: wr", problems)
        self.assertIn("fd 12 (h): rights beyond the policy: ft,mmx", problems)
        self.assertIn("fd 7 (E): rights not limited", problems)
        # A type the policy has no entry for.
        caps["50"] = {"type": "P", "rights": ["pg", "pk"], "name": "-"}
        self.assertIn("fd 50: descriptor type 'P' not allowed",
                      capsicum.policy_problems(fds, caps))

    def test_cpu_seconds_parsing(self):
        for text, want in (("0:00.12\n", 0.12), ("00:00:01\n", 1.0), ("1:02:03.5\n", 3723.5),
                           ("2-01:00:00\n", 176400.0), ("", None), ("junk\n", None)):
            with unittest.mock.patch.object(capsicum, "_run", return_value=text):
                self.assertEqual(capsicum.cpu_seconds(1), want, text)

    def test_lockdown_requested(self):
        ns = lambda *args: unittest.mock.Mock(browser_args=list(args))  # noqa: E731
        self.assertTrue(capsicum.lockdown_requested(
            ns("--enable-features=BerylliumCapsicumRenderer")))
        self.assertTrue(capsicum.lockdown_requested(
            ns("--headless", "--enable-features=Foo,BerylliumCapsicumRenderer,BerylliumCapsicumTrap")))
        self.assertFalse(capsicum.lockdown_requested(ns()))
        self.assertFalse(capsicum.lockdown_requested(
            ns("--disable-features=BerylliumCapsicumRenderer")))
        self.assertFalse(capsicum.lockdown_requested(unittest.mock.Mock()))  # no list of arguments
        self.assertFalse(capsicum.lockdown_requested(None))

    def test_capability_mode_parsing(self):
        with unittest.mock.patch.object(capsicum, "_run", return_value=PROCSTAT_S):
            self.assertIs(capsicum.capability_mode(5000), True)
        with unittest.mock.patch.object(capsicum, "_run", return_value=PROCSTAT_S.replace(" C\n", " -\n")):
            self.assertIs(capsicum.capability_mode(5000), False)
        with unittest.mock.patch.object(capsicum, "_run", return_value=""):
            self.assertIsNone(capsicum.capability_mode(5000))

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


class LoggedFrames(unittest.TestCase):
    """The return addresses the lockdown logs for the first socket pair at
    each site and thread (0.20.3.15), parsed and named."""

    LINE = ("[69151:403674:1110/065457.579140:WARNING:base/posix/capsicum_rights.cc:430] "
            "beryllium-sandbox: the first socket pair made at mojo::PlatformChannel on thread "
            "'CrRendererMain' came from frames: beryllium+0x5a1b2c0 beryllium+0x3f00120 "
            "libthr.so.3+0x1a2b0 0x7fffdeadbeef ")

    def test_frames_are_parsed_per_site_and_thread_once(self):
        frames = capsicum.frames_logged([self.LINE, self.LINE])
        self.assertEqual(list(frames), ["mojo::PlatformChannel on CrRendererMain"])
        self.assertEqual(frames["mojo::PlatformChannel on CrRendererMain"],
                         [("beryllium", 0x5a1b2c0), ("beryllium", 0x3f00120),
                          ("libthr.so.3", 0x1a2b0), (None, 0x7fffdeadbeef)])

    def test_frames_in_the_binary_are_named_and_others_kept_as_offsets(self):
        calls = []
        def fake_run(cmd, inp):
            calls.append((cmd, inp))
            return ("mojo::PlatformChannel::PlatformChannel()\n??:0:0\n\n"
                    "content::RenderThreadImpl::Init()\n??:0:0\n")
        frames = capsicum.frames_logged([self.LINE])
        with unittest.mock.patch.object(capsicum.shutil, "which", return_value="/usr/bin/llvm-symbolizer"):
            lines = capsicum.describe_frames(frames, "/usr/local/share/beryllium/beryllium", run=fake_run)
        self.assertEqual(lines, ["mojo::PlatformChannel on CrRendererMain: "
                                 "mojo::PlatformChannel::PlatformChannel() < content::RenderThreadImpl::Init() "
                                 "< libthr.so.3+0x1a2b0 < ?+0x7fffdeadbeef"])
        self.assertEqual(calls[0][1], "0x5a1b2c0\n0x3f00120\n")
        self.assertIn("--obj=/usr/local/share/beryllium/beryllium", calls[0][0])

    def test_without_a_symbolizer_the_offsets_stand(self):
        frames = capsicum.frames_logged([self.LINE])
        with unittest.mock.patch.object(capsicum.shutil, "which", return_value=None), \
             unittest.mock.patch.object(capsicum.os.path, "exists", return_value=False):
            lines = capsicum.describe_frames(frames, "/usr/local/share/beryllium/beryllium")
        self.assertEqual(lines, ["mojo::PlatformChannel on CrRendererMain: beryllium+0x5a1b2c0 "
                                 "< beryllium+0x3f00120 < libthr.so.3+0x1a2b0 < ?+0x7fffdeadbeef"])


class ThreadNames(unittest.TestCase):
    LINE = ("[1:2:1110/124732.754052:WARNING:sandbox/policy/freebsd/sandbox_freebsd.cc:448] "
            "beryllium-sandbox: renderer pid=34900 capability_mode=1 closed_directories=0 limited=9 "
            "threads=2 thread_names=CrRendererMain,ThreadPoolServi")

    def test_names_are_listed_per_report(self):
        self.assertEqual(capsicum.thread_names_at_lockdown([self.LINE]),
                         [["CrRendererMain", "ThreadPoolServi"]])
        self.assertEqual(capsicum.threads_at_lockdown([self.LINE]), [2])

    def test_a_build_without_names_gives_an_empty_list(self):
        line = self.LINE.replace(" thread_names=CrRendererMain,ThreadPoolServi", " thread_names=-")
        self.assertEqual(capsicum.thread_names_at_lockdown([line]), [[]])
        self.assertEqual(capsicum.thread_names_at_lockdown([self.LINE.split(" thread_names")[0]]), [])
