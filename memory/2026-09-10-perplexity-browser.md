# Investigation: Perplexity in Brave

## Symptom

The user wants AgentViz to launch when using Perplexity in a Brave browser tab.

## Root cause

AgentViz currently starts from Codex/Claude lifecycle hooks and a zsh terminal
preexec hook. A Brave tab navigating to perplexity.ai does not invoke any of
those hooks, and launchd does not receive browser-tab navigation events.

## Evidence

- `hooks/launch.sh` is called by AI session hooks, not by Brave.
- `contrib/agentviz.zsh` only watches terminal AI commands.
- The relay accepts events from clients, but no browser extension or tab monitor
  exists in this repository.

## Status

DONE_WITH_CONCERNS: the current setup will not auto-launch from Perplexity.
Opening AgentViz manually or leaving it open works, but Perplexity events will
not animate the field. Automatic launch would require a Brave extension or a
macOS tab monitor; event capture would additionally require a page integration.
