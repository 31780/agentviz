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
    print(__doc__.strip())
    print("\nusage: python3 agentviz.py demo [relay-url]")
