"""Resource-root resolution that works in dev and in a PyInstaller build.

Bundled read-only resources (sprites, the persona/memory seeds, the opencode
plugin, the STT model) sit at a fixed layout under a base dir:
  - dev:    the repo root (parent of the ``companion`` package)
  - frozen: PyInstaller's extraction dir (``sys._MEIPASS``; for onedir that's
            ``<app>/_internal``)
"""

from __future__ import annotations

import sys
from pathlib import Path


def res_root() -> Path:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base)
        return Path(sys.executable).resolve().parent   # fallback
    return Path(__file__).resolve().parent.parent       # repo root
