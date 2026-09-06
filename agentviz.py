#!/usr/bin/env python3
"""Zero-dependency emitter. Point your agent loop at a running relay.

    from agentviz import Viz
    viz = Viz(agent="hermes")

    viz.thinking("Reading the question")
    viz.tool("web_search", "cloudflare outage")
    viz.tool_done("web_search")
    for chunk in stream:
        viz.token(chunk)
    viz.response(final_text)

Nothing here can break your agent: every send is best-effort with a short
timeout, and failures are swallowed unless you pass strict=True.

    python3 agentviz.py demo     # smoke-test the full path
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("AGENTVIZ_URL", "http://127.0.0.1:8766/event")


class Viz:
    """A handle on the visualizer. Every method is fire-and-forget."""

    def __init__(self, agent=None, url=DEFAULT_URL, timeout=0.35, strict=False,
                 enabled=True):
        self.agent = agent
        self.url = url
        self.timeout = timeout
        self.strict = strict
        self.enabled = enabled and os.environ.get("AGENTVIZ_DISABLE") != "1"

    # -- the seven event types -------------------------------------------
    def thinking(self, text=None):
        return self.send("thinking", text=text)

    def token(self, text):
        return self.send("token", text=text)

    def tool(self, name, text=None):
        return self.send("tool_call", name=name, text=text)

    def tool_done(self, name=None):
        return self.send("tool_result", name=name)

    def response(self, text=None):
        return self.send("response", text=text)

    def error(self, text=None):
        return self.send("error", text=text)

    def idle(self):
        return self.send("idle")

    # -- transport --------------------------------------------------------
    def send(self, type, **fields):
        """Post one event. Returns True if the relay took it."""
        if not self.enabled:
            return False
        event = {"type": type}
        if self.agent:
            event["agent"] = self.agent
        event.update({k: v for k, v in fields.items() if v is not None})
        body = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout):
                return True
        except (urllib.error.URLError, OSError, ValueError):
            if self.strict:
                raise
            return False


# ----------------------------------------------------------------- watch

# A terminal view of the same feed. No browser, no canvas, no GPU -- just the
# events as they arrive. This is the cheapest way to watch an agent work.

_C = {"thinking": "\033[36m", "token": "\033[37m", "tool_call": "\033[33m",
      "tool_result": "\033[32m", "response": "\033[1;37m", "error": "\033[31m",
      "idle": "\033[90m"}
_DIM, _OFF = "\033[90m", "\033[0m"


def _ws_connect(url):
    """Minimal RFC 6455 client handshake. Returns a connected socket."""
    import base64
    import socket
    rest = url.split("://", 1)[-1]
    hostport = rest.split("/", 1)[0]
    host, _, port = hostport.partition(":")
    sock = socket.create_connection((host or "127.0.0.1", int(port or 8765)), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        "GET / HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (hostport, key)
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("relay closed during handshake")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    if b" 101 " not in head.split(b"\r\n")[0]:
        raise ConnectionError("relay refused the upgrade")
    return sock, rest


def watch(url=None, color=True):
    """Print every event the relay fans out, until interrupted."""
    import struct
    url = url or os.environ.get("AGENTVIZ_WS", "ws://127.0.0.1:8765")
    try:
        sock, rest = _ws_connect(url)
    except (OSError, ValueError, ConnectionError) as exc:
        print("cannot reach %s (%s) — is relay.py running?" % (url, exc), file=sys.stderr)
        return 1

    def read(n):
        nonlocal rest
        while len(rest) < n:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("relay closed")
            rest += chunk
        out, rest = rest[:n], rest[n:]
        return out

    print("watching %s — ctrl-c to stop" % url)
    try:
        while True:
            b0, b1 = struct.unpack("!BB", read(2))
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", read(8))[0]
            if b1 & 0x80:
                read(4)
            data = read(n) if n else b""
            if (b0 & 0x0F) != 0x1:
                continue
            try:
                ev = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            type = ev.get("type", "?")
            label = ev.get("name") or ""
            text = (ev.get("text") or "").replace("\n", " ")
            stamp = time.strftime("%H:%M:%S")
            agent = ev.get("agent") or ""
            if color:
                print("%s%s%s %s%-12s%s %s%-14s%s %s%s %s" % (
                    _DIM, stamp, _OFF, _C.get(type, ""), type, _OFF,
                    _DIM, agent[:14], _OFF, label and label + " " or "", text, _OFF))
            else:
                print("%s %-12s %-14s %s %s" % (stamp, type, agent[:14], label, text))
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nbye")
    except (OSError, ConnectionError, struct.error) as exc:
        print("disconnected: %s" % exc, file=sys.stderr)
        return 1
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return 0


# ------------------------------------------------------------------ demo

DEMO = [
    (0.0, "thinking", {"text": "Reading the question"}),
    (1.1, "thinking", {"text": "This needs current data — I should search"}),
    (1.0, "tool_call", {"name": "web_search", "text": "cloudflare outage"}),
    (1.6, "tool_result", {"name": "web_search"}),
    (0.5, "thinking", {"text": "Three sources agree on the timeline"}),
    (0.9, "tool_call", {"name": "read_page", "text": "status.cloudflare.com"}),
    (1.4, "tool_result", {"name": "read_page"}),
    (0.6, "thinking", {"text": "Enough to answer"}),
    (0.8, "token", {"text": "The outage began "}),
    (0.18, "token", {"text": "at 06:12 UTC "}),
    (0.18, "token", {"text": "and lasted "}),
    (0.18, "token", {"text": "roughly 40 minutes."}),
    (0.7, "response", {"text": "The outage began at 06:12 UTC and lasted roughly 40 minutes."}),
    (2.0, "idle", {}),
]


def demo(url=DEFAULT_URL):
    viz = Viz(agent="demo", url=url, timeout=1.0)
    if not viz.send("idle"):
        print("no relay at %s — start it with: python3 relay.py" % url, file=sys.stderr)
        return 1
    print("driving the visualizer at %s" % url)
    for delay, type, fields in DEMO:
        time.sleep(delay)
        viz.send(type, **fields)
        label = fields.get("name") or fields.get("text") or ""
        print("  %-12s %s" % (type, label))
    print("done")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    url = args[1] if len(args) > 1 else DEFAULT_URL
    if args and args[0] == "demo":
        sys.exit(demo(url))
    if args and args[0] == "watch":
        ws = args[1] if len(args) > 1 else None
        sys.exit(watch(ws, color=sys.stdout.isatty() and "--no-color" not in args))
    print(__doc__.strip())
    print("\nusage: python3 agentviz.py demo  [relay-url]     drive the field")
    print("       python3 agentviz.py watch [ws-url]        follow it in the terminal")
