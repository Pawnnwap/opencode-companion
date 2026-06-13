"""Companion memory — a tiered system modelled on Project N.E.K.O.

Tiers (markdown files synced to ~/.config/opencode/agent/slime/, read by the
slime agent at the start of each conversation):

    working      the live conversation (core.history) — not a file
    recent.md    近期  short-term: rolling recent exchanges (newest first)
    facts.md     事实  long-term durable facts (manual `note:` + consolidation)
    reflection.md 反思 long-term insights / preferences (consolidation only)
    profile.md   人格  static identity (hand-edited)
    tasks/<id>.md     per-session task: goal + short progress log
    task_current.md   mirror of the active session's task file (fixed path)
    sessions.md       runtime session list (unchanged)

Short-term (recent) is periodically **consolidated** into long-term (facts /
reflection) by opencode itself; the companion only writes the resulting files.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from ._paths import res_root

AGENT_NAME = "slime"

# Bundled memory source/seed (repo in dev, _MEIPASS when frozen).
MEMORY_DIR = res_root() / "agents" / "memory"


def _runtime_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "opencode" / "agent" / AGENT_NAME


MAX_RECENT = 20          # short-term exchanges kept before consolidation trims them
MAX_TASK_PROGRESS = 3    # progress steps kept per session task

_BULLET = re.compile(r"^- ")
_ENTRY = re.compile(r"^- \[")


def _ensure_dirs():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _runtime_dir().mkdir(parents=True, exist_ok=True)
    (_runtime_dir() / "tasks").mkdir(parents=True, exist_ok=True)


# ── recent (短期 / 近期) ───────────────────────────────────────────

_RECENT_HEADER = "# Recent (近期记忆)\n\n*Most recent exchanges, newest first.*\n\n"


def append_recent(user_text: str, reply_text: str):
    """Prepend a one-line summary of a turn to recent.md (rolling, newest first)."""
    _ensure_dirs()
    ts = time.strftime("%m-%d %H:%M")
    entry = f"- [{ts}] **Q:** {_snip(user_text, 70)}  →  **A:** {_snip(reply_text, 90)}"
    entries = read_recent_entries()
    entries.insert(0, entry)
    entries = entries[:MAX_RECENT]
    _write("recent.md", _RECENT_HEADER + "\n".join(entries) + "\n")


def read_recent_entries() -> list[str]:
    return [l for l in _read("recent.md").splitlines() if _ENTRY.match(l)]


def trim_recent(keep: int):
    """Keep only the newest ``keep`` entries (the rest were consolidated)."""
    entries = read_recent_entries()[:max(0, keep)]
    _write("recent.md", _RECENT_HEADER + "\n".join(entries) + "\n")


# ── facts (事实) ──────────────────────────────────────────────────

_FACTS_HEADER = "# Facts (事实记忆)\n\n*Durable facts about the user and project.*\n\n"


def append_fact(text: str):
    """Append a manual durable fact (from the `note:` command)."""
    _ensure_dirs()
    facts = _bullets("facts.md")
    fact = text.strip()
    if fact and fact not in facts:
        facts.append(fact)
    _write("facts.md", _FACTS_HEADER + "\n".join(f"- {f}" for f in facts) + "\n")


def write_facts(items: list[str]):
    """Replace the fact list (consolidation output; already merged/deduped)."""
    items = [i.strip() for i in items if i.strip()]
    _write("facts.md", _FACTS_HEADER + "\n".join(f"- {i}" for i in items) + "\n")


def read_facts_text() -> str:
    return _read("facts.md")


def facts_list() -> list[str]:
    return _bullets("facts.md")


def reflection_list() -> list[str]:
    return _bullets("reflection.md")


# ── reflection (反思) ─────────────────────────────────────────────

_REFLECT_HEADER = "# Reflection (反思记忆)\n\n*Insights, preferences, patterns.*\n\n"


def write_reflection(items: list[str]):
    items = [i.strip() for i in items if i.strip()]
    _write("reflection.md", _REFLECT_HEADER + "\n".join(f"- {i}" for i in items) + "\n")


def read_reflection_text() -> str:
    return _read("reflection.md")


# ── per-session task memory ───────────────────────────────────────

def write_task(session_id: str, summary: str, progress: str):
    """Upsert a session's task memory (goal + rolling last-N progress)."""
    if not session_id:
        return
    _ensure_dirs()
    path = _runtime_dir() / "tasks" / f"{session_id}.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    steps = [l for l in existing.splitlines() if _ENTRY.match(l)]
    ts = time.strftime("%m-%d %H:%M")
    if progress and progress.strip():
        steps.insert(0, f"- [{ts}] {_snip(progress, 110)}")
    steps = steps[:MAX_TASK_PROGRESS]
    text = (
        f"# Task\n\n**Goal:** {_snip(summary, 100) or '(unknown)'}\n\n"
        f"**Progress (latest first):**\n" + ("\n".join(steps) if steps else "- (none)") + "\n"
    )
    try:
        path.write_text(text, encoding="utf-8")
        (_runtime_dir() / "task_current.md").write_text(text, encoding="utf-8")
    except OSError:
        pass


