# SPDX-License-Identifier: GPL-3.0-only
"""Capability-mode survey: what each browser process does that Capsicum
capability mode would refuse, and what it holds (plan/09 Phase 2 item 1,
feature matrix S-REN-02 and S-REN-03).

FreeBSD's ktrace records with -t p every system call and path lookup that
capability mode would refuse, even in a process that has not entered it
(CAPFAIL; since FreeBSD 14.1 and 15, requested explicitly). -t n adds the
path of every lookup and -t y the name of every sysctl read. This module
reads kdump's output and procstat's views of a process: descriptors,
environment variable names (never values) and resource limits."""

import collections
import glob
import json
import os
import re
import subprocess

# "  1234 beryllium CAP   system call not allowed: openat"; kdump -H adds a
# thread id column after the pid.
KDUMP_RE = re.compile(r"^\s*(\d+)\s+(?:\d+\s+)?(\S+)\s+(CAP|NAMI|SCTL|USER)\s+(.*?)\s*$")
SAMPLES = 8  # example paths kept per failure
# Written with utrace(2) by patches/security/beryllium-capsicum-renderer.patch
# at the renderer's lockdown point; kdump prints it as a length and hex bytes.
MARKER = b"BERYLLIUM-LOCKDOWN"
# System calls whose refusal comes from a path lookup, so the lookup just
# before it names the path; other refusals (cpuset, signals) get no path.
PATH_SYSCALLS = {"open", "openat", "access", "eaccess", "faccessat", "readlink",
                 "readlinkat", "stat", "lstat", "fstatat", "__realpathat", "mkdir",
                 "mkdirat", "rename", "renameat", "unlink", "unlinkat", "rmdir",
                 "connect", "bind", "statfs", "pathconf", "execve", "chdir",
                 "chmod", "chown", "link", "symlink", "mkfifo", "__sysctl"}


def _unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def syscall_of(message):
    """The system call a CAPFAIL message is about, if it names one."""
    if message.startswith("system call not allowed: "):
        return message.split(": ", 1)[1].split()[0]
    if ": " in message:
        return message.split(": ", 1)[0]
    return None


def sysctl_name(name):
    """Groups per-process and per-oid names: kern.proc.pid.123 -> kern.proc.pid.<pid>."""
    name = re.sub(r"^(kern\.proc\.\w+)\.\d+$", r"\1.<pid>", name)
    return re.sub(r"^(sysctl\.\w+)(\.\d+)+$", r"\1.<oid>", name)


def is_marker(data):
    if MARKER.decode() in data:
        return True
    fields = data.split()
    try:
        raw = bytes(int(x, 16) for x in fields[1:])
    except ValueError:
        return False
    return MARKER in raw


def _new_proc(comm):
    return {"comm": comm, "marker": False, "lookups": 0,
            "cap": collections.Counter(), "cap_after": collections.Counter(),
            "cap_paths": collections.defaultdict(list),
            "sysctl": collections.Counter(), "sysctl_after": collections.Counter()}


