"""The companion's persona — the slime agent that shapes opencode's replies.

The persona lives as an opencode agent definition at ``agents/slime.md`` in this
repo (requirement: "a skill which contains the persona of the companion").

To make ``opencode run --agent slime`` work regardless of which project
directory a session lives in, we copy that file into opencode's *global* agent
directory once, on startup. This is additive (a single new file) and idempotent.

The source template uses ``{color}`` which is replaced with the active colour
profile's description (e.g. "fire-red" for lava, "mint-green" for mint).

Memory files (agents/memory/*.md) are synced to the same global directory at
startup, so the agent can read them like supplementary skill files.
"""

from __future__ import annotations

import os
from pathlib import Path

from ._paths import res_root

AGENT_NAME = "slime"

# Source persona (bundled resource; repo in dev, _MEIPASS when frozen).
SRC = res_root() / "agents" / f"{AGENT_NAME}.md"

PROFILE_COLORS = {
    "matcha":   "green",
    "berry":    "pink",
    "ocean":    "blue",
    "sunset":   "orange",
    "midnight": "deep-purple",
    "coral":    "coral-red",
    "mint":     "mint-green",
    "lavender": "soft-purple",
    "peach":    "golden",
    "rose":     "magenta",
    "storm":    "slate-gray",
    "lava":     "fire-red",
}

DEFAULT_PROFILE = "matcha"


def _global_agent_dir() -> Path:
    """opencode's global config lives at ~/.config/opencode (also on Windows)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "opencode" / "agent"


def ensure_installed(profile: str = DEFAULT_PROFILE) -> str | None:
    """Install/refresh the slime agent globally, rendering ``{color}``.

    Returns AGENT_NAME or None if the source file is missing or unwritable.
    """
    if not SRC.exists():
        return None
    try:
        color = PROFILE_COLORS.get(profile, PROFILE_COLORS[DEFAULT_PROFILE])
        src_text = SRC.read_text(encoding="utf-8")
        rendered = src_text.replace("{color}", color)

        dest_dir = _global_agent_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{AGENT_NAME}.md"

        # re-install if missing or if profile changed (rendered text differs)
        if not dest.exists() or dest.read_text(encoding="utf-8") != rendered:
            dest.write_text(rendered, encoding="utf-8")
        return AGENT_NAME
    except OSError:
        return None


def ensure_memory_installed() -> bool:
    """Sync agents/memory/*.md into ~/.config/opencode/agent/slime/.

    Called once on startup. Returns True if at least one file was synced.
    Delegates to companion.memory to avoid circular imports.
    """
    from . import memory
    return memory.ensure_memory_installed()
