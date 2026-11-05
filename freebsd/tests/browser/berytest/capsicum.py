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
            "cap_paths_before": collections.defaultdict(list),
            "cap_paths_after": collections.defaultdict(list),
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
            phase = "cap_paths_after" if p["marker"] else "cap_paths_before"
            for key in ("cap_paths", phase):
                examples = p[key][message]
                if path and path not in examples and len(examples) < SAMPLES:
                    examples.append(path)
    return procs


TEMP_DIRS = ("/tmp", "/var/tmp")


def temp_file_name(path, temp_dirs=TEMP_DIRS):
    """A file directly in a temporary directory, with mkstemp's six random
    characters replaced by XXXXXX when they look random (a digit or mixed
    case), or None for any other path."""
    head, _, name = path.rstrip("/").rpartition("/")
    if not name or head not in temp_dirs:
        return None
    tail = name[-6:]
    if (len(name) > 6 and tail.isalnum()
            and (any(c.isdigit() for c in tail) or (tail.lower() != tail and tail.upper() != tail))):
        name = name[:-6] + "XXXXXX"
    return f"{head}/{name}"


def temp_files(lines, types, temp_dirs=TEMP_DIRS):
    """{process type: Counter(temp file pattern)} from kdump NAMI records,
    every process included (the browser too): who makes temporary files."""
    out = collections.defaultdict(collections.Counter)
    for line in lines:
        m = KDUMP_RE.match(line)
        if not m or m.group(3) != "NAMI":
            continue
        name = temp_file_name(_unquote(m.group(4)), temp_dirs)
        if name:
            out[types.get(int(m.group(1)), "unknown")][name] += 1
    return out


def temp_files_report(found):
    lines = ["== Temporary files (path lookups directly in a temporary directory, "
             "every process, the browser included)", ""]
    if not found:
        lines.append("None.")
    for ptype in sorted(found, key=lambda t: (t != "browser", t)):
        for name, n in found[ptype].most_common():
            lines.append(f"  {ptype:<32} {n:>5}  {name}")
    return "\n".join(lines) + "\n"


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
    """[{fd, type, vtype, flags, name}] from procstat -f. type: v vnode,
    s socket, p pipe, k kqueue, h shared memory...; vtype for vnodes: d
    directory, r regular file, c character device."""
    rows = _table(text if text is not None else _run(["procstat", "-f", str(pid)]))
    return [{"fd": r.get("FD", ""), "type": r.get("T", ""), "vtype": r.get("V", ""),
             "flags": r.get("FLAGS", ""), "name": r.get("NAME", r.get("PATH", ""))}
            for r in rows]


def risky_descriptors(fds):
    """Descriptors a confined renderer must not hold: directories (lookups
    beneath them still work in capability mode) and writable files, apart
    from 0-2. "text", "cwd", "root" and "trace" are not descriptors."""
    out = []
    for d in fds:
        if not d["fd"].isdigit() or d["type"] != "v":
            continue
        if d["vtype"] == "d":
            out.append(f"fd {d['fd']} directory {d['name']}")
        elif int(d["fd"]) > 2 and "w" in d["flags"] and d["vtype"] == "r":
            name = d["name"].strip()
            if name in ("", "-"):
                # No path: an unlinked file. Before the memfd patch, Chromium's
                # shared memory on FreeBSD was exactly that, in TMPDIR.
                out.append(f"fd {d['fd']} writable file with no name (unlinked)")
            else:
                out.append(f"fd {d['fd']} writable file {name}")
    return out


# Rights only a descriptor nobody limited has all of: fchdir, fchroot,
# fexecve, fsck, ftruncate, fchmod, fchown (procstat -C short names).
UNLIMITED_MARKERS = {"cd", "ct", "fe", "fk", "ft", "cm", "cn"}


def rights(pid, text=None):
    """{fd: {type, rights, name}} from procstat -C -f: each descriptor's
    Capsicum rights in procstat's short names (rd read, wr write, mm mmap,
    mmr/mrw/mmx map read/read-write/executable, ft ftruncate, fs fstat, fc
    fcntl, cm fchmod...). "-" in procstat means none; a descriptor nobody
    limited has all of them."""
    rows = _table(text if text is not None else _run(["procstat", "-C", "-f", str(pid)]))
    out = {}
    for r in rows:
        fd = r.get("FD", "")
        if not fd.isdigit():
            continue
        caps = r.get("CAPABILITIES", "-")
        out[fd] = {"type": r.get("T", ""),
                   "rights": [] if caps == "-" else caps.split(","),
                   "name": r.get("NAME", "").strip()}
    return out


def rights_summary(names):
    """Short form for reports: "all" for an unlimited descriptor."""
    if UNLIMITED_MARKERS <= set(names):
        return "all"
    return ",".join(names) or "none"


