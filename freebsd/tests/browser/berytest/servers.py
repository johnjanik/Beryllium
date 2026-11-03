# SPDX-License-Identifier: GPL-3.0-only
"""Local servers for the tests: a static file server for test pages and
media, and a recording proxy that notes every outside host the browser
tries to reach (and, by default, refuses to connect it)."""

import functools
import http.server
import socket
import socketserver
import threading
import time


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class FixtureServer:
    """Serves a directory on 127.0.0.1 (loopback bypasses any proxy)."""

    def __init__(self, directory):
        handler = functools.partial(_QuietHandler, directory=directory)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path=""):
        return f"http://127.0.0.1:{self.port}/{path.lstrip('/')}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class RecordingProxy:
    """HTTP proxy that records requested hosts. With allow=False (the
    default) it answers 403 and nothing leaves the machine."""

    def __init__(self, allow=False):
        self.allow = allow
        self.requests = []  # (time, method, host, port)
        self._lock = threading.Lock()
        proxy = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                line = self.rfile.readline(65536).decode("latin-1").strip()
                if not line:
                    return
                headers = []
                while True:
                    h = self.rfile.readline(65536)
                    if h in (b"\r\n", b"\n", b""):
                        break
                    headers.append(h)
                parts = line.split()
                if len(parts) < 2:
                    return
                method, target = parts[0], parts[1]
                if method == "CONNECT":
                    host, _, port = target.rpartition(":")
                else:
                    rest = target.split("://", 1)[-1]
                    hostport = rest.split("/", 1)[0]
                    host, _, port = hostport.partition(":")
                    port = port or "80"
                proxy._record(method, host, port)
                if not proxy.allow:
                    self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    return
                if method != "CONNECT":
                    self.wfile.write(b"HTTP/1.1 501 Not Implemented\r\nContent-Length: 0\r\n\r\n")
                    return
                try:
                    upstream = socket.create_connection((host, int(port)), timeout=20)
                except OSError:
                    self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    return
                self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                _pipe(self.connection, upstream)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _record(self, method, host, port):
        with self._lock:
            self.requests.append((time.time(), method, host.strip("[]"), port))

    def hosts(self):
        with self._lock:
            return sorted({h for _, _, h, _ in self.requests})

    def address(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _pipe(a, b):
    def copy(src, dst):
        try:
            while True:
                data = src.recv(1 << 16)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
    t = threading.Thread(target=copy, args=(b, a), daemon=True)
    t.start()
    copy(a, b)
    t.join(timeout=5)
