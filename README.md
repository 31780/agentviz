# agentviz

A single-file neural-field visualizer for any AI agent. A few thousand luminous nodes joined by fine filaments in black space, with blue and violet pulses travelling between them. Thinking raises the firing rate and spreads it outward; a tool call sends a violet pulse out to a distant cluster and back; streaming tokens push bright pulses from the core; the final answer sweeps a wave through the whole field. Slow camera drift, depth of field, no text.

```
index.html            the visualizer (raw WebGL, no build step, no dependencies)
index-2d.html         the earlier small canvas version with captions and a log
relay.py              tiny relay: agents push events in, browsers subscribe
agentviz.py           zero-dep Python emitter for your agents
hooks/claude_code.py  bridge that drives the field from Claude Code
```

Python 3.8+ and a browser. No pip install, no build step, no dependencies —
the relay speaks WebSocket straight from the standard library.

## Run it

```bash
python3 relay.py          # serves the page + relays events
open http://localhost:8766
```

`index.html` is the ambient view: pulses and brightness, deliberately no text.
`index-2d.html` is the legible one — the caption names the tool and its
argument (`Bash` / `python3 relay.py -v`), and the **Log** button opens a
scrolling history. Serve that one at `/` instead:

```bash
python3 relay.py --page 2d
```

Either page is always reachable by name, whichever is the default.

The page has no visible controls. Press **/** (or double-tap) to show the connection field and the Demo button, **d** to toggle the demo. URL params: `?demo` autoplays, `?hud` shows controls, `?n=8000` sets node count (default 4800 desktop, 2600 mobile).

Smoke test the full path from another terminal:

```bash
python3 agentviz.py demo
```

## Wire it into Claude Code

`hooks/claude_code.py` turns a Claude Code session into a light show. Start the
relay, open the page, then add this to `~/.claude/settings.json` (global, so it
fires in every repo) or to a single project's `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.py" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.py" }] }],
    "PreToolUse":       [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.py" }] }],
    "PostToolUse":      [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.py" }] }],
    "Notification":     [{ "hooks": [{ "type": "command", "command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.py" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.py" }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.py" }] }]
  }
}
```

What each hook becomes:

| Claude Code hook | event | on screen |
|---|---|---|
| `SessionStart`, `SessionEnd` | `idle` | slow breathing |
| `UserPromptSubmit` | `thinking` | the field fires; caption shows your prompt |
| `PreToolUse` | `tool_call` | amber satellite named for the tool |
| `PostToolUse`, `SubagentStop` | `tool_result` | signal returns, satellite fades |
| `Notification` | `thinking` | caption shows the notification |
| `Stop` | `response` | full bloom |

The `agent` label on every event is the basename of the session's working
directory, so with several repos running at once you can tell which one is
lighting up.

Claude Code has no per-token hook, so `token` events never fire from this
bridge — the field breathes on thinking and blooms on the answer instead.

Two properties make this safe to leave installed everywhere: the bridge never
writes to stdout (Claude Code feeds hook stdout back into the model's context
on some events), and it always exits 0 within a 250 ms timeout, so a relay
that is down or gone can never slow down or wedge a coding session. Set
`AGENTVIZ_DISABLE=1` to mute it, `AGENTVIZ_URL` to point at another relay, or
`AGENTVIZ_DEBUG=1` to see connection errors on stderr.

## Hook up an agent

Python (any agent loop, any framework):

```python
from agentviz import Viz
viz = Viz(agent="hermes")

viz.thinking("Reading the question")
viz.tool("web_search", "cloudflare outage")
viz.tool_done("web_search")
for chunk in stream:
    viz.token(chunk)
viz.response(final_text)
```

Anything else, just POST JSON:

```bash
curl -X POST localhost:8766/event -d '{"type":"thinking","agent":"hermes","text":"hmm"}'
```

Or open a WebSocket to `ws://localhost:8765` and send one JSON object per message.

If the agent runs on another box, run the relay there with
`python3 relay.py --host 0.0.0.0` and open the page with
`?ws=ws://that-host:8765`, or type the address into the field at the bottom of
the page. The relay binds to localhost only by default. `relay.py -v` logs
every event it fans out, and `GET /healthz` reports how many browsers are
attached.

## Event protocol

| type | fields | what it does |
|---|---|---|
| `thinking` | `text?` | network fires with cool blue signals; caption shows the thought |
| `token` | `text` | pulse from core outward; caption streams the text |
| `tool_call` | `name`, `text?` | amber satellite appears with the tool name |
| `tool_result` | `name?` | signal returns to core, satellite fades |
| `response` | `text?` | full bloom; caption shows the answer |
| `error` | `text?` | red flash |
| `idle` | | back to slow breathing |

Every event may carry `agent` (a label for the caption). Unknown types are ignored.

## Embedding

The page also accepts `window.postMessage(event, "*")` when placed in an iframe, and exposes `window.agentviz.handle(event)` if you inline it into your own dashboard. Open it with `?demo` to autoplay the demo.
