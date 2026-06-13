"""Headless text REPL for the slime companion (no GUI).

The real companion is the desktop pet (``companion`` / ``python -m
companion.desktop``). This is a fallback for terminals / debugging and shares the
same brain (companion.core.Core), so the shorthand is identical:

    ls            list opencode sessions
    2             make session #2 active
    1,3: <cmd>    run <cmd> on sessions #1 and #3
    new: <cmd>    start a new session
    mic           record once via the microphone and send (if STT installed)
    quit          exit
"""

from __future__ import annotations

import argparse
import io
import sys

from .core import Core

BANNER = """\
🟢 Goo (opencode slime companion) — text mode
  ls            list sessions        2            select session #2
  1,3: <cmd>    run on sessions      new: <cmd>   start a new session
  mic           speak once           quit         exit
"""


def main():
    parser = argparse.ArgumentParser(description="Slime companion (text mode)")
    parser.add_argument("-m", "--model", default=None, help="opencode model id")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    core = Core(model=args.model)
    print(BANNER)

    while True:
        try:
            raw = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n*wobble* bye!")
            break
        if not raw:
            continue
        if raw.lower() in ("quit", "exit", "q"):
            print("*wobble* bye!")
            break
        if raw.lower() == "mic":
            from . import voice
            if not voice.available():
                print("  [STT not installed: pip install sounddevice sherpa-onnx]")
                continue
            print("  [listening…]")
            raw = voice.listen() or ""
            if not raw:
                print("  [didn't catch that]")
                continue
            print(f"  [heard: {raw}]")

        print("  …")
        reply = core.handle(raw, on_activity=lambda h: None)
        print(f"goo> {reply}\n")


if __name__ == "__main__":
    main()
