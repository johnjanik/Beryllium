# SPDX-License-Identifier: GPL-3.0-only
"""Launch Beryllium for a test, isolated from the user's own profile.

Each launch gets its own HOME (so ~/.config/beryllium, ~/.cache and the
rest are fresh and thrown away), keeps the display variables, and logs the
browser's stderr to the results directory.
"""

import fcntl
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import time

from .cdp import CDPError, Connection, Page

DEFAULT_BINARIES = ("/usr/local/bin/beryllium", "/usr/local/share/beryllium/beryllium")
# The launcher sets "ulimit -c 0"; --cores runs the browser itself.
DIRECT_BINARY = "/usr/local/share/beryllium/beryllium"
KEEP_ENV = ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
            "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DBUS_SESSION_BUS_ADDRESS",
            "LANG", "LC_ALL", "LC_CTYPE", "TZ", "PATH", "USER", "LOGNAME", "SHELL",
            "PULSE_SERVER", "AUDIODEV")


def find_binary(explicit=None):
    if explicit:
        return explicit
    for b in DEFAULT_BINARIES:
        if os.access(b, os.X_OK):
            return b
    raise FileNotFoundError("Beryllium not found; install it or pass --browser PATH")


def has_display():
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def context_lines(lines, needle, after=16):
    """For each line containing needle, that line and the lines after it
    that continue the same log message: Chromium prefixes each message with
    "[pid:tid:date:LEVEL:file(line)]" and prints a multi-line message (a
    stack trace) with the extra lines unprefixed. Each result is one block
    (a string with newlines), at most after lines long."""
    blocks = []
    for i, line in enumerate(lines):
        if needle not in line:
            continue
        block = [line]
        for extra in lines[i + 1:i + 1 + after]:
            if extra.startswith("["):
                break
            block.append(extra)
        blocks.append("\n".join(block))
    return blocks


def describe_exit(status):
    """A wait status as Popen reports it, in words; None for a process
    that still runs."""
    if status is None:
        return None
    if status < 0:
        try:
            name = signal.Signals(-status).name
        except ValueError:
            name = "unknown"
        return f"was killed by signal {-status} ({name})"
    return f"exited with status {status}"


# What a browser log says about why the process ended, as opposed to the
# stack frames and register dump that follow a crash and fill its last lines.
TELLING = re.compile(r":FATAL:|:ERROR:|Received signal|[Ee]rror|Goodbye|[Ff]ailed|"
                     r"[Ww]ayland|wl_|terminat|[Ll]ost|crash", re.ASCII)
FRAME = re.compile(r"^\s*(#\d+ 0x|\[end of stack trace\]|[a-z0-9]{2,3}: [0-9a-f]{16}\b)")
# Lines a healthy browser writes over and over. The FreeBSD port's patch to
# wayland_frame_manager.cc logs this warning for every frame shown, with any
# GPU and whichever way the buffer is synchronised (6469 times in one suite
# run of 0.20.3.16); it says nothing about a failure and would fill every
# excerpt.
NOISE = re.compile(r"SyncMethod::kSyncobj is not supported")
# "[pid:tid:MMDD/HHMMSS.micro:" in front of a log line: differs on every
# line, so it is left out when two lines are compared.
STAMP = re.compile(r"^\[\d+:\d+:\d+/[\d.]+:")


# Log lines whose cause is known, with what they mean. Each was met in a
# report and traced: add to this only what has been.
EXPLANATIONS = (
    (re.compile(r"importing the supplied dmabufs failed"),
     "the Wayland compositor could not import a buffer the browser drew, and Chromium "
     "stops on any Wayland error (signal 5); with --render-node-override this means the "
     "named GPU is not one the compositor can take buffers from (0.20.3.16 with the Intel "
     "node on a desktop drawn by the NVIDIA GPU, 10 November 2026)"),
)


def explain(lines):
    """What is known about the failure these log lines show, or ""."""
    for pattern, meaning in EXPLANATIONS:
        if any(pattern.search(l) for l in lines):
            return meaning
    return ""


def quiet(lines):
    """Log lines without the per-frame noise and the blank ones."""
    return [l for l in lines if l.strip() and not NOISE.search(l)]


def collapse(lines):
    """Runs of lines that differ only in their stamp, as one line each with
    the count."""
    out, last, count = [], None, 0
    for line in lines:
        key = STAMP.sub("[", line)
        if key == last:
            count += 1
            continue
        if count > 1:
            out[-1] += f" ({count} times)"
        out.append(line)
        last, count = key, 1
    if count > 1:
        out[-1] += f" ({count} times)"
    return out


