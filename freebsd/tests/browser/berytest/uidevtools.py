# SPDX-License-Identifier: GPL-3.0-only
"""Read the browser's own window layout (Views) through UI DevTools.

Chromium serves its native UI tree (toolbar, buttons, location bar...) on
--enable-ui-devtools=PORT with a DevTools-like protocol over WebSocket at
ws://127.0.0.1:PORT/0 (its HTTP /json endpoints do not answer). Nodes carry
their class in attributes ("class", "ToolbarView"); CSS.getMatchedStylesForNode
returns one rule per class level, and the View level has X, Y, Width,
Height (relative to the parent) and Visible. Standard library only.
"""

import base64
import itertools
import json
import os
import socket
import struct
import time


class WebSocket:
    def __init__(self, url, timeout=15):
        assert url.startswith("ws://")
        hostport, _, path = url[5:].partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("UI DevTools closed the connection during handshake")
            head += chunk
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"UI DevTools handshake failed: {status!r}")
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise ConnectionError("UI DevTools connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        data = text.encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        message = b""
        while True:
            b0, b1 = self._read(2)
            opcode, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                raise ConnectionError("UI DevTools closed the connection")
            if opcode == 9:
                continue
            if opcode in (0, 1, 2):
                message += payload
                if b0 & 0x80:
                    return message.decode()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class UIDevTools:
    def __init__(self, port, timeout=30):
        deadline = time.monotonic() + timeout
        last = None
        while True:
            try:
                self.ws = WebSocket(f"ws://127.0.0.1:{port}/0")
                break
            except OSError as e:
                last = e
                if time.monotonic() > deadline:
                    raise ConnectionError(f"UI DevTools not reachable on port {port}: {last}")
                time.sleep(0.5)
        self.ids = itertools.count(1)

    def send(self, method, params=None):
        mid = next(self.ids)
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def document(self):
        return self.send("DOM.getDocument")["root"]

    def properties(self, node_id):
        """All properties of one view (every class level, merged)."""
        res = self.send("CSS.getMatchedStylesForNode", {"nodeId": node_id})
        props = {}
        rules = [r.get("rule", {}).get("style", {}) for r in res.get("matchedCSSRules", [])]
        if res.get("inlineStyle"):
            rules.append(res["inlineStyle"])
        for style in rules:
            for p in style.get("cssProperties", []):
                props.setdefault(p["name"], p.get("value"))
        return props

    def close(self):
        self.ws.close()


def node_attrs(node):
    a = node.get("attributes") or []
    return dict(zip(a[0::2], a[1::2]))


def node_name(node):
    """The view's class (ToolbarView, HomeButton...), else its DOM name."""
    attrs = node_attrs(node)
    return attrs.get("class") or attrs.get("name") or node.get("nodeName") or ""


def walk(node, depth=0, parent=None):
    yield node, depth, parent
    for child in node.get("children", []) or []:
        yield from walk(child, depth + 1, node)


def find(root, name):
    return [n for n, _, _ in walk(root) if node_name(n) == name]


def _get(props, name):
    for k, v in props.items():
        if k.lower() == name:
            return v
    return None


def rect(props):
    """(x, y, width, height) relative to the parent view, or None."""
    try:
        return tuple(int(float(_get(props, k))) for k in ("x", "y", "width", "height"))
    except (ValueError, TypeError):
        return None


def visible(props):
    return str(_get(props, "visible")).lower() == "true"
