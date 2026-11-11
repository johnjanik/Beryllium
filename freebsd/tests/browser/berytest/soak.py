# SPDX-License-Identifier: GPL-3.0-only
"""Many runs in a row, a ledger of every run, and the count that decides
when the renderer lockdown may become the default.

plan/18 section 3.2 (P7) wants "the suite passes the gate on every run" to
be a number fixed before the runs are made. The owner left the number to
this file on 11 November 2026: BAR_RUNS whole-suite lockdown runs in a row
with nothing failing, on one package version, over at least BAR_BOOTS
boots, at least BAR_WINDOWS of them with windows open (a headless run
skips the toolbar tests). A whole run takes about three minutes, so a
night is enough for the runs and the boots are what take days.

Every run adds one line to the ledger. A run of some groups only, or one
without the lockdown, is recorded and does not count either way. A run
that hangs or dies counts as a run that failed. A run the user stops is
not recorded.
"""

import json
import os
import re
import signal
import subprocess
import time

BAR_RUNS = 100
BAR_BOOTS = 3
BAR_WINDOWS = 20

# A whole run takes about three minutes. One that has not finished in this
# many seconds is taken to hang, and is stopped with its browsers.
RUN_TIMEOUT = 30 * 60

CLEAN = "clean"
FAILED = "failed"
HUNG = "hung"
DIED = "died"


def default_ledger():
    return os.path.join(os.path.expanduser("~"), "beryllium-test-results", "ledger.jsonl")


def parse_boot_time(sysctl_text=None, proc_stat=None):
    """Seconds since the epoch at which this boot began, from FreeBSD's
    `sysctl -n kern.boottime` ("{ sec = 1794400000, usec = 5 } Wed ...") or
    Linux's /proc/stat ("btime 1794400000"); None if neither says."""
    if sysctl_text:
        m = re.search(r"\bsec\s*=\s*(\d+)", sysctl_text)
        if m:
            return int(m.group(1))
    if proc_stat:
        m = re.search(r"^btime\s+(\d+)", proc_stat, re.M)
        if m:
            return int(m.group(1))
    return None


def boot_time():
    try:
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0:
            found = parse_boot_time(sysctl_text=out.stdout)
            if found:
                return found
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with open("/proc/stat") as f:
            return parse_boot_time(proc_stat=f.read())
    except OSError:
        return None


def entry_from_report(report, boot, results):
    """The ledger line for a finished run, from its report.json."""
    options = report.get("options", {})
    info = report.get("info", {})
    counts = {}
    not_passed = []
    for r in report.get("results", []):
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        if r["outcome"] not in ("pass", "skip"):
            not_passed.append(f"{r['outcome']} {r['test']}")
    return {
        "started": report.get("started", ""),
        "seconds": report.get("seconds", 0),
        "boot": boot,
        "package": info.get("beryllium_package", "") or "unknown",
        "lockdown": str(info.get("renderer_lockdown", "")).startswith("requested"),
        "whole": not options.get("groups"),
        "headless": bool(options.get("headless")),
        "outcome": FAILED if not_passed else CLEAN,
        "counts": counts,
        "not_passed": not_passed,
        "results": results,
    }


def entry_without_report(outcome, started, seconds, boot, package, lockdown, whole,
                         headless, results):
    """The ledger line for a run that left no report: it hung or died."""
    return {
        "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "seconds": round(seconds),
        "boot": boot,
        "package": package or "unknown",
        "lockdown": lockdown,
        "whole": whole,
        "headless": headless,
        "outcome": outcome,
        "counts": {},
        "not_passed": [f"{outcome}: the run left no report"],
        "results": results,
    }


