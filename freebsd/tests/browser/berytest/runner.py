# SPDX-License-Identifier: GPL-3.0-only
"""Run the test modules and write report.txt and report.json."""

import io
import json
import os
import platform
import subprocess
import sys
import time
import traceback
import unittest

from . import capsicum


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._start = {}

    def startTest(self, test):
        self._start[test.id()] = time.monotonic()
        super().startTest(test)

    def _add(self, test, outcome, detail=""):
        began = self._start.get(test.id(), time.monotonic())
        self.records.append({"test": test.id(), "outcome": outcome,
                             "seconds": round(time.monotonic() - began, 1),
                             "detail": detail})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._add(test, "ERROR", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._add(test, "skip", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._add(test, "known bug", self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._add(test, "FIXED (was a known bug)")


def system_info():
    def cmd(*args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"system": " ".join(platform.uname()),
            "freebsd_version": cmd("freebsd-version", "-ku").replace("\n", " / "),
            "beryllium_package": cmd("pkg", "query", "%n-%v", "beryllium"),
            "python": sys.version.split()[0]}


def run(ctx, suite):
    stream = io.StringIO()
    tee = Tee(sys.stdout, stream)
    runner = unittest.TextTestRunner(stream=tee, verbosity=2, resultclass=Result)
    started = time.time()
    result = runner.run(suite)
    info = system_info()
    info["browser"] = getattr(ctx, "browser_version", {})
    info["browser_binary"] = getattr(ctx, "browser_binary", "") or ctx.options.browser or ""
    # So two reports of the same build can be told apart: the switches the
    # run gave the browser, and whether they ask for the renderer lockdown.
    args = getattr(ctx.options, "browser_args", None) or []
    info["browser_args"] = " ".join(args) or "(none)"
    info["renderer_lockdown"] = ("requested (the sandbox tests are a gate)"
                                 if capsicum.lockdown_requested(ctx.options) else "not requested")
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
              "seconds": round(time.time() - started),
              "info": info, "options": vars(ctx.options),
              "results": result.records,
              "notes": [{"test": t, "text": x} for t, x in ctx.notes]}
    with open(ctx.artifact("report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    with open(ctx.artifact("report.txt"), "w") as f:
        f.write(text_report(report))
    counts = {}
    for r in result.records:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    print("\n" + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    print(f"Report: {ctx.artifact('report.txt')}")
    return 0 if result.wasSuccessful() else 1


def text_report(report):
    out = [f"Beryllium test report, {report['started']} ({report['seconds']} s)", ""]
    for k, v in report["info"].items():
        out.append(f"{k}: {v}")
    out.append("")
    width = max([len(r["test"]) for r in report["results"]] + [10])
    for r in report["results"]:
        out.append(f"{r['outcome']:<10} {r['test']:<{width}} {r['seconds']:>6} s")
    problems = [r for r in report["results"] if r["outcome"] not in ("pass", "skip")]
    if problems:
        out += ["", "Details", "======="]
        for r in problems:
            out += ["", f"{r['outcome']}: {r['test']}", r["detail"].rstrip()]
    if report["notes"]:
        out += ["", "Notes", "====="]
        for n in report["notes"]:
            out += ["", f"{n['test']}:", n["text"].rstrip()]
    skips = [r for r in report["results"] if r["outcome"] == "skip"]
    if skips:
        out += ["", "Skipped", "======="]
        out += [f"{r['test']}: {r['detail']}" for r in skips]
    return "\n".join(out) + "\n"


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()
