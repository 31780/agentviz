#!/bin/bash
# Low-cost variant of claude_code.py — same mapping, ~6x cheaper to start.
#
# Python costs ~107ms of interpreter startup per invocation, and Claude Code
# fires two hooks per tool call, so the .py bridge adds ~200ms to every tool
# use. This does the same work with one jq pass and bash's built-in /dev/tcp,
# for ~16ms total. Falls back to the Python version when jq is absent.
#
# Same two rules as the Python bridge: never write to stdout (Claude Code
# feeds hook stdout back into the model's context), and always exit 0.

export LC_ALL=C           # so ${#body} counts bytes, not characters
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL_HOST="${AGENTVIZ_HOST:-127.0.0.1}"
URL_PORT="${AGENTVIZ_PORT:-8766}"

[ "$AGENTVIZ_DISABLE" = "1" ] && exit 0

if ! command -v jq >/dev/null 2>&1; then
  exec python3 "$HERE/claude_code.py"       # no jq: use the portable bridge
fi

# -a keeps the output pure ASCII, so the byte count below is exact.
body=$(jq -ac '
  def clip($n): tostring | gsub("\\s+"; " ")
                | if length > $n then .[0:$n-1] + "..." else . end;
  . as $h
  | ($h.hook_event_name // "") as $e
  | { SessionStart: "idle", SessionEnd: "idle",
      UserPromptSubmit: "thinking", Notification: "thinking",
      PreToolUse: "tool_call", PostToolUse: "tool_result",
      SubagentStop: "tool_result", Stop: "response" }[$e] as $t
  | if $t == null then empty else
      { type: $t, agent: (($h.cwd // "") | split("/") | map(select(. != "")) | last // "claude") }
      + (if $e == "UserPromptSubmit" then { text: ($h.prompt // "" | clip(240)) } else {} end)
      + (if $e == "Notification"     then { text: ($h.message // "" | clip(240)) } else {} end)
      + (if $e == "PreToolUse" or $e == "PostToolUse"
         then { name: ($h.tool_name // "tool") } else {} end)
      + (if $e == "SubagentStop" then { name: "subagent" } else {} end)
      + (if $e == "PreToolUse"
         then (($h.tool_input // {})
               | (.command // .file_path // .pattern // .url // .query
                  // .description // .notebook_path // .skill // null)) as $a
              | (if $a == null then {} else { text: ($a | clip(160)) } end)
         else {} end)
    end
' 2>/dev/null) || exit 0

[ -z "$body" ] && exit 0

# bash speaks TCP directly; no curl process needed.
# The redirection failure is reported by the shell itself, so the whole
# compound has to be silenced -- 2>/dev/null on the exec alone leaks
# "Connection refused" to stderr whenever the relay is not running.
{ exec 3<>"/dev/tcp/$URL_HOST/$URL_PORT"; } 2>/dev/null || exit 0
printf 'POST /event HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s' \
  "$URL_HOST" "${#body}" "$body" >&3 2>/dev/null
exec 3<&- 2>/dev/null
exec 3>&- 2>/dev/null
exit 0