def append(ledger, entry):
    os.makedirs(os.path.dirname(os.path.abspath(ledger)), exist_ok=True)
    with open(ledger, "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def read(ledger):
    """The ledger's entries, oldest first. A line that is not JSON (a write
    cut short by a power failure) is skipped."""
    entries = []
    try:
        with open(ledger) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        pass
    return entries


def counts_toward_the_bar(entry):
    return bool(entry.get("lockdown")) and bool(entry.get("whole"))


def tally(entries):
    """Per package version, in the order first seen: how many whole-suite
    lockdown runs, how many clean, and the run of clean ones that ends at
    the latest, with the boots it spans and how many had windows."""
    packages = {}
    for e in entries:
        if not counts_toward_the_bar(e):
            continue
        p = packages.setdefault(e.get("package", "unknown"), {
            "runs": 0, "clean": 0, "streak": 0, "boots": set(), "windows": 0,
            "last_bad": None})
        p["runs"] += 1
        if e.get("outcome") == CLEAN:
            p["clean"] += 1
            p["streak"] += 1
            p["boots"].add(e.get("boot"))
            if not e.get("headless"):
                p["windows"] += 1
        else:
            p["streak"] = 0
            p["boots"] = set()
            p["windows"] = 0
            p["last_bad"] = e
    for p in packages.values():
        p["boots"] = len(p["boots"] - {None})
        p["met"] = (p["streak"] >= BAR_RUNS and p["boots"] >= BAR_BOOTS
                    and p["windows"] >= BAR_WINDOWS)
    return packages


def tally_lines(entries, only=None):
    """The tally in words; only: one package version, for the line a
    repeat prints after each run."""
    packages = tally(entries)
    if only is not None:
        packages = {k: v for k, v in packages.items() if k == only}
        if not packages:
            return []
    if not packages:
        return ["No whole-suite lockdown run in the ledger yet "
                "(make one with: run --lockdown, or many with: run --lockdown --repeat N)."]
    lines = []
    for name, p in packages.items():
        lines.append(f"{name}: {p['runs']} whole-suite lockdown runs, {p['clean']} clean, "
                     f"{p['runs'] - p['clean']} not")
        lines.append(f"  clean in a row, counting back from the latest: {p['streak']} "
                     f"(over {p['boots']} boot{'' if p['boots'] == 1 else 's'}, "
                     f"{p['windows']} with windows)")
        short = []
        if p["streak"] < BAR_RUNS:
            short.append(f"{BAR_RUNS - p['streak']} more runs")
        if p["boots"] < BAR_BOOTS:
            short.append(f"{BAR_BOOTS - p['boots']} more boot"
                         f"{'' if BAR_BOOTS - p['boots'] == 1 else 's'}")
        if p["windows"] < BAR_WINDOWS:
            short.append(f"{BAR_WINDOWS - p['windows']} more with windows")
        lines.append(f"  the bar ({BAR_RUNS} in a row, {BAR_BOOTS} boots, {BAR_WINDOWS} with "
                     f"windows; plan/18 section 3.2): "
                     + ("met" if p["met"] else "not yet, needs " + ", ".join(short)))
        bad = p["last_bad"]
        if bad:
            lines.append(f"  last run that was not clean: {bad.get('started', '?')}, "
                         f"{bad.get('outcome', '?')}")
            for t in bad.get("not_passed", [])[:8]:
                lines.append(f"    {t}")
            lines.append(f"    {bad.get('results', '')}")
    return lines


def run_once(start, timeout=RUN_TIMEOUT):
    """Wait for one child run to end. start() starts it and returns the
    Popen object; it must give the child a session of its own
    (start_new_session=True), so that a hung run can be stopped together
    with the browsers it started. Returns (exit status or None if it hung,
    seconds)."""
    started = time.time()
    child = start()
    try:
        status = child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop(child)
        return None, time.time() - started
    except KeyboardInterrupt:
        stop(child)
        raise
    return status, time.time() - started


def stop(child):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, sig)
        except OSError:
            return
        try:
            child.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


def repeat(times, base, ledger, launch, describe, say=print, pause=2):
    """Make `times` runs. launch(results_dir) makes one and returns
    (exit status or None, seconds); it adds the run's ledger line itself
    when the run ends with a report. describe(outcome, started, seconds,
    results_dir) gives the ledger line for a run that left none.
    Returns 0 if every run was clean."""
    worst = 0
    for i in range(1, times + 1):
        results = os.path.join(base, f"run-{i:03d}")
        before = len(read(ledger))
        started = time.time()
        try:
            status, seconds = launch(results)
        except KeyboardInterrupt:
            say(f"run {i} of {times}: stopped by you; not recorded")
            return 130
        entries = read(ledger)
        if len(entries) > before:
            outcome = entries[-1].get("outcome", FAILED)
        else:
            outcome = HUNG if status is None else DIED
            append(ledger, describe(outcome, started, seconds, results))
            entries = read(ledger)
        if outcome != CLEAN:
            worst = 1
        say(f"run {i} of {times}: {outcome} ({round(seconds)} s)  {results}")
        for line in tally_lines(entries, only=entries[-1].get("package"))[:2]:
            say("  " + line)
        if i < times:
            time.sleep(pause)
    return worst
