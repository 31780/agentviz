#!/bin/bash
# Ask the per-user launchd job to open agentviz. Fall back to the direct
# launcher when the job has not been installed yet.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOB="gui/$(id -u)/com.agentviz.open"

[ "$AGENTVIZ_DISABLE" = "1" ] && exit 0

if launchctl print "$JOB" >/dev/null 2>&1; then
  launchctl kickstart "$JOB" >/dev/null 2>&1 && exit 0
fi

python3 "$HERE/launch.py" >/dev/null 2>&1 || true

exit 0
