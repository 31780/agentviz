#!/usr/bin/env python3
"""Bridge Claude Code hook events onto the agentviz event protocol.

Claude Code hands each hook a JSON object on stdin. This maps that onto one
visualizer event and posts it to the relay:

    SessionStart     -> idle
    UserPromptSubmit -> thinking     (the prompt)
    PreToolUse       -> tool_call    (tool name + a short argument summary)
    PostToolUse      -> tool_result
    SubagentStop     -> tool_result
    Notification     -> thinking     (the notification text)
    Stop             -> response
    SessionEnd       -> idle

Claude Code has no per-token hook, so `token` events are not emitted — the
field breathes on thinking and blooms on the final response instead.

Install: see README, "Wire it into Claude Code".

Two rules this script must never break:
  1. Never write to stdout. Claude Code feeds hook stdout back into the model's
     context on some events; anything printed there would leak into the prompt.
  2. Never fail. It always exits 0, even with no relay running, so a dead
     visualizer can never wedge a coding session.
"""

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("AGENTVIZ_URL", "http://127.0.0.1:8766/event")
TIMEOUT = float(os.environ.get("AGENTVIZ_TIMEOUT", "0.25"))
DEBUG = os.environ.get("AGENTVIZ_DEBUG") == "1"

MAP = {
    "SessionStart": "idle",
    "UserPromptSubmit": "thinking",
    "PreToolUse": "tool_call",
    "PostToolUse": "tool_result",
    "SubagentStop": "tool_result",
    "Notification": "thinking",
    "Stop": "response",
    "SessionEnd": "idle",
}

# Which field of tool_input actually says what the tool is doing.
TOOL_ARG = {
    "Bash": "command",
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern",
    "Grep": "pattern",
    "WebFetch": "url",
    "WebSearch": "query",
    "Task": "description",
    "Agent": "description",
    "Skill": "skill",
}


def clip(text, n=160):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def summarize(tool_name, tool_input):
    if not isinstance(tool_input, dict):
        return None
    key = TOOL_ARG.get(tool_name)
    if key and tool_input.get(key):
        return clip(tool_input[key])
    for key in ("description", "prompt", "query", "command", "file_path", "url"):
        if tool_input.get(key):
            return clip(tool_input[key])
    return None


def build(hook):
    name = hook.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "")
    type = MAP.get(name)
    if not type:
        return None

    event = {"type": type}
    # Label the field with the repo this session is working in.
    cwd = hook.get("cwd") or os.getcwd()
    if cwd:
        event["agent"] = os.path.basename(cwd.rstrip("/")) or "claude"

    if name == "UserPromptSubmit":
        event["text"] = clip(hook.get("prompt", ""), 240)
    elif name == "Notification":
        event["text"] = clip(hook.get("message", ""), 240)
    elif name in ("PreToolUse", "PostToolUse"):
        tool = hook.get("tool_name") or "tool"
        event["name"] = tool
        if name == "PreToolUse":
            text = summarize(tool, hook.get("tool_input"))
            if text:
                event["text"] = text
    elif name == "SubagentStop":
        event["name"] = "subagent"

    return event


def main():
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    try:
        hook = json.loads(raw) if raw.strip() else {}
    except ValueError:
        hook = {}
    if not isinstance(hook, dict):
        hook = {}

    event = build(hook)
    if event is None:
        return

    body = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT):
            pass
    except (urllib.error.URLError, OSError, ValueError) as exc:
        if DEBUG:
            sys.stderr.write("agentviz: %s\n" % exc)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                       # never wedge a session
        if DEBUG:
            sys.stderr.write("agentviz: %s\n" % exc)
    sys.exit(0)
