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
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = os.environ.get("AGENTVIZ_URL", "http://127.0.0.1:8766/event")
DEFAULT_PAGE_URL = os.environ.get("AGENTVIZ_PAGE_URL", "http://127.0.0.1:8766")


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


# ---------------------------------------------------------------- launch

def _health_url(page_url):
    """Return the relay health endpoint for a visualizer page URL."""
    parts = urllib.parse.urlsplit(page_url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/healthz", "", ""))


def _relay_is_ready(page_url, timeout=0.2):
    try:
        with urllib.request.urlopen(_health_url(page_url), timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _claim_launch(cooldown, stamp_path=None):
    """Lock this launch window; return an fd, -1 without locking, or False if recent."""
    stamp_path = stamp_path or os.path.join(
        tempfile.gettempdir(), "agentviz-launch-%s.stamp" % getattr(os, "getuid", lambda: 0)()
    )
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(stamp_path, flags, 0o600)
    except OSError:
        # A read-only temp directory should not stop the visualizer opening.
        return -1
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except ImportError:
            pass
        now = time.time()
        stamp = os.fstat(fd)
        if stamp.st_size > 0 and now - stamp.st_mtime < cooldown:
            os.close(fd)
            return False
        return fd
    except Exception:
        os.close(fd)
        raise


def _finish_launch(claim, succeeded):
    """Record a successful open and release the inter-process launch lock."""
    if claim == -1:
        return
    try:
        if succeeded:
            now = time.time()
            os.ftruncate(claim, 0)
            os.write(claim, str(now).encode("ascii"))
    finally:
        os.close(claim)


def _start_relay(page="2d", page_url=DEFAULT_PAGE_URL):
    parts = urllib.parse.urlsplit(page_url)
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    try:
        port = parts.port or 80
    except ValueError:
        return None

    is_default_endpoint = parts.hostname == "127.0.0.1" and port == 8766
    if sys.platform == "darwin" and is_default_endpoint:
        job = "gui/%s/com.agentviz.relay" % getattr(os, "getuid", lambda: 0)()
        installed = subprocess.run(
            ["/bin/launchctl", "print", job],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if installed.returncode == 0:
            restarted = subprocess.run(
                ["/bin/launchctl", "kickstart", "-k", job],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if restarted.returncode == 0:
                return restarted
    command = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "relay.py"),
        "--host", parts.hostname,
        "--port", str(port),
        "--page", page,
    ]
    return subprocess.Popen(
        command,
        cwd=os.path.dirname(__file__),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _open_page(page_url):
    if sys.platform == "darwin":
        browser = os.environ.get("AGENTVIZ_BROWSER", "Brave Browser")
        subprocess.Popen(
            ["/usr/bin/open", "-a", browser, page_url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    import webbrowser
    webbrowser.open(page_url, new=2)


def launch(page_url=DEFAULT_PAGE_URL, cooldown=None):
    """Ensure the relay is alive and open its page once per AI session start."""
    if os.environ.get("AGENTVIZ_DISABLE") == "1":
        return False
    if cooldown is None:
        try:
            cooldown = float(os.environ.get("AGENTVIZ_LAUNCH_COOLDOWN", "8"))
        except ValueError:
            cooldown = 8.0
    claim = _claim_launch(max(0.0, cooldown))
    if claim is False:
        return False

    succeeded = False
    try:
        if not _relay_is_ready(page_url):
            _start_relay(os.environ.get("AGENTVIZ_PAGE", "2d"), page_url)
            for _ in range(20):
                if _relay_is_ready(page_url):
                    break
                time.sleep(0.05)
            else:
                return False
        _open_page(page_url)
        succeeded = True
        return True
    finally:
        _finish_launch(claim, succeeded)


# ------------------------------------------------------------------- run

# Wrap any terminal agent. The agent needs to know nothing about agentviz:
# it runs inside a pty, its input and output pass through untouched, and the
# events are inferred from what appears on the way past.

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\r")

# Ordered: the first pattern that matches a line wins. These are guesses about
# how agents narrate themselves, not a contract -- an agent that changes its
# output format will quietly stop producing tool_call events, which is why
# nothing else depends on them.
_TOOL_PATTERNS = [
    (re.compile(r"^\s*[\u25cf\u23fa\u2022]\s*(\w[\w.-]*)\("), 1),   # Claude Code: bullet Tool(args)
    (re.compile(r"^\s*(?:Running|Executing|Invoking|Calling)[: ]+(.+)$"), 1),
    (re.compile(r"^\s*(?:Tool|Action|Function)(?: call)?[: ]+([\w.-]+)"), 1),
    (re.compile(r"^\s*[$>\u276f]\s+(\S.*)$"), 1),                       # a shell command echoed
    (re.compile(r"^\s*(?:Reading|Writing|Editing|Creating|Patching)\s+(\S+)"), 0),
    (re.compile(r"^\s*(?:Searching|Grepping|Fetching|Downloading)\s+(.+)$"), 0),
]

_VERB = re.compile(r"^\s*(\w+)")


def _clean(text):
    return " ".join(_ANSI.sub(" ", text).split())


def _detect_tool(line):
    """Return (name, argument) if this line looks like a tool call."""
    for pattern, group in _TOOL_PATTERNS:
        m = pattern.match(line)
        if not m:
            continue
        if group == 1:
            arg = m.group(1).strip()
            name = arg.split()[0] if arg else "tool"
            return name[:32], arg[:160]
        verb = _VERB.match(line)
        return (verb.group(1).lower() if verb else "tool")[:32], m.group(1)[:160]
    return None


def run(argv, agent=None, url=DEFAULT_URL, detect_tools=True):
    """Run a command inside a pty, narrating it to the visualiser."""
    import pty
    import shutil

    # pty.spawn forks and execs in the child. A failed exec raises there, and
    # the child would then carry on running this program, so the command is
    # resolved before any fork happens.
    exe = shutil.which(argv[0])
    if not exe:
        print("agentviz: command not found: %s" % argv[0], file=sys.stderr)
        Viz(agent=agent or "agentviz", url=url, timeout=0.2).error(
            "command not found: %s" % argv[0])
        return 127
    argv = [exe] + list(argv[1:])

    viz = Viz(agent=agent or os.path.basename(argv[0]), url=url, timeout=0.2)
    viz.thinking("$ " + " ".join(argv)[:200])

    state = {"buf": b"", "last_token": 0.0, "open_tool": None, "quiet": time.time()}
    TOKEN_EVERY = 0.15          # never more than ~7 token events a second

    def observe(chunk):
        now = time.time()
        state["quiet"] = now
        state["buf"] += chunk
        # Only whole lines are inspected; a partial last line waits for more.
        if b"\n" in state["buf"]:
            *lines, state["buf"] = state["buf"].split(b"\n")
            if len(state["buf"]) > 8192:            # a line that never ends
                state["buf"] = state["buf"][-4096:]
            for raw in lines:
                line = _clean(raw.decode("utf-8", "replace"))
                if not line:
                    continue
                hit = _detect_tool(line) if detect_tools else None
                if hit:
                    if state["open_tool"]:
                        viz.tool_done(state["open_tool"])
                    viz.tool(hit[0], hit[1])
                    state["open_tool"] = hit[0]
                elif now - state["last_token"] > TOKEN_EVERY:
                    state["last_token"] = now
                    viz.token(line[:120])
        elif now - state["last_token"] > TOKEN_EVERY:
            # Output with no newline yet -- a spinner, or a token stream.
            text = _clean(state["buf"][-120:].decode("utf-8", "replace"))
            if text:
                state["last_token"] = now
                viz.token(text)

    def master_read(fd):
        data = os.read(fd, 4096)
        if data:
            try:
                observe(data)
            except Exception:
                pass                 # never let narration break the agent
        return data

    try:
        status = pty.spawn(argv, master_read)
    except Exception as exc:
        viz.error(str(exc)[:200])
        raise

    if state["open_tool"]:
        viz.tool_done(state["open_tool"])
    code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status
    if code == 0:
        viz.response("%s finished" % os.path.basename(argv[0]))
    else:
        viz.error("%s exited %s" % (os.path.basename(argv[0]), code))
    time.sleep(0.05)
    viz.idle()
    return code if isinstance(code, int) else 0


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
    if args and args[0] == "launch":
        page_url = args[1] if len(args) > 1 else DEFAULT_PAGE_URL
        sys.exit(0 if launch(page_url) else 0)
    if args and args[0] == "run":
        rest, agent = args[1:], None
        while rest:
            if rest[0] == "--":
                rest = rest[1:]
                break
            if rest[0] == "--agent" and len(rest) > 1:
                agent, rest = rest[1], rest[2:]
                continue
            if rest[0].startswith("--agent="):
                agent, rest = rest[0].split("=", 1)[1], rest[1:]
                continue
            break
        if not rest:
            print("usage: python3 agentviz.py run [--agent NAME] -- <command...>",
                  file=sys.stderr)
            sys.exit(2)
        sys.exit(run(rest, agent=agent))
    if args and args[0] == "watch":
        ws = args[1] if len(args) > 1 else None
        sys.exit(watch(ws, color=sys.stdout.isatty() and "--no-color" not in args))
    print(__doc__.strip())
    print("\nusage: python3 agentviz.py demo  [relay-url]     drive the field")
    print("       python3 agentviz.py launch [page-url]     start and open the field")
    print("       python3 agentviz.py watch [ws-url]        follow it in the terminal")
    print("       python3 agentviz.py run -- <command>      narrate any agent")
