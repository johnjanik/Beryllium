# SPDX-License-Identifier: GPL-3.0-only
"""Launch Beryllium for a test, isolated from the user's own profile.

Each launch gets its own HOME (so ~/.config/beryllium, ~/.cache and the
rest are fresh and thrown away), keeps the display variables, and logs the
browser's stderr to the results directory.
"""

import fcntl
import json
import os
import shutil
import signal
import subprocess
import time

from .cdp import CDPError, Connection, Page

DEFAULT_BINARIES = ("/usr/local/bin/beryllium", "/usr/local/share/beryllium/beryllium")
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


def _high_fd(fd):
    new = fcntl.fcntl(fd, fcntl.F_DUPFD, 10)
    os.close(fd)
    return new


class Browser:
    def __init__(self, ctx, name, args=(), headless=None, user_data_dir=False,
                 prefs=None, env=None):
        self.ctx = ctx
        self.name = name
        self.binary = find_binary(ctx.options.browser)
        self.headless = ctx.options.headless if headless is None else headless
        self.root = ctx.scratch(name)
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home, exist_ok=True)
        self.user_data_dir = os.path.join(self.root, "profile") if user_data_dir else None
        self.args = list(args)
        self.prefs = prefs
        self.extra_env = env or {}
        self.log_path = ctx.artifact(f"{name}.stderr.log")
        self.proc = None
        self.conn = None
        self.version = {}

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
        return cmd

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
        if self.prefs is not None:
            base = self.user_data_dir or os.path.join(self.home, ".config", "beryllium")
            os.makedirs(os.path.join(base, "Default"), exist_ok=True)
            with open(os.path.join(base, "Default", "Preferences"), "w") as f:
                json.dump(self.prefs, f)
        to_browser_r, to_browser_w = os.pipe()
        from_browser_r, from_browser_w = os.pipe()
        child_r, child_w = _high_fd(to_browser_r), _high_fd(from_browser_w)

        def preexec():
            os.dup2(child_r, 3)
            os.dup2(child_w, 4)
            os.setsid()

        self.log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            self.command(), env=self.environment(), cwd=self.root,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
            pass_fds=(3, 4), preexec_fn=preexec)
        os.close(child_r)
        os.close(child_w)
        self.conn = Connection(from_browser_r, to_browser_w)
        try:
            self.version = self.conn.send("Browser.getVersion", timeout=timeout)
            self.conn.send("Target.setDiscoverTargets", {"discover": True})
        except CDPError as e:
            self.stop()
            raise CDPError(f"{self.binary} did not start: {e}; log: {self.log_path}\n"
                           + self.log_tail())
        return self

    def stop(self):
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

    def new_page(self, url=None, timeout=45):
        tid = self.conn.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self.conn.send("Target.attachToTarget",
                             {"targetId": tid, "flatten": True})["sessionId"]
        page = Page(self.conn, tid, sid)
        for domain in ("Page", "Runtime", "Inspector"):
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

    def log_tail(self, lines=40):
        try:
            with open(self.log_path, "rb") as f:
                data = f.read().decode(errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(data[-lines:])

    def product(self):
        return self.version.get("product", "")

    def url(self, path):
        """An internal page URL, e.g. url("version") -> beryllium://version."""
        return f"{self.ctx.options.scheme}://{path}"

    def wait(self, seconds):
        time.sleep(seconds)
