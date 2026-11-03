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


def backtrace(binary, core, lines=80):
    """Backtrace of the crashing thread, with the loaded modules for context."""
    if shutil.which("lldb"):
        cmd = ["lldb", "--batch", "-c", core, binary, "-o", "bt", "-o", "register read rip",
               "-o", "image lookup -a $pc"]
    elif shutil.which("gdb"):
        cmd = ["gdb", "-batch", "-ex", "bt", "-ex", "info registers rip", binary, core]
    else:
        return "(no lldb or gdb to read the core)"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return f"(debugger failed: {e})"
    out = (r.stdout + r.stderr).splitlines()
    return "\n".join(out[:lines])