def set_active_task(session_id: str | None):
    """Point task_current.md at the given session's task file (or a placeholder)."""
    _ensure_dirs()
    try:
        src = _runtime_dir() / "tasks" / f"{session_id}.md" if session_id else None
        text = src.read_text(encoding="utf-8") if (src and src.exists()) else \
            "# Task\n\n**Goal:** (none yet)\n\n**Progress (latest first):**\n- (none)\n"
        (_runtime_dir() / "task_current.md").write_text(text, encoding="utf-8")
    except OSError:
        pass


# ── sync ─────────────────────────────────────────────────────────

# Only the hand-edited identity seed comes from the repo; the rest is runtime state.
_SYNCED = ["profile.md"]


def _migrate_legacy():
    """One-time: seed runtime recent.md from the old digest.md (same format)."""
    rec, dig = _runtime_dir() / "recent.md", MEMORY_DIR / "digest.md"
    if not rec.exists() and dig.exists():
        entries = [l for l in dig.read_text(encoding="utf-8").splitlines()
                   if _ENTRY.match(l)][:MAX_RECENT]
        if entries:
            _write("recent.md", _RECENT_HEADER + "\n".join(entries) + "\n")


def ensure_memory_installed() -> bool:
    """Seed the runtime memory dir at startup. Only profile.md comes from the
    version-controlled source; recent/facts/reflection/tasks are live runtime
    state that persists in the runtime dir across restarts (not in the repo)."""
    _ensure_dirs()
    seeded = False
    for name in _SYNCED:                       # just profile.md
        src = MEMORY_DIR / name
        if src.exists():
            try:
                (_runtime_dir() / name).write_text(src.read_text(encoding="utf-8"),
                                                   encoding="utf-8")
                seeded = True
            except OSError:
                pass
    _migrate_legacy()
    set_active_task(None)   # ensure task_current.md exists for the agent to read
    return seeded


# ── sessions.md (runtime-only live list; unchanged) ───────────────

def write_sessions(sessions: list[dict], active_id: str | None = None):
    _ensure_dirs()
    now = time.strftime("%Y-%m-%d %H:%M")
    header = (
        f"# Sessions\n\n*Auto-refreshed: {now}*\n\n"
        f"| # | Title | ID | Last Active | Directory |\n"
        f"|---|-------|----|-------------|-----------|\n"
    )
    rows: list[str] = []
    for i, s in enumerate(sessions):
        sid = s.get("id", "?")[-8:]
        title = s.get("title", "untitled")
        ts = s.get("updated", 0)
        updated = time.strftime("%m-%d %H:%M", time.localtime(ts / 1000)) \
            if isinstance(ts, (int, float)) and ts > 0 else "?"
        directory = Path(s.get("directory", "?")).name if s.get("directory") else "?"
        star = " ★" if (active_id and s.get("id") == active_id) else ""
        rows.append(f"| {i + 1} | {title}{star} | `{sid}` | {updated} | {directory} |")
    _write_runtime("sessions.md", header + "\n".join(rows) + "\n")


# ── helpers ──────────────────────────────────────────────────────

def _bullets(name: str) -> list[str]:
    """Return bullet contents (without the leading '- ') from a memory file."""
    out = []
    for l in _read(name).splitlines():
        if _BULLET.match(l) and not _ENTRY.match(l):   # plain bullets, not timestamped
            out.append(l[2:].strip())
    return out


def _read(name: str) -> str:
    """Read a memory file (runtime first — live memory lives there — then fall
    back to the version-controlled source seed, e.g. profile.md)."""
    rt = _runtime_dir() / name
    if rt.exists():
        return rt.read_text(encoding="utf-8")
    src = MEMORY_DIR / name
    return src.read_text(encoding="utf-8") if src.exists() else ""


def _write(name: str, text: str):
    """Memory is per-user runtime state — written to the runtime dir only, never
    the repo (avoids churn + keeps personal data out of version control)."""
    _write_runtime(name, text)


def _write_runtime(name: str, text: str):
    try:
        (_runtime_dir() / name).write_text(text, encoding="utf-8")
    except OSError:
        pass


def _snip(text: str, max_len: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= max_len else t[: max_len - 1] + "…"