def parse_kdump(lines):
    """Per pid: capability failures (message -> count, with example paths
    from the lookup that caused them) and sysctl names read, in total and
    after the lockdown marker when the process wrote one."""
    procs = {}
    last_path = {}
    for line in lines:
        m = KDUMP_RE.match(line)
        if not m:
            continue
        pid, comm, kind, data = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        p = procs.setdefault(pid, _new_proc(comm))
        if kind == "USER":
            if is_marker(data):
                p["marker"] = True
        elif kind == "NAMI":
            last_path[pid] = _unquote(data)
            p["lookups"] += 1
        elif kind == "SCTL":
            name = sysctl_name(_unquote(data))
            p["sysctl"][name] += 1
            if p["marker"]:
                p["sysctl_after"][name] += 1
        else:  # CAP
            message = data
            p["cap"][message] += 1
            if p["marker"]:
                p["cap_after"][message] += 1
            path = last_path.get(pid) if syscall_of(message) in PATH_SYSCALLS else None
            examples = p["cap_paths"][message]
            if path and path not in examples and len(examples) < SAMPLES:
                examples.append(path)
    return procs


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _table(text):
    """procstat output as dicts keyed by its header; the last column keeps spaces."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    header = lines[0].split()
    rows = []
    for line in lines[1:]:
        cells = line.split(None, len(header) - 1)
        rows.append(dict(zip(header, cells)))
    return rows


def descriptors(pid, text=None):
    """[{fd, type, flags, name}] from procstat -f."""
    rows = _table(text if text is not None else _run(["procstat", "-f", str(pid)]))
    return [{"fd": r.get("FD", ""), "type": r.get("T", ""), "flags": r.get("FLAGS", ""),
             "name": r.get("NAME", r.get("PATH", ""))} for r in rows]


ENV_NAME_RE = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=")


def environment_names(pid, text=None):
    """Variable names only, from procstat -e; values are never kept."""
    text = text if text is not None else _run(["procstat", "-e", str(pid)])
    lines = text.splitlines()[1:]
    return sorted({m.group(1) for line in lines for m in ENV_NAME_RE.finditer(line)})


# "  4242 beryllium  datasize   4194304 KB   4194304 KB" (FreeBSD 16 adds units)
LIMIT_RE = re.compile(r"^\s*\d+\s+\S+\s+(\S+)\s+(infinity|-?\d+(?:\s+[A-Za-z]+)?)"
                      r"\s+(infinity|-?\d+(?:\s+[A-Za-z]+)?)\s*$")


def limits(pid, text=None):
    """{rlimit: (soft, hard)} from procstat -l."""
    text = text if text is not None else _run(["procstat", "-l", str(pid)])
    out = {}
    for line in text.splitlines()[1:]:
        m = LIMIT_RE.match(line)
        if m:
            out[m.group(1)] = (" ".join(m.group(2).split()), " ".join(m.group(3).split()))
    return out


def proc_debug_setting():
    """security.bsd.unprivileged_proc_debug: procstat -f and -e read another
    process's descriptors and environment only when it is 1 (limits are
    readable either way); ktrace started on itself works regardless."""
    value = _run(["sysctl", "-n", "security.bsd.unprivileged_proc_debug"]).strip()
    return value or None


def readable_sysctls(results_dir, kernel_release):
    """The sysctls the Capsicum oracle found readable in capability mode on
    a kernel of this major version, newest result first; None if no result
    for this version is committed."""
    major = kernel_release.split(".")[0]
    files = sorted(glob.glob(os.path.join(results_dir, f"oracle-{major}.*.json")), reverse=True)
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return set(data["caprd_sysctls"]["readable"]), os.path.basename(path)
        except (OSError, ValueError, KeyError):
            continue
    return None, None


def summarise(kdump, types, readable=None):
    """Aggregate parse_kdump() output by process type ({pid: type}). The
    browser process is left out: it is never confined."""
    out = {}
    for pid, p in kdump.items():
        ptype = types.get(pid, "unknown")
        if ptype == "browser":
            continue
        t = out.setdefault(ptype, {"pids": [], "marked": 0,
                                   "cap": collections.Counter(),
                                   "cap_after": collections.Counter(),
                                   "cap_paths": collections.defaultdict(list),
                                   "sysctl": collections.Counter(),
                                   "sysctl_after": collections.Counter()})
        t["pids"].append(pid)
        t["marked"] += 1 if p["marker"] else 0
        for key in ("cap", "cap_after", "sysctl", "sysctl_after"):
            t[key].update(p[key])
        for message, paths in p["cap_paths"].items():
            examples = t["cap_paths"][message]
            for path in paths:
                if path not in examples and len(examples) < SAMPLES:
                    examples.append(path)
    for t in out.values():
        t["sysctl_blocked"] = (sorted(n for n in t["sysctl"] if n not in readable)
                               if readable is not None else None)
    return out


def _failures(lines, counter, paths, title):
    if not counter:
        return
    lines.append(title)
    for message, n in counter.most_common():
        lines.append(f"  {n:6d}  {message}")
        for path in paths.get(message, []):
            lines.append(f"            {path}")
    lines.append("")


def _sysctls(lines, counter, blocked, note, title):
    if not counter:
        return
    lines.append(f"{title} ({note}):")
    for name, n in sorted(counter.items()):
        mark = "" if blocked is None else (
            "  REFUSED in capability mode" if name in blocked else "  ok")
        lines.append(f"  {n:6d}  {name}{mark}")
    lines.append("")


def report(summary, samples, readable_from=None):
    """Plain-text report: per process type, the failures, the sysctls and
    (for one process of the type) its descriptors, environment and limits."""
    lines = []
    sampled = {s.get("type") for s in samples.values()} - {None, "browser"}
    empty = {"pids": [], "cap": collections.Counter(), "cap_paths": {},
             "sysctl": collections.Counter(), "sysctl_blocked": None}
    for ptype in sorted(set(summary) | sampled, key=lambda t: (t != "renderer", t)):
        t = summary.get(ptype, empty)
        count = len(t["pids"]) or sum(1 for s in samples.values() if s.get("type") == ptype)
        lines += [f"== {ptype} ({count} processes)", ""]
        note = (f"readable in capability mode per {readable_from}" if readable_from
                else "no oracle result for this kernel to say which are readable")
        blocked = set(t["sysctl_blocked"]) if t.get("sysctl_blocked") is not None else None
        if t.get("marked"):
            lines.append(f"{t['marked']} of these processes wrote the lockdown marker.")
            lines.append("")
            if not t["cap_after"] and not t["sysctl_after"]:
                lines.append("After the lockdown point: nothing capability mode would refuse.")
                lines.append("")
            _failures(lines, t["cap_after"], t["cap_paths"],
                      "AFTER the lockdown point (must work in capability mode):")
            _sysctls(lines, t["sysctl_after"], blocked, note,
                     "Sysctls read AFTER the lockdown point")
            before = t["cap"] - t["cap_after"]
            _failures(lines, before, t["cap_paths"],
                      "Before the lockdown point (start-up; allowed):")
        else:
            if not t["cap"]:
                lines.append("No capability failures recorded.")
                lines.append("")
            _failures(lines, t["cap"], t["cap_paths"],
                      "Would be refused in capability mode (no lockdown marker in this "
                      "build, so start-up and later are mixed):")
            _sysctls(lines, t["sysctl"], blocked, note, "Sysctls read")
        sample = next((samples[pid] for pid in t["pids"] if pid in samples), None)
        if sample is None:
            sample = next((s for s in samples.values() if s.get("type") == ptype), None)
        if sample:
            lines.append(f"Descriptors of pid {sample['pid']} (procstat -f, after "
                         f"{', '.join(sample.get('workloads', [])) or 'start'}):")
            for d in sample.get("fds", []):
                lines.append(f"  {d['fd']:>5} {d['type']:<2} {d['flags']:<10} {d['name']}")
            lines.append(f"Environment variable names: {', '.join(sample.get('env', [])) or '(none)'}")
            lim = sample.get("limits", {})
            if lim:
                lines.append("Limits: " + ", ".join(f"{k}={v[0]}/{v[1]}" for k, v in sorted(lim.items())))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
