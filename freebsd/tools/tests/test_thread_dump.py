# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the browser suite's thread dump of a renderer at its lockdown
point (freebsd/tests/browser/berytest/capsicum.py: parse_lldb, name_frames,
run_to_lockdown). The fixture is lldb's own output for a Chromium renderer
paused by --renderer-startup-dialog and run on to a breakpoint, shortened."""

import os
import signal
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests", "browser"))
from berytest import capsicum  # noqa: E402

BINARY = "/usr/local/share/beryllium/beryllium"

LLDB = """\
(lldb) process attach --pid 1818
Process 1818 stopped
* thread #1, name = 'beryllium', stop reason = signal SIGSTOP
    frame #0: 0x00007f7efccfa4f6 libc.so.7`__sys_sigsuspend + 10
  thread #2, name = 'beryllium', stop reason = signal SIGSTOP
    frame #0: 0x00007f7efcc98e51 libthr.so.3`___lldb_unnamed_symbol111 + 33
Executable module set to "/usr/local/share/beryllium/beryllium".
(lldb) thread backtrace all
* thread #1, name = 'beryllium', stop reason = signal SIGSTOP
  * frame #0: 0x00007f7efccfa4f6 libc.so.7`__sys_sigsuspend + 10
    frame #1: 0x000055d0e835b7e2 beryllium`___lldb_unnamed_symbol15648 + 76786
    frame #2: 0x000055d0e5d69b00 beryllium`ChromeMain + 496
    frame #3: 0x00007f7efcc2a1ca libc.so.7`__libc_start1(argc=10, argv=0x00007ffdabfc9a48) at libc_start1.c:157:12
    frame #4: 0x000055d0e6af935a beryllium`_start + 42
  thread #2, name = 'beryllium', stop reason = signal SIGSTOP
    frame #0: 0x00007f7efcc98e51 libthr.so.3`___lldb_unnamed_symbol111 + 33
    frame #1: 0x000055d0e3b3a6e8 beryllium
    frame #2: 0x000055d0e4bc4030 beryllium`___lldb_unnamed_symbol5787 + 14816
    frame #3: 0x00007f7efcc9cb84 libthr.so.3`thread_start(arg=<unavailable>) at thr_create.c:290:16
    frame #4: 0x0000000000001234
(lldb) breakpoint set -n utrace -n __sys_utrace -n cap_enter -n __sys_cap_enter
Breakpoint 1: 2 locations.
(lldb) process handle SIGUSR1 --stop false --pass true --notify false
NAME         PASS   STOP   NOTIFY
===========  =====  =====  ======
SIGUSR1      true   false  false
(lldb) continue
Process 1818 resuming
Process 1818 stopped
* thread #1, name = 'beryllium', stop reason = breakpoint 1.1
    frame #0: 0x00007f7efcd0a000 libc.so.7`utrace
(lldb) thread backtrace all
* thread #1, name = 'beryllium', stop reason = breakpoint 1.1
  * frame #0: 0x00007f7efcd0a000 libc.so.7`utrace
    frame #1: 0x000055d0e3000100 beryllium`___lldb_unnamed_symbol1 + 4
    frame #2: 0x000055d0e5d69b00 beryllium`ChromeMain + 496
  thread #2, name = 'beryllium'
    frame #0: 0x00007f7efcc98e51 libthr.so.3`___lldb_unnamed_symbol111 + 33
    frame #1: 0x000055d0e3b3a6e8 beryllium
(lldb) image list -o -f
[  0] 0x000055d0dfd9c000 /usr/local/share/beryllium/beryllium
[  1] 0x00007f7efcc00000 /lib/libc.so.7
[  2] 0x00007f7efcc90000 /lib/libthr.so.3
[  3] 0x00007f7efdc01000 [vdso](0x00007f7efdc01000)
(lldb) detach
Process 1818 detached
"""
SLIDE = 0x000055d0dfd9c000


def fake_symbolizer(names):
    """llvm-symbolizer's reply for the offsets it is asked about."""
    def run(cmd, inp):
        return "\n\n".join(f"{names.get(int(line, 16), '??')}\n??:0:0"
                           for line in inp.split()) + "\n"
    return run


