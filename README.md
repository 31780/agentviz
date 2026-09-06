# agentviz

A single-file neural-field visualizer for any AI agent. A few thousand luminous nodes joined by fine filaments in black space, with blue and violet pulses travelling between them. Thinking raises the firing rate and spreads it outward; a tool call sends a violet pulse out to a distant cluster and back; streaming tokens push bright pulses from the core; the final answer sweeps a wave through the whole field. Slow camera drift, depth of field, no text.

```
index.html     the visualizer (raw WebGL, no build step, no dependencies)
index-2d.html  the earlier small canvas version with captions and a log
relay.py       tiny relay: agents push events in, browsers subscribe
agentviz.py    zero-dep Python emitter for your agents
```

## Run it

```bash
pip install websockets
python relay.py           # serves the page + relays events
open http://localhost:8766
```

The page has no visible controls. Press **/** (or double-tap) to show the connection field and the Demo button, **d** to toggle the demo. URL params: `?demo` autoplays, `?hud` shows controls, `?n=8000` sets node count (default 4800 desktop, 2600 mobile).

Smoke test the full path from another terminal:

```bash
python agentviz.py demo
```

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

If the agent runs on another box, run the relay there and open the page with `?ws=ws://that-host:8765`, or type the address into the field at the bottom of the page.

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
