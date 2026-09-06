# agentviz

A single-file neural-field visualizer for any AI agent. A few thousand luminous nodes joined by fine filaments in black space, with blue and violet pulses travelling between them. Thinking raises the firing rate and spreads it outward; a tool call sends a violet pulse out to a distant cluster and back; streaming tokens push bright pulses from the core; the final answer sweeps a wave through the whole field. Slow camera drift, depth of field, no text.

```
index.html            the visualizer (raw WebGL, no build step, no dependencies)
index-2d.html         the earlier small canvas version with captions and a log
relay.py              tiny relay: agents push events in, browsers subscribe
agentviz.py           zero-dep Python emitter for your agents
hooks/claude_code.sh  bridge that drives the field from Claude Code (fast)
hooks/claude_code.py  the same bridge in portable Python
hooks/codex.py        bridge that drives the field from Codex lifecycle hooks
.codex/hooks.json     ready-to-use Codex hooks for this repository
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

### Watching without a browser

`watch` follows the same feed in the terminal — every event, colour-coded, no
canvas and no GPU:

```bash
python3 agentviz.py watch
```

```
15:01:00 tool_call    neuralLink     Bash python3 agentviz.py watch
15:01:00 tool_result  neuralLink     Bash
15:01:01 response     neuralLink     same feed, ~0 graphics cost
```

It costs ~23 MB against a browser's hundreds — which matters if you leave the
visualiser up all day. One tab showing `index-2d.html`, each browser given a
fresh profile, summed RSS across every process it spawned (shared pages are
counted more than once, so read these as a ranking, not as absolutes):

| browser | | processes |
|---|---|---|
| Brave | 851 MB | 6 |
| Chrome | 1242 MB | 9 |
| Firefox | 1822 MB | 13 |
| `agentviz.py watch` | **23 MB** | 1 |

The gap between any browser and the terminal is two orders of magnitude, so if
the goal is to keep it running permanently, the terminal view is the answer and
the choice of browser is a detail. Among browsers, fewer processes wins.

The terminal view is also the right one when
you want to read what an agent is doing rather than watch it. A headless
browser is *not* a cheaper way to run the visualiser: it is still a full
browser, and nothing renders to a screen you can see, so you pay the cost and
get no picture. Use headless only to screenshot or record the page.

## Wire it into Codex

This repository is already wired through `.codex/hooks.json`. Start the relay,
open the page, then start a **new Codex task** in this repository. Codex loads
lifecycle hooks when a task starts; a task that was already open when the hook
file was added will not pick it up. Codex will ask you to review the project
hook the first time; open `/hooks` and trust it.

```bash
python3 relay.py
open http://localhost:8766
```

`UserPromptSubmit` sends `thinking` as soon as you submit a prompt, so the
field animates for the whole active turn. `Stop` sends `response`; an interrupt
or session end returns it to `idle`. Tool and subagent hooks add their own
outbound and return pulses. The hook commands run in the background and the
bridge treats the relay as optional, so this does not hold up Codex when the
visualizer is closed.

To use agentviz for every Codex project, copy the `hooks` object from
`.codex/hooks.json` into `~/.codex/hooks.json` and replace each command with an
absolute path to this checkout:

```json
"command": "python3 /ABSOLUTE/PATH/TO/agentviz/hooks/codex.py"
```

Codex hooks expose turn, tool, and completion boundaries, but not private
reasoning tokens. The animation therefore represents the actual lifetime of
the turn; it does not attempt to display hidden chain-of-thought.

## Wire it into Claude Code

`hooks/claude_code.sh` turns a Claude Code session into a light show. Start the
relay, open the page, then add this to `~/.claude/settings.json` (global, so it
fires in every repo) or to a single project's `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "/ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.sh" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "/ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.sh" }] }],
    "PreToolUse":       [{ "matcher": "*", "hooks": [{ "type": "command", "command": "/ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.sh" }] }],
    "PostToolUse":      [{ "matcher": "*", "hooks": [{ "type": "command", "command": "/ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.sh" }] }],
    "Notification":     [{ "hooks": [{ "type": "command", "command": "/ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.sh" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "/ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.sh" }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "/ABSOLUTE/PATH/TO/agentviz/hooks/claude_code.sh" }] }]
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

### Cost

Claude Code fires two hooks per tool call, so the bridge runs constantly and its
startup cost is the whole story. Measured on an M-series Mac:

| bridge | per hook | per tool call | transient memory |
|---|---|---|---|
| `claude_code.sh` | 20 ms | 39 ms | 2.8 MB |
| `claude_code.py` | 106 ms | 212 ms | 16.8 MB |

The shell version does the same mapping with one `jq` pass and bash's built-in
`/dev/tcp`, skipping Python's ~107 ms interpreter startup — which is not
fixable by interpreter choice (Homebrew 3.12 and the Xcode python are within
2 ms, and `-S -E` is worse). It falls back to the Python bridge automatically
when `jq` is absent, so use `claude_code.sh` unless you need pure portability.

Neither bridge leaves anything resident: the cost is process startup, paid per
event and returned immediately.

The relay itself is ~19 MB resident and idles at zero CPU. The expensive part
of the whole system is the browser tab — `index.html` holds several thousand
WebGL nodes, so on a machine under memory pressure prefer `--page 2d`, or cap
the 3D field with `?n=1500`.

Two properties make this safe to leave installed everywhere. Neither bridge
writes to stdout, since Claude Code feeds hook stdout back into the model's
context on some events. And both always exit 0 without stalling, so a relay
that is down or gone can never wedge a coding session: the Python bridge
bounds itself with a 250 ms request timeout, and the shell bridge relies on
the TCP connect to a local relay failing immediately when nothing is
listening. Point the shell bridge at a *remote* relay and that guarantee
weakens to the kernel's connect timeout — use the Python bridge across a
network. Set
`AGENTVIZ_DISABLE=1` to mute either bridge. The Python one takes `AGENTVIZ_URL`
and `AGENTVIZ_DEBUG=1`; the shell one takes `AGENTVIZ_HOST` and `AGENTVIZ_PORT`.

## Any other agent

`run` wraps a command in a pty and narrates it. The agent needs to know nothing
about agentviz — its input and output pass through untouched, and the events
are inferred from what goes past:

```bash
python3 agentviz.py run -- codex "fix the failing test"
python3 agentviz.py run -- aider
python3 agentviz.py run --agent scraper -- ./my-agent.sh
```

Start and exit become `thinking` and `response` (or `error`, with the exit
code). Output becomes `token` pulses, rate-limited so a chatty agent cannot
flood the field. Lines that look like an agent narrating a tool call become
`tool_call`:

```
Running: npm test          ->  tool_call npm
Reading src/index.js       ->  tool_call reading
$ git status               ->  tool_call git
● Bash(npm test)           ->  tool_call Bash
```

Those patterns are guesses about how agents describe themselves, not a
contract. An agent that changes its output format will quietly stop producing
`tool_call` events and keep producing everything else, which is why nothing
depends on them. The wrapper is transparent otherwise: output is byte-identical
to running the command directly, and the exit code is passed through.

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

### Running it all the time

On macOS, a launch agent keeps the relay up across logins and restarts it if it
dies. `contrib/com.agentviz.relay.plist` is a template — edit the paths, then:

```bash
cp contrib/com.agentviz.relay.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.agentviz.relay.plist
launchctl print gui/$UID/com.agentviz.relay | grep state
```

To stop it, `launchctl bootout gui/$UID/com.agentviz.relay`. To restart after
changing the relay, `launchctl kickstart -k gui/$UID/com.agentviz.relay`.

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