class ParseLldb(unittest.TestCase):
    def setUp(self):
        self.dumps, self.images = capsicum.parse_lldb(LLDB)

    def test_two_dumps_and_not_the_attach_summary(self):
        self.assertEqual([len(d) for d in self.dumps], [2, 2])
        self.assertEqual([len(t["frames"]) for t in self.dumps[0]], [5, 5])

    def test_threads(self):
        first = self.dumps[1][0]
        self.assertEqual((first["index"], first["name"], first["stop"]),
                         (1, "beryllium", "breakpoint 1.1"))
        self.assertEqual(self.dumps[1][1]["stop"], "")

    def test_frames(self):
        frames = self.dumps[0][1]["frames"]
        self.assertEqual(frames[0], (0x00007f7efcc98e51, "libthr.so.3",
                                     "___lldb_unnamed_symbol111 + 33"))
        self.assertEqual(frames[1], (0x000055d0e3b3a6e8, "beryllium", ""))
        self.assertEqual(frames[4], (0x1234, "", ""))

    def test_images(self):
        self.assertEqual(self.images["beryllium"], SLIDE)
        self.assertEqual(self.images["libthr.so.3"], 0x00007f7efcc90000)
        self.assertNotIn("[vdso](0x00007f7efdc01000)", self.images)

    def test_terminal_line_ends(self):
        dumps, images = capsicum.parse_lldb(LLDB.replace("\n", "\r\n"))
        self.assertEqual([len(d) for d in dumps], [2, 2])
        self.assertEqual(images["beryllium"], SLIDE)

    def test_nothing(self):
        self.assertEqual(capsicum.parse_lldb("error: attach failed\n"), ([], {}))


class NameFrames(unittest.TestCase):
    def setUp(self):
        self.dumps, self.images = capsicum.parse_lldb(LLDB)
        self.run = fake_symbolizer({
            0x000055d0e835b7e2 - SLIDE: "content::WaitForDebugger(std::string const&)",
            0x000055d0e3b3a6e8 - SLIDE: "base::HangWatcher::Run()",
            0x000055d0e4bc4030 - SLIDE: "base::(anonymous namespace)::ThreadFunc(void*)",
            0x000055d0e5d69b00 - SLIDE: "ChromeMain",
        })
        self._which = capsicum.shutil.which
        capsicum.shutil.which = lambda tool: "/usr/bin/llvm-symbolizer"
        self.addCleanup(setattr, capsicum.shutil, "which", self._which)

    def test_binary_frames_by_the_symbolizer_others_by_lldb(self):
        names = capsicum.name_frames(self.dumps[0], self.images, BINARY, self.run)
        self.assertEqual(names[0][:3], ["__sys_sigsuspend",
                                        "content::WaitForDebugger(std::string const&)",
                                        "ChromeMain"])
        self.assertEqual(names[0][3], "__libc_start1")
        # the symbolizer has no name for _start's address: lldb's is used
        self.assertEqual(names[0][4], "_start")

    def test_unnamed_frames_fall_back_to_module_and_offset(self):
        names = capsicum.name_frames(self.dumps[0], self.images, BINARY, self.run)
        self.assertEqual(names[1], ["libthr.so.3+0x8e51", "base::HangWatcher::Run()",
                                    "base::(anonymous namespace)::ThreadFunc(void*)",
                                    "thread_start", "0x1234"])

    def test_describe_dump(self):
        lines = capsicum.describe_dump(self.dumps[1], self.images, BINARY, self.run)
        self.assertTrue(lines[0].startswith("thread #1, stopped by breakpoint 1.1: utrace < "))
        self.assertEqual(lines[1], "thread #2: libthr.so.3+0x8e51 < base::HangWatcher::Run()")

    def test_without_the_binary_in_the_image_list(self):
        names = capsicum.name_frames(self.dumps[0], {}, BINARY, self.run)
        self.assertEqual(names[1][1], "0x55d0e3b3a6e8")


class ShortStack(unittest.TestCase):
    def test_short_stacks_are_whole(self):
        self.assertEqual(capsicum.short_stack(["a", "b", "c"]), "a < b < c")

    def test_long_stacks_keep_both_ends(self):
        names = [f"f{i}" for i in range(30)]
        text = capsicum.short_stack(names, inner=2, outer=3)
        self.assertEqual(text, "f0 < f1 < ...25 more... < f27 < f28 < f29")