# What no holder of a shared memory descriptor should be able to do
# (S-SHM-01, S-SHM-02): the region's size is sealed, and nothing maps it
# executable or changes its owner or mode.
SHM_FORBIDDEN = (("ft", "truncate"), ("mmx", "map executable"),
                 ("fe", "execute"), ("cm", "chmod"), ("cn", "chown"))


def shared_memory_problems(rights_by_fd):
    """Shared memory descriptors (type h) holding a forbidden right."""
    out = []
    for fd in sorted(rights_by_fd, key=int):
        r = rights_by_fd[fd]
        if r["type"] != "h":
            continue
        bad = [why for abbr, why in SHM_FORBIDDEN if abbr in r["rights"]]
        if bad:
            out.append(f"fd {fd} shared memory can {', '.join(bad)} "
                       f"(rights: {rights_summary(r['rights'])})")
    return out


def file_identities(pid, text=None):
    """{fd: {mount, inode, mode, size, rw}} for the vnodes in fstat -p:
    the file system and inode identify a file that has no name any more."""
    text = text if text is not None else _run(["fstat", "-p", str(pid)])
    out = {}
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) >= 9 and f[3].isdigit():
            out[f[3]] = {"mount": f[4], "inode": f[5], "mode": f[6], "size": f[7], "rw": f[8]}
    return out


def describe_file(ident, holders=()):
    """One line for an unnamed file: where it lives, its size, who else holds it."""
    if not ident:
        return "(fstat could not identify it)"
    also = ", ".join(f"{t} pid {p} fd {fd}" for t, p, fd in holders) or "no other Beryllium process"
    return (f"on {ident['mount']}, inode {ident['inode']}, {ident['size']} bytes, "
            f"mode {ident['mode']}; also held by: {also}")


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
                                   "cap_paths_before": collections.defaultdict(list),
                                   "cap_paths_after": collections.defaultdict(list),
                                   "sysctl": collections.Counter(),
                                   "sysctl_after": collections.Counter()})
        t["pids"].append(pid)
        t["marked"] += 1 if p["marker"] else 0
        for key in ("cap", "cap_after", "sysctl", "sysctl_after"):
            t[key].update(p[key])
        for key in ("cap_paths", "cap_paths_before", "cap_paths_after"):
            for message, paths in p[key].items():
                examples = t[key][message]
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
        if ptype == "unknown":
            lines += ["Processes the browser never listed: they started and ended between "
                      "two samples (a renderer that wrote the marker was a renderer).", ""]
        note = (f"readable in capability mode per {readable_from}" if readable_from
                else "no oracle result for this kernel to say which are readable")
        blocked = set(t["sysctl_blocked"]) if t.get("sysctl_blocked") is not None else None
        if t.get("marked"):
            lines.append(f"{t['marked']} of these processes wrote the lockdown marker.")
            lines.append("")
            if not t["cap_after"] and not t["sysctl_after"]:
                lines.append("After the lockdown point: nothing capability mode would refuse.")
                lines.append("")
            _failures(lines, t["cap_after"], t["cap_paths_after"],
                      "AFTER the lockdown point (must work in capability mode):")
            _sysctls(lines, t["sysctl_after"], blocked, note,
                     "Sysctls read AFTER the lockdown point")
            before = t["cap"] - t["cap_after"]
            _failures(lines, before, t["cap_paths_before"],
                      "Before the lockdown point (start-up; allowed):")
        else:
            if not t["cap"]:
                lines.append("No capability failures recorded.")
                lines.append("")
            _failures(lines, t["cap"], t["cap_paths"],
                      "Would be refused in capability mode (this process type has no "
                      "lockdown point yet, so start-up and later are mixed):")
            _sysctls(lines, t["sysctl"], blocked, note, "Sysctls read")
        sample = next((samples[pid] for pid in t["pids"] if pid in samples), None)
        if sample is None:
            sample = next((s for s in samples.values() if s.get("type") == ptype), None)
        if sample:
            lines.append(f"Descriptors of pid {sample['pid']} (procstat -f and -C, after "
                         f"{', '.join(sample.get('workloads', [])) or 'start'}):")
            caps = sample.get("rights", {})
            for d in sample.get("fds", []):
                r = caps.get(d["fd"])
                tail = f"  [{rights_summary(r['rights'])}]" if r else ""
                lines.append(f"  {d['fd']:>5} {d['type']:<2}{d.get('vtype', ''):<2} "
                             f"{d['flags']:<10} {d['name'].rstrip()}{tail}")
            lines.append(f"Environment variable names: {', '.join(sample.get('env', [])) or '(none)'}")
            lim = sample.get("limits", {})
            if lim:
                lines.append("Limits: " + ", ".join(f"{k}={v[0]}/{v[1]}" for k, v in sorted(lim.items())))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
