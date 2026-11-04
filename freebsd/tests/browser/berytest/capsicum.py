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
KDUMP_RE = re.compile(r"^\s*(\d+)\s+(?:\d+\s+)?(\S+)\s+(CAP|NAMI|SCTL)\s+(.*?)\s*$")
SAMPLES = 8  # example paths kept per failure


def _unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def parse_kdump(lines):
    """Per pid: capability failures (message -> count, with example paths
    from the lookup that caused them) and sysctl names read."""
    procs = {}
    last_path = {}
    for line in lines:
        m = KDUMP_RE.match(line)
        if not m:
            continue
        pid, comm, kind, data = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        p = procs.setdefault(pid, {"comm": comm, "cap": collections.Counter(),
                                   "cap_paths": collections.defaultdict(list),
                                   "sysctl": collections.Counter(), "lookups": 0})
        if kind == "NAMI":
            last_path[pid] = _unquote(data)
            p["lookups"] += 1
        elif kind == "SCTL":
            p["sysctl"][_unquote(data)] += 1
        else:  # CAP
            message = data
            p["cap"][message] += 1
            path = last_path.get(pid)
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


def limits(pid, text=None):
    """{rlimit: (soft, hard)} from procstat -l."""
    rows = _table(text if text is not None else _run(["procstat", "-l", str(pid)]))
    return {r["RLIMIT"]: (r.get("SOFT", ""), r.get("HARD", "")) for r in rows if "RLIMIT" in r}


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
        t = out.setdefault(ptype, {"pids": [], "cap": collections.Counter(),
                                   "cap_paths": collections.defaultdict(list),
                                   "sysctl": collections.Counter()})
        t["pids"].append(pid)
        t["cap"].update(p["cap"])
        t["sysctl"].update(p["sysctl"])
        for message, paths in p["cap_paths"].items():
            examples = t["cap_paths"][message]
            for path in paths:
                if path not in examples and len(examples) < SAMPLES:
                    examples.append(path)
    for t in out.values():
        t["sysctl_blocked"] = (sorted(n for n in t["sysctl"] if n not in readable)
                               if readable is not None else None)
    return out


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
        if t["cap"]:
            lines.append("Would be refused in capability mode (count, message, example paths):")
            for message, n in t["cap"].most_common():
                lines.append(f"  {n:6d}  {message}")
                for path in t["cap_paths"].get(message, []):
                    lines.append(f"            {path}")
        else:
            lines.append("No capability failures recorded.")
        lines.append("")
        if t["sysctl"]:
            note = (f"readable in capability mode per {readable_from}" if readable_from
                    else "no oracle result for this kernel to say which are readable")
            lines.append(f"Sysctls read ({note}):")
            blocked = set(t["sysctl_blocked"] or [])
            for name, n in sorted(t["sysctl"].items()):
                mark = "" if t["sysctl_blocked"] is None else (
                    "  REFUSED in capability mode" if name in blocked else "  ok")
                lines.append(f"  {n:6d}  {name}{mark}")
            lines.append("")
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