def telling_lines(lines, limit=8, window=200):
    """The last limit lines, of the last window that are neither noise nor
    stack frames, that say something about a failure; without any, the last
    limit of that window."""
    recent = [l.strip() for l in quiet(lines) if not FRAME.match(l)][-window:]
    recent = collapse(recent)
    telling = [l for l in recent if TELLING.search(l)]
    return [l[:300] for l in (telling or recent)[-limit:]]


def kernel_lines(pid, path="/var/log/messages", limit=3):
    """What the kernel logged about a process: FreeBSD writes "pid N
    (name), jid J, uid U: exited on signal S (core dumped)" for a crash."""
    needle = f"pid {pid} ("
    try:
        with open(path, errors="replace") as f:
            return [l.strip() for l in f if needle in l][-limit:]
    except OSError:
        return []


def _high_fd(fd):
    new = fcntl.fcntl(fd, fcntl.F_DUPFD, 10)
    os.close(fd)
    return new


class Browser:
    def __init__(self, ctx, name, args=(), headless=None, user_data_dir=False,
                 prefs=None, env=None, settings_from=None, wrapper=None):
        self.ctx = ctx
        self.name = name
        self.binary = find_binary(ctx.options.browser)
        self.cores = getattr(ctx.options, "cores", False)
        if self.cores and self.binary == DEFAULT_BINARIES[0] and os.access(DIRECT_BINARY, os.X_OK):
            self.binary = DIRECT_BINARY
        self.core_dir = ctx.artifact("cores") if self.cores else None
        self.headless = ctx.options.headless if headless is None else headless
        self.root = ctx.scratch(name)
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home, exist_ok=True)
        self.user_data_dir = os.path.join(self.root, "profile") if user_data_dir else None
        self.args = list(args)
        self.prefs = prefs
        self.settings_from = settings_from
        # A command the browser runs under, e.g. ["ktrace", "-i", ...].
        self.wrapper = list(wrapper or [])
        self.extra_env = env or {}
        self.log_path = ctx.artifact(f"{name}.stderr.log")
        self.proc = None
        self.conn = None
        self.version = {}
        self._stopping = False
        self._death_told = False

    # -- lifecycle -----------------------------------------------------------

    def command(self):
        cmd = [self.binary, "--remote-debugging-pipe", "--no-first-run",
               "--no-default-browser-check", "--enable-logging=stderr", "--v=0",
               "--autoplay-policy=no-user-gesture-required", "--window-size=1280,900"]
        if self.headless:
            cmd.append("--headless")
        if self.user_data_dir:
            cmd.append(f"--user-data-dir={self.user_data_dir}")
        cmd += self.ctx.options.browser_args + self.args
        cmd.append("about:blank")
        return self.wrapper + cmd

    def environment(self):
        env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        env["HOME"] = self.home
        real_home = os.path.expanduser("~")
        xauth = os.path.join(real_home, ".Xauthority")
        if "XAUTHORITY" not in env and os.path.exists(xauth):
            env["XAUTHORITY"] = xauth
        env.update(self.extra_env)
        return env

    def start(self, timeout=90):
        base = self.user_data_dir or os.path.join(self.home, ".config", "beryllium")
        if self.settings_from:
            # A copy of someone's settings (not their history, cookies or
            # passwords, which live in other files) in the throwaway profile.
            os.makedirs(os.path.join(base, "Default"), exist_ok=True)
            for rel in ("Local State", os.path.join("Default", "Preferences")):
                src = os.path.join(self.settings_from, rel)
                if os.path.isfile(src):
                    shutil.copyfile(src, os.path.join(base, rel))
        elif self.prefs is not None:
            os.makedirs(os.path.join(base, "Default"), exist_ok=True)
            with open(os.path.join(base, "Default", "Preferences"), "w") as f:
                json.dump(self.prefs, f)
        to_browser_r, to_browser_w = os.pipe()
        from_browser_r, from_browser_w = os.pipe()
        child_r, child_w = _high_fd(to_browser_r), _high_fd(from_browser_w)

        cores = self.cores

        def preexec():
            os.dup2(child_r, 3)
            os.dup2(child_w, 4)
            os.setsid()
            if cores:
                _, hard = resource.getrlimit(resource.RLIMIT_CORE)
                resource.setrlimit(resource.RLIMIT_CORE, (hard, hard))

        if self.core_dir:
            os.makedirs(self.core_dir, exist_ok=True)
        self.started_at = time.time()
        self.log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            self.command(), env=self.environment(), cwd=self.core_dir or self.root,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
            pass_fds=(3, 4), preexec_fn=preexec)
        os.close(child_r)
        os.close(child_w)
        self.conn = Connection(from_browser_r, to_browser_w)
        self.conn.why_closed = self.death
        try:
            self.version = self.conn.send("Browser.getVersion", timeout=timeout)
            self.conn.send("Target.setDiscoverTargets", {"discover": True})
        except CDPError as e:
            self.stop()
            # An error about a closed connection already ends with the log.
            tail = "" if "last lines of its log" in str(e) else "\n" + self.log_tail()
            raise CDPError(f"{self.binary} did not start: {e}; log: {self.log_path}{tail}")
        return self

    def ended(self):
        """None while the browser process runs; otherwise how it ended:
        "exited with status 1" or "was killed by signal 11 (SIGSEGV)"."""
        if not self.proc:
            return None
        return describe_exit(self.proc.poll())

    def death(self):
        """For an error about a closed connection: how the browser process
        ended, and the first time also the last lines of its log and the
        kernel's line about it. The pipe closes a moment before the process
        is gone, so this waits for it briefly."""
        if not self.proc or self._stopping:
            return ""
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return ("the browser process is still running; it closed the "
                    "debugging pipe")
        how = f"the browser process (pid {self.proc.pid}) {self.ended()}"
        if self._death_told:
            return how + ", as reported for an earlier test"
        self._death_told = True
        parts = [how]
        kernel = kernel_lines(self.proc.pid)
        if kernel:
            parts.append("kernel: " + " | ".join(kernel))
        log = self._log()
        known = explain(log[-400:])
        if known:
            parts.append("known cause: " + known)
        tail = telling_lines(log)
        parts.append("last lines of its log (" + os.path.basename(self.log_path) + "):\n  "
                     + "\n  ".join(tail) if tail else "its log is empty")
        return "; ".join(parts)

    def death_note(self):
        """For a test's notes: how the process ended, the kernel's line and
        more of the log than an error message carries."""
        log = self._log()
        known = explain(log[-400:])
        return (f"the browser process (pid {self.proc.pid}) {self.ended()}\n"
                f"kernel: {' | '.join(kernel_lines(self.proc.pid)) or 'no line about it'}\n"
                + (f"known cause: {known}\n" if known else "")
                + f"log ({os.path.basename(self.log_path)}):\n  "
                + ("\n  ".join(telling_lines(log, limit=20)) or "empty"))

    def stop(self):
        self._stopping = True
        if self.conn and not self.conn.closed:
            try:
                self.conn.send("Browser.close", timeout=10)
            except CDPError:
                pass
        if self.proc:
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                self.proc.wait(timeout=15)
        if self.conn:
            self.conn.close()
        if getattr(self, "log", None):
            self.log.close()
        if not self.ctx.options.keep_profiles:
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -- pages -----------------------------------------------------------------

    def new_page(self, url=None, timeout=45, domains=("Page", "Runtime", "Inspector")):
        """A new tab with a DevTools session. domains are the DevTools domains
        switched on for it; scripts can be evaluated without the Runtime
        domain, which is the one a page can notice."""
        tid = self.conn.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self.conn.send("Target.attachToTarget",
                             {"targetId": tid, "flatten": True})["sessionId"]
        page = Page(self.conn, tid, sid)
        for domain in domains:
            try:
                page.send(f"{domain}.enable")
            except CDPError:
                pass
        if url:
            page.navigate(url, timeout=timeout)
        return page

    def close_page(self, page):
        try:
            self.conn.send("Target.closeTarget", {"targetId": page.target_id}, timeout=10)
        except CDPError:
            pass

    def crashes(self, since=0):
        return [e["params"] for e in self.conn.events("Target.targetCrashed", since)]

    def log_lines(self, needle, limit=200):
        """Lines of the browser's log (its stderr, shared by its children)
        containing needle: the last limit of them, or all of them with
        limit=None. A check that must not miss a line asks for all: the
        lockdown gate read the last 200 from 0.20.3.13 to 0.20.3.18, when
        the log had grown past that, and so saw only its end."""
        found = [l for l in self._log() if needle in l]
        return found if limit is None else found[-limit:]

    def log_context(self, needle, after=16, limit=20):
        """Each log line containing needle with the lines that belong to the
        same message after it (a stack trace, for one): see context_lines."""
        return context_lines(self._log(), needle, after)[:limit]

    def _log(self):
        try:
            with open(self.log_path, "rb") as f:
                return f.read().decode(errors="replace").splitlines()
        except OSError:
            return []

    def log_tail(self, lines=40):
        """The end of the log, without the per-frame noise (see NOISE)."""
        return "\n".join(collapse(quiet(self._log()))[-lines:])

    def record_version(self):
        """The first browser started in a run names the browser in the report."""
        if not getattr(self.ctx, "browser_version", None):
            self.ctx.browser_version = self.version
            self.ctx.browser_binary = self.binary

    def product(self):
        return self.version.get("product", "")

    def url(self, path):
        """An internal page URL, e.g. url("version") -> beryllium://version."""
        return f"{self.ctx.options.scheme}://{path}"

    def wait(self, seconds):
        time.sleep(seconds)
