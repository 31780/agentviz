#!/usr/bin/env python3
"""Bridge Codex lifecycle hooks onto the agentviz event protocol.

Codex sends one hook event as JSON on stdin. This process translates it to a
single best-effort POST to the local relay. A missing relay must never delay or
break a Codex turn.

Install the repository-local integration from ``.codex/hooks.json`` or copy
the example from the README into ``~/.codex/hooks.json`` for every project.
"""

import json
import os
import sys
import urllib.error
import urllib.request


URL = os.environ.get("AGENTVIZ_URL", "http://127.0.0.1:8766/event")
TIMEOUT = float(os.environ.get("AGENTVIZ_TIMEOUT", "0.25"))
DEBUG = os.environ.get("AGENTVIZ_DEBUG") == "1"

EVENT_TYPES = {
    "SessionStart": "idle",
    "UserPromptSubmit": "thinking",
    "PreToolUse": "tool_call",
    "PostToolUse": "tool_result",
    "SubagentStart": "tool_call",
    "SubagentStop": "tool_result",
    "Stop": "response",
    "Interrupt": "idle",
    "SessionEnd": "idle",
}

TOOL_ARGUMENT_KEYS = (
    "cmd",
    "command",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "description",
    "prompt",
)


def clip(value, limit=200):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_tool(tool_input):
    if not isinstance(tool_input, dict):
        return None
    for key in TOOL_ARGUMENT_KEYS:
        if tool_input.get(key):
            return clip(tool_input[key], 160)
    return None


def build(hook):
    """Return one agentviz event for a Codex hook payload."""
    hook_name = hook.get("hook_event_name", "")
    event_type = EVENT_TYPES.get(hook_name)
    if not event_type:
        return None

    event = {"type": event_type}
    cwd = hook.get("cwd") or os.getcwd()
    event["agent"] = os.path.basename(cwd.rstrip(os.sep)) or "codex"

    if hook_name == "UserPromptSubmit":
        text = clip(hook.get("prompt"), 240)
        if text:
            event["text"] = text
    elif hook_name == "PreToolUse":
        event["name"] = hook.get("tool_name") or "tool"
        text = summarize_tool(hook.get("tool_input"))
        if text:
            event["text"] = text
    elif hook_name == "PostToolUse":
        event["name"] = hook.get("tool_name") or "tool"
    elif hook_name in ("SubagentStart", "SubagentStop"):
        event["name"] = hook.get("agent_type") or "subagent"
    elif hook_name == "Stop":
        text = clip(hook.get("last_assistant_message"), 240)
        if text:
            event["text"] = text

    return event


def send(event):
    if not event or os.environ.get("AGENTVIZ_DISABLE") == "1":
        return
    body = json.dumps(event).encode("utf-8")
    request = urllib.request.Request(
        URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT):
            pass
    except (urllib.error.URLError, OSError, ValueError) as exc:
        if DEBUG:
            sys.stderr.write("agentviz: %s\n" % exc)


def main():
    try:
        hook = json.load(sys.stdin)
        if not isinstance(hook, dict):
            hook = {}
    except (OSError, ValueError):
        hook = {}

    send(build(hook))

    # Codex requires JSON output from these hook types when they exit 0. An
    # empty object explicitly says that this observer is not controlling the
    # turn or the subagent.
    if hook.get("hook_event_name") in ("Stop", "SubagentStop"):
        sys.stdout.write("{}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # An observer must never wedge the agent loop.
        if DEBUG:
            sys.stderr.write("agentviz: %s\n" % exc)
    sys.exit(0)
