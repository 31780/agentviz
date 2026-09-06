#!/usr/bin/env python3
"""Tiny relay: agents push events in, browsers subscribe.

Zero dependencies. Serves the visualizer over HTTP and fans events out to
every connected browser over WebSocket.

    python3 relay.py            # http://localhost:8766, ws://localhost:8765
    python3 relay.py --port 9000 --ws-port 9001

Agents push events either way:

    POST http://localhost:8766/event   with a JSON body
    ws://localhost:8765                one JSON object per message
"""

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455

_clients = set()          # browser sockets subscribed to the feed
_clients_lock = threading.Lock()


# ---------------------------------------------------------------- websocket

def _frame(payload: bytes) -> bytes:
    """Encode one unmasked text frame (server -> client)."""
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x81, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x81, 126, n)
    else:
        head = struct.pack("!BBQ", 0x81, 127, n)
    return head + payload


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return buf


def _read_frame(sock: socket.socket):
    """Read one frame. Returns (opcode, payload) or None on close."""
    b0, b1 = struct.unpack("!BB", _recv_exactly(sock, 2))
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", _recv_exactly(sock, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", _recv_exactly(sock, 8))[0]
    if n > 1 << 20:                       # 1 MB is far more than any event
        raise ConnectionError("frame too large")
    key = _recv_exactly(sock, 4) if masked else b""
    data = _recv_exactly(sock, n) if n else b""
    if masked:
        data = bytes(c ^ key[i % 4] for i, c in enumerate(data))
    if opcode == 0x8:
        return None
    return opcode, data


def broadcast(event: dict) -> int:
    """Send one event to every connected browser. Returns the delivery count."""
    payload = _frame(json.dumps(event).encode("utf-8"))
    with _clients_lock:
        targets = list(_clients)
    sent = 0
    for sock in targets:
        try:
            sock.sendall(payload)
            sent += 1
        except OSError:
            _drop(sock)
    return sent


def _drop(sock: socket.socket) -> None:
    with _clients_lock:
        _clients.discard(sock)
    try:
        sock.close()
    except OSError:
        pass


def _handshake(sock: socket.socket) -> bool:
    """Complete the HTTP upgrade. Returns True if this is a live websocket."""
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = sock.recv(4096)
        if not chunk:
            return False
        request += chunk
        if len(request) > 65536:
            return False
    headers = {}
    for line in request.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    key = headers.get("sec-websocket-key")
    if not key:
        sock.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
        return False
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    sock.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
    )
    return True


def _serve_ws_client(sock: socket.socket) -> None:
    try:
        if not _handshake(sock):
            sock.close()
            return
        with _clients_lock:
            _clients.add(sock)
        # A peer may also *push* events in (an agent on a websocket).
        while True:
            frame = _read_frame(sock)
            if frame is None:
                break
            opcode, data = frame
            if opcode == 0x9:                       # ping -> pong
                sock.sendall(struct.pack("!BB", 0x8A, len(data)) + data)
                continue
            if opcode != 0x1 or not data:
                continue
            try:
                event = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(event, dict) and event.get("type"):
                broadcast(event)
    except (OSError, ConnectionError, struct.error):
        pass
    finally:
        _drop(sock)


def ws_server(host: str, port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(64)
    while True:
        conn, _ = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=_serve_ws_client, args=(conn,), daemon=True).start()


# --------------------------------------------------------------------- http

PAGES = {"index.html", "index-2d.html"}
DEFAULT_PAGE = "index.html"      # overridden by --page


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agentviz-relay"

    def log_message(self, fmt, *args):            # quiet by default
        if self.server.verbose:
            sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            with _clients_lock:
                n = len(_clients)
            return self._send(200, json.dumps({"ok": True, "clients": n}).encode(),
                              "application/json")
        name = self.server.default_page if path == "/" else path.lstrip("/")
        if name not in PAGES:
            return self._send(404, b"not found")
        try:
            with open(os.path.join(HERE, name), "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send(404, b"not found")
        self._send(200, body, "text/html; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/event":
            return self._send(404, b"not found")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 1 << 20:
            return self._send(400, b"bad length")
        try:
            event = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, b"bad json")
        if not isinstance(event, dict) or not event.get("type"):
            return self._send(400, b"missing type")
        sent = broadcast(event)
        if self.server.verbose:
            label = event.get("name") or (event.get("text") or "")[:48]
            sys.stderr.write("  %-12s %-28s -> %d\n" % (event["type"], label, sent))
        self._send(200, json.dumps({"ok": True, "sent": sent}).encode(), "application/json")


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="agentviz relay")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 to expose)")
    ap.add_argument("--port", type=int, default=8766, help="http port")
    ap.add_argument("--ws-port", type=int, default=8765, help="websocket port")
    ap.add_argument("--page", choices=("3d", "2d"), default="3d",
                    help="which page to serve at / (default: 3d). "
                         "2d is the captioned view with a tool log.")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every event")
    args = ap.parse_args()

    threading.Thread(target=ws_server, args=(args.host, args.ws_port), daemon=True).start()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    httpd.verbose = args.verbose
    httpd.default_page = "index-2d.html" if args.page == "2d" else "index.html"
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print("agentviz relay")
    other = "index.html" if args.page == "2d" else "index-2d.html"
    print("  page    http://%s:%d          (%s)" % (shown, args.port, httpd.default_page))
    print("  other   http://%s:%d/%s" % (shown, args.port, other))
    print("  events  POST http://%s:%d/event" % (shown, args.port))
    print("  socket  ws://%s:%d" % (shown, args.ws_port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
