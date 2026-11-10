# SPDX-License-Identifier: GPL-3.0-only
"""A small Chrome DevTools Protocol client over --remote-debugging-pipe.

The browser reads commands from file descriptor 3 and writes replies and
events to file descriptor 4, one JSON message per NUL-terminated record
(the transport Puppeteer and Playwright use). Standard library only.
"""

import itertools
import json
import os
import threading
import time


class CDPError(Exception):
    pass


class TargetCrashed(CDPError):
    """The page's renderer process died; status/error_code as Chromium reports."""

    def __init__(self, target_id, status, error_code):
        super().__init__(f"renderer crashed: status={status} error code={error_code}")
        self.target_id = target_id
        self.status = status
        self.error_code = error_code


class JSError(CDPError):
    pass


class Connection:
    def __init__(self, read_fd, write_fd):
        self._r = os.fdopen(read_fd, "rb", buffering=0)
        self._w = os.fdopen(write_fd, "wb", buffering=0)
        self._ids = itertools.count(1)
        self._replies = {}
        self._events = []
        self._cond = threading.Condition()
        self._wlock = threading.Lock()
        self.closed = False
        # Set by the owner of the browser process: a function that says how
        # the process ended, for the errors below.
        self.why_closed = None
        threading.Thread(target=self._reader, daemon=True).start()

    def _closed(self, what, error=None):
        """The error for a command or wait that met a closed connection,
        with how the browser process ended when the owner can tell."""
        text = f"{what}: browser connection closed"
        if error:
            text += f" ({error})"
        why = ""
        if self.why_closed:
            try:
                why = self.why_closed()
            except Exception as e:  # never hide the first error behind this one
                why = f"(how the browser ended could not be read: {e})"
        return CDPError(f"{text}; {why}" if why else text)

    def _reader(self):
        buf = b""
        while True:
            try:
                chunk = self._r.read(1 << 16)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                with self._cond:
                    if "id" in msg:
                        self._replies[msg["id"]] = msg
                    else:
                        self._events.append(msg)
                    self._cond.notify_all()
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    def mark(self):
        """Position in the event log, for waiting on events after this point."""
        with self._cond:
            return len(self._events)

    def events(self, method=None, since=0):
        with self._cond:
            return [e for e in self._events[since:] if method is None or e["method"] == method]

    def _crash_of(self, target_id, since):
        for e in self._events[since:]:
            if e["method"] == "Target.targetCrashed" and e["params"].get("targetId") == target_id:
                p = e["params"]
                return TargetCrashed(target_id, p.get("status"), p.get("errorCode"))
        return None

    def send(self, method, params=None, session=None, timeout=30, target_id=None):
        """Send a command and wait for its reply. With target_id, give up as
        soon as that target's renderer crashes."""
        mid = next(self._ids)
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        since = self.mark()
        with self._wlock:
            try:
                self._w.write(json.dumps(msg).encode() + b"\0")
            except OSError as e:
                raise self._closed(method, e)
        deadline = time.monotonic() + timeout
        with self._cond:
            while mid not in self._replies:
                if target_id:
                    crash = self._crash_of(target_id, since)
                    if crash:
                        raise crash
                if self.closed:
                    break
                left = deadline - time.monotonic()
                if left <= 0:
                    raise CDPError(f"{method}: no reply within {timeout} s")
                self._cond.wait(left)
            reply = self._replies.pop(mid, None)
        if reply is None:
            # Outside the lock: finding out how the browser ended can wait
            # for the process and read its log.
            raise self._closed(method)
        if "error" in reply:
            raise CDPError(f"{method}: {reply['error'].get('message')}")
        return reply.get("result", {})

    def wait_event(self, method, session=None, predicate=None, timeout=30,
                   since=None, target_id=None):
        """Wait for an event (from `since` on); returns its params."""
        i = self.mark() if since is None else since
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                while i < len(self._events):
                    e = self._events[i]
                    i += 1
                    if (e["method"] == method
                            and (session is None or e.get("sessionId") == session)
                            and (predicate is None or predicate(e.get("params", {})))):
                        return e.get("params", {})
                    if (target_id and e["method"] == "Target.targetCrashed"
                            and e["params"].get("targetId") == target_id):
                        p = e["params"]
                        raise TargetCrashed(target_id, p.get("status"), p.get("errorCode"))
                if self.closed:
                    break
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"no {method} within {timeout} s")
                self._cond.wait(left)
        raise self._closed(f"waiting for {method}")

    def close(self):
        for f in (self._w, self._r):
            try:
                f.close()
            except OSError:
                pass


class Page:
    """One tab, attached with a flat session."""

    def __init__(self, conn, target_id, session):
        self.conn = conn
        self.target_id = target_id
        self.session = session

    def send(self, method, params=None, timeout=30):
        return self.conn.send(method, params, session=self.session, timeout=timeout,
                              target_id=self.target_id)

    def navigate(self, url, timeout=45, wait_load=True):
        since = self.conn.mark()
        res = self.send("Page.navigate", {"url": url}, timeout=timeout)
        if res.get("errorText"):
            time.sleep(0.5)  # a crash can be reported just after the error
            crash = self.crashed(since)
            if crash:
                raise crash
            raise CDPError(f"navigating to {url}: {res['errorText']}")
        if wait_load:
            self.conn.wait_event("Page.loadEventFired", session=self.session,
                                 timeout=timeout, since=since, target_id=self.target_id)
        return res

    def eval(self, expression, timeout=30):
        """Evaluate JS (promises awaited) and return the value."""
        res = self.send("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
            "userGesture": True}, timeout=timeout)
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            text = d.get("exception", {}).get("description") or d.get("text")
            raise JSError(text)
        return res.get("result", {}).get("value")

    def text(self):
        return self.eval("document.body ? document.body.innerText : ''") or ""

    def crashed(self, since=0):
        with self.conn._cond:
            return self.conn._crash_of(self.target_id, since)
