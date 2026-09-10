#!/usr/bin/env python3
"""Open AgentViz once when the Comet browser starts.

This is intentionally a process monitor, not a browser-content monitor. It
does not inspect tabs, URLs, prompts, or page contents.
"""

import os
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "hooks" / "launch.sh"
STATE = pathlib.Path(
    os.environ.get(
        "AGENTVIZ_COMET_STATE",
        os.path.expanduser("~/Library/Application Support/AgentViz/comet.pid"),
    )
)


def comet_pid():
    """Return Comet's primary PID, an empty string if stopped, or None on error."""
    try:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-x", "Comet"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode == 1:
        return ""
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()[0].strip()


def _read_state():
    try:
        return STATE.read_text().strip()
    except OSError:
        return ""


def _write_state(value):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".comet.", dir=str(STATE.parent))
        try:
            with os.fdopen(fd, "w") as file:
                file.write(value)
            os.replace(temporary, STATE)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return True
    except OSError:
        return False


def main():
    current = comet_pid()
    if current is None:
        return 0
    previous = _read_state()
    if current and current != previous:
        subprocess.run(
            ["/bin/bash", str(LAUNCHER)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    _write_state(current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
