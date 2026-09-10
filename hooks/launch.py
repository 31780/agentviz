#!/usr/bin/env python3
"""Open agentviz for an AI session without ever blocking the agent."""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    from agentviz import launch

    launch()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if os.environ.get("AGENTVIZ_DEBUG") == "1":
            sys.stderr.write("agentviz launch: %s\n" % exc)
    sys.exit(0)
