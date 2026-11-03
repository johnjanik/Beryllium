# SPDX-License-Identifier: GPL-3.0-only
"""Find core dumps from a test run and print their backtraces (--cores).

FreeBSD writes a crashing process's core to kern.corefile, by default
"%N.core" in the process's working directory (the browser and its children
are started in the results' cores/ directory). An absolute kern.corefile
(for example /var/tmp/%N.%P.core) is searched as well."""

import glob
import os
import shutil
import subprocess


def corefile_pattern():
    try:
        return subprocess.run(["sysctl", "-n", "kern.corefile"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def find(core_dir, since):
    dirs = {core_dir}
    pattern = corefile_pattern()
    if pattern.startswith("/"):
        dirs.add(os.path.dirname(pattern))
    found = []
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*core*")):
            try:
                if os.path.isfile(path) and os.path.getmtime(path) >= since:
                    found.append(path)
            except OSError:
                pass
    return sorted(found, key=os.path.getmtime)


# Enough to tell a bad pointer from a bad instruction, and which thread and
# code it was, even in a stripped binary: the backtrace, the faulting
# instruction in context, all registers, the fault address (siginfo), the
# memory map entry for the pc, the threads, and the load addresses.
LLDB_COMMANDS = ["bt", "disassemble --start-address '$pc-96' --count 48", "register read",
                 "thread siginfo", "memory region $pc", "thread list", "image list"]
GDB_COMMANDS = ["bt", "x/48i $pc-96", "info registers", "p $_siginfo", "info threads",
                "info sharedlibrary"]


def backtrace(binary, core, lines=400):
    """What the debugger can say about the crash; see LLDB_COMMANDS."""
    if shutil.which("lldb"):
        cmd = ["lldb", "--batch", "-c", core, binary]
        for c in LLDB_COMMANDS:
            cmd += ["-o", c]
    elif shutil.which("gdb"):
        cmd = ["gdb", "-batch"]
        for c in GDB_COMMANDS:
            cmd += ["-ex", c]
        cmd += [binary, core]
    else:
        return "(no lldb or gdb to read the core)"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return f"(debugger failed: {e})"
    out = (r.stdout + r.stderr).splitlines()
    return "\n".join(out[:lines])