class Commands(unittest.TestCase):
    def test_commands(self):
        commands = capsicum.lldb_commands()
        self.assertEqual(commands[0], "thread backtrace all")
        self.assertEqual(commands[1],
                         "breakpoint set -n utrace -n __sys_utrace -n cap_enter -n __sys_cap_enter")
        self.assertIn("SIGUSR1 --stop false --pass true", commands[2])
        self.assertEqual(commands[3:], ["continue", "thread backtrace all",
                                        "image list -o -f", "detach"])

    def test_resumed(self):
        self.assertFalse(capsicum.resumed(""))
        self.assertFalse(capsicum.resumed("(lldb) process attach --pid 1\nProcess 1 stopped\n"))
        self.assertFalse(capsicum.resumed("(lldb) continue\n"))
        self.assertTrue(capsicum.resumed("(lldb) continue\nProcess 1 resuming\n"))

    def test_dumps_begun(self):
        self.assertEqual(len(capsicum.lldb_dumps(LLDB)), 2)
        self.assertEqual(len(capsicum.lldb_dumps(LLDB.split("(lldb) continue")[0])), 1)

    def test_paused_line(self):
        line = ("[350:350:1110/140939.579974:ERROR:content/common/content_switches_internal.cc:109] "
                "Renderer (350) paused waiting for debugger to attach. Send SIGUSR1 to unpause.")
        self.assertEqual(capsicum.PAUSED.search(line).group(1), "350")


class FakeLldb:
    """Stands in for the lldb process: writes its output to the terminal it
    is given in two parts, the second only once it has been "signalled"."""

    def __init__(self, cmd, stdout, **kwargs):
        self.cmd, self.fd = cmd, os.dup(stdout)
        self.first, self.second = LLDB.split("Process 1818 stopped\n* thread #1, name = "
                                             "'beryllium', stop reason = breakpoint", 1)
        os.write(self.fd, self.first.encode())
        self.signalled = False
        self.done = False

    def poll(self):
        if self.signalled and not self.done:
            os.write(self.fd, ("Process 1818 stopped\n* thread #1, name = 'beryllium', "
                               "stop reason = breakpoint" + self.second).encode())
            os.close(self.fd)
            self.done = True
            return None
        return 0 if self.done else None

    def kill(self):
        if not self.done:
            os.close(self.fd)
            self.done = True

    def wait(self):
        return 0


class RunToLockdown(unittest.TestCase):
    def run_it(self, states, timeout=5):
        made, sent = [], []

        def popen(cmd, **kwargs):
            made.append(FakeLldb(cmd, **kwargs))
            return made[0]

        def kill(pid, sig):
            sent.append((pid, sig))
            made[0].signalled = True

        state = iter(states)
        text = capsicum.run_to_lockdown(1818, popen=popen, kill=kill, timeout=timeout,
                                        state_of=lambda pid: next(state, "S"))
        return text, sent, made[0]

    def test_signal_goes_out_once_lldb_says_resuming(self):
        text, sent, lldb = self.run_it(["T", "T", "S", "S", "S"])
        self.assertEqual(sent, [(1818, signal.SIGUSR1)])
        dumps, images = capsicum.parse_lldb(text)
        self.assertEqual([len(d) for d in dumps], [2, 2])
        self.assertIn("-p", lldb.cmd)
        self.assertIn("--no-use-colors", lldb.cmd)

    def test_lldb_that_cannot_start(self):
        def popen(cmd, **kwargs):
            raise OSError("no lldb")
        text = capsicum.run_to_lockdown(1, popen=popen, kill=lambda *a: None)
        self.assertIn("could not be started", text)


class ThreadNameSets(unittest.TestCase):
    def test_counts_per_renderer(self):
        self.assertEqual(capsicum.thread_name_sets([["beryllium", "beryllium"]] * 3),
                         {"beryllium,beryllium": 3})
        self.assertEqual(capsicum.thread_name_sets([["CrRendererMain"], ["CrRendererMain", "x"]]),
                         {"CrRendererMain": 1, "CrRendererMain,x": 1})
        self.assertEqual(capsicum.thread_name_sets([]), {})


if __name__ == "__main__":
    unittest.main()
