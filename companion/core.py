"""The companion's brain: routes user input to opencode sessions.

It understands a small shorthand so you can drive opencode sessions from the
slime's chat bubble:

    ls                      list opencode sessions (numbered)
    2                       make session #2 the active one (plain talk goes there)
    1: run the tests        send "run the tests" to session #1
    1,3: fix the lint       send to sessions #1 and #3
    1-3: format everything  send to sessions #1, #2 and #3
    all: git status         send to every listed session
    new: build a todo app   start a brand-new session with that first message
    <anything else>         goes to the active session (or starts one)

Replies contain only opencode's final text — tool calls and thinking are
stripped upstream in opencode.run_final_text.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import opencode as oc
from ._paths import res_root
from . import persona
from . import memory

LIST_TRIGGERS = {
    "ls", "list", "sessions", "session list", "/ls", "/sessions",
    "会话", "列表", "任务", "任务列表", "任务集合", "清单",
}

_TARGET_CMD = re.compile(r"^\s*([0-9][0-9\s,\-]*|\*|all|new)\s*[:：]\s*(.+)$", re.I | re.S)
_BARE_INDEX = re.compile(r"^\s*(\d{1,3})\s*$")
_NOTE_CMD = re.compile(r"^\s*(note|备注|remember|记住)\s*[:：]?\s*(.+)$", re.I | re.S)

CONFIG_DIR = Path.home() / ".opencode-companion"
HISTORY_PATH = CONFIG_DIR / "history.json"

# Default chat runs in a sandbox so casual talk can't touch real files. Resolve to
# an absolute path: a relative --dir would be resolved against opencode's own cwd.
# When frozen (PyInstaller), the project root is a read-only temp extraction, so
# use a writable per-user dir instead.
if getattr(sys, "frozen", False):
    DEFAULT_CHAT_DIR = CONFIG_DIR / "chat"
else:
    DEFAULT_CHAT_DIR = res_root() / "temp"

# Memory consolidation prompt — MUST be a single line: opencode is launched via
# opencode.CMD (Windows shim) and embedded newlines in the argument break parsing.
_CONSOLIDATE_PROMPT = (
    "Combine these memory notes into durable facts and a few short insights. "
    'Reply with ONLY a JSON object like {{"facts":["fact"],"reflection":["insight"]}} '
    "and nothing else. Keep durable points only (identity, preferences, decisions, "
    "gotchas), merge duplicates, drop chit-chat, <=25 facts, <=8 insights, each short. "
    "Known facts: {facts}. Recent notes (newest first): {recent}"
)


def _short(text: str, n: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Core:
    """Stateful controller shared by the desktop UI (and any CLI)."""

    def __init__(self, model: Optional[str] = None, list_limit: int = 12, profile: str = "matcha",
                 chat_dir: Optional[str] = None):
        self.model = model
        self.list_limit = list_limit
        self.profile = profile
        self.agent = persona.ensure_installed(profile=profile)  # "slime" or None
        self.plan_mode = False   # when True, run opencode's read-only "plan" agent
        self.consolidation_model = None   # model for memory consolidation (None = opencode default)
        self._last_consolidate = 0.0      # monotonic time of last consolidation (throttle)
        persona.ensure_memory_installed()                        # sync memory files to opencode dir
        # Sandbox dir for the default chat (absolute, created if missing).
        self.chat_cwd = str(Path(chat_dir).resolve() if chat_dir else DEFAULT_CHAT_DIR)
        try:
            Path(self.chat_cwd).mkdir(parents=True, exist_ok=True)
        except OSError:
            self.chat_cwd = None  # fall back to opencode's default cwd if uncreatable
        self._sessions: list[dict[str, Any]] = []  # last listed, index 0 == #1
        self._active: Optional[dict[str, str]] = None  # {"id","title"}
        self._active_is_chat: bool = True  # True => active session is the sandboxed chat
        self.running: set[str] = set()  # session ids with a run currently in flight
        self.history: list[dict[str, Any]] = []
        self._pending_user: Optional[str] = None  # for auto-digest pairing
        self._load_history()

    # ── history ───────────────────────────────────────────────────

    def _load_history(self):
        try:
            if HISTORY_PATH.exists():
                self.history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.history = []

    def _save_history(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            # keep the tail; bubbles don't need the whole life story
            HISTORY_PATH.write_text(
                json.dumps(self.history[-200:], ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:
            pass

    def log(self, role: str, text: str):
        self.history.append({"role": role, "text": text, "ts": time.time()})
        self._save_history()
        # auto-digest: when a slime/error reply follows a user message
        if role in ("slime", "error") and self._pending_user is not None:
            memory.append_recent(self._pending_user, text)
            self._pending_user = None
        elif role == "user":
            self._pending_user = text

    # ── status helpers ────────────────────────────────────────────

    def active_label(self) -> str:
        if self._active:
            return f"#{self._active['title']}"
        return "new session"

    # ── session view / direct run (used by the desktop session panel) ──

    def set_active(self, session: dict[str, Any]) -> None:
        """Make ``session`` the active target for plain talk (a real session, not chat)."""
        self._active = {"id": session["id"],
                        "title": _short(session.get("title") or session["id"], 30)}
        self._active_is_chat = False  # opened a real session: use its own dir, not the sandbox
        memory.set_active_task(session["id"])
        memory.write_sessions(self._sessions, active_id=self._active["id"])

    def session_transcript(self, session_id: str) -> list[dict[str, str]]:
        """Fetch a session's messages as ``[{role, text}]`` for the bubble view."""
        return oc.export_session(session_id)

    def list_agents(self) -> list[str]:
        """User-facing opencode agents (picking one switches the agent)."""
        return oc.list_agents()

    def list_skills(self) -> list[tuple[str, str]]:
        """Installed agent skills as (name, description) for the slash dropdown."""
        return oc.list_skills()

    def set_agent(self, name: str) -> None:
        """Switch the agent used for subsequent prompts."""
        self.agent = name or self.agent

    def set_plan_mode(self, on: bool) -> None:
        """Plan mode runs opencode's read-only `plan` agent (makes no changes)."""
        self.plan_mode = bool(on)

    def _effective_agent(self) -> Optional[str]:
        return "plan" if self.plan_mode else self.agent

    def run_on_session(self, session_id, message, on_activity=None, stop_event=None, files=None) -> str:
        """Run a prompt against a specific session via the CLI; track running state."""
        reply = self._reply(self._run(
            message, session_id=session_id, files=files,
            on_activity=on_activity, stop_event=stop_event,
        ))
        memory.write_task(session_id, self._session_title(session_id), reply)
        return reply

    def _session_title(self, sid: str) -> str:
        """Best-known title (task goal) for a session id."""
        if self._active and self._active.get("id") == sid:
            return self._active["title"]
        for s in self._sessions:
            if s.get("id") == sid:
                return _short(s.get("title") or sid, 40)
        return "task"

    # ── memory consolidation (short-term → long-term, via opencode) ──

    def consolidate_memory(self) -> bool:
        """Distil recent exchanges into durable facts/reflection using opencode.

        Throttled; only runs with enough new material. opencode does the
        reasoning (free model, read-only `plan` agent, bridge disabled so it
        never prompts); this method writes the resulting files. Non-destructive
        on any failure.
        """
        now = time.monotonic()
        if now - self._last_consolidate < 600:        # at most once / 10 min
            return False
        entries = memory.read_recent_entries()
        if len(entries) < 8:                           # not enough to consolidate
            return False
        self._last_consolidate = now

        # single-line prompt (opencode.CMD breaks on newlines in the argument)
        facts = "; ".join(memory.facts_list()) or "(none)"
        recent = " · ".join(e.lstrip("- ").strip() for e in entries)
        prompt = _CONSOLIDATE_PROMPT.format(facts=facts, recent=recent)
        # run with the bridge disabled (no permission bubbles for a background task)
        env = {k: v for k, v in os.environ.items() if k != "COMPANION_PERMS_URL"}
        res = oc.run_final_text(
            prompt, model=self.consolidation_model, agent=self.agent,
            cwd=self.chat_cwd, env=env, timeout=180,
        )
        if res.code != 0:
            return False
        parsed = self._parse_consolidation(res.text)
        if parsed is None:
            return False
        facts, reflection = parsed
        if facts:
            memory.write_facts(facts)
        if reflection:
            memory.write_reflection(reflection)
        memory.trim_recent(5)                          # keep a little working context
        return True

    @staticmethod
    def _parse_consolidation(text: str):
        """Extract {facts:[...], reflection:[...]} from the model's reply."""
        m = re.search(r"\{.*\}", text or "", re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except (ValueError, json.JSONDecodeError):
            return None
        facts = data.get("facts")
        refl = data.get("reflection") or data.get("reflections") or []
        if not isinstance(facts, list) or not isinstance(refl, list):
            return None
        return [str(x) for x in facts if str(x).strip()], [str(x) for x in refl if str(x).strip()]

    # ── sessions ──────────────────────────────────────────────────

    def refresh_sessions(self) -> list[dict[str, Any]]:
        self._sessions = oc.list_sessions_json(limit=self.list_limit)
        active_id = self._active["id"] if self._active else None
        memory.write_sessions(self._sessions, active_id=active_id)
        return self._sessions

    def list_reply(self) -> str:
        sessions = self.refresh_sessions()
        if not sessions:
            return "No opencode sessions yet. Say `new: <task>` to start one. *wobble*"
        lines = ["opencode sessions:"]
        for i, s in enumerate(sessions, 1):
            mark = ""
            if self._active and self._active["id"] == s.get("id"):
                mark = "  ←active"
            lines.append(f"  {i}. {_short(s.get('title') or '(untitled)', 40)}{mark}")
        lines.append("Reply `2`, `1,3: <cmd>`, or `all: <cmd>`.")
        return "\n".join(lines)

    def _index_to_session(self, idx: int) -> Optional[dict[str, Any]]:
        if 1 <= idx <= len(self._sessions):
            return self._sessions[idx - 1]
        return None

    @staticmethod
    def _parse_targets(spec: str, n: int) -> list[int]:
        spec = spec.strip().lower()
        if spec in ("*", "all"):
            return list(range(1, n + 1))
        out: list[int] = []
        for part in spec.replace(" ", ",").split(","):
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                if a.isdigit() and b.isdigit():
                    out.extend(range(int(a), int(b) + 1))
            elif part.isdigit():
                out.append(int(part))
        seen: list[int] = []
        for i in out:
            if 1 <= i <= n and i not in seen:
                seen.append(i)
        return seen

    # ── main entry ────────────────────────────────────────────────

    def handle(
        self,
        text: str,
        on_activity: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        self.log("user", text)
        reply = self.respond(text, on_activity, stop_event)
        self.log("slime", reply)
        return reply

    def respond(self, text, on_activity=None, stop_event=None, files=None) -> str:
        """Route input to opencode and return the reply text (no history logging)."""
        text = (text or "").strip()
        if not text:
            return ""
        low = text.lower()

        # 1. show the session list
        if low in LIST_TRIGGERS:
            return self.list_reply()

        # 2. save a note to memory  "note: <text>"  "记住 <text>"
        m = _NOTE_CMD.match(text)
        if m:
            note_text = m.group(2).strip()
            if note_text:
                memory.append_fact(note_text)
                return f"Noted. *wobble*"
            return "What should I remember? Say `note: <thing>` or `记住 <thing>`."

        # 3. targeted command:  "1,3: do thing" / "new: do thing" / "all: do thing"
        m = _TARGET_CMD.match(text)
        if m:
            spec, command = m.group(1).strip(), m.group(2).strip()
            if spec.lower() == "new":
                reply = self._send_new(command, on_activity, stop_event)  # real work, own dir
                self._active_is_chat = False
                return reply
            if not self._sessions:
                self.refresh_sessions()
            idxs = self._parse_targets(spec, len(self._sessions))
            if not idxs:
                return f"No session matches `{spec}`. Say `ls` to see the list."
            return self._dispatch(idxs, command, on_activity, stop_event)

        # 4. bare number -> select active session
        m = _BARE_INDEX.match(text)
        if m:
            if not self._sessions:
                self.refresh_sessions()
            s = self._index_to_session(int(m.group(1)))
            if not s:
                return f"No session #{m.group(1)}. Say `ls` to see the list."
            self._active = {"id": s["id"], "title": _short(s.get("title") or s["id"], 30)}
            self._active_is_chat = False  # a real session selected by number
            memory.set_active_task(s["id"])
            memory.write_sessions(self._sessions, active_id=self._active["id"])
            return f"On session #{m.group(1)}: {self._active['title']}. Talk to me. *wobble*"

        # 5. plain talk -> active session, or start a new one (sandboxed chat)
        if self._active:
            cwd = self.chat_cwd if self._active_is_chat else None
            return self._send_to(self._active["id"], text, on_activity, stop_event,
                                 cwd=cwd, files=files)
        reply = self._send_new(text, on_activity, stop_event, cwd=self.chat_cwd, files=files)
        self._active_is_chat = True
        return reply

    # ── opencode calls ────────────────────────────────────────────

    def _run(self, message, *, session_id=None, cwd=None, title=None, files=None,
             on_activity=None, stop_event=None):
        """Call opencode with this companion's agent/model, tracking running state."""
        if session_id:
            self.running.add(session_id)
        try:
            return oc.run_final_text(
                message, session_id=session_id, cwd=cwd, title=title, files=files,
                agent=self._effective_agent(), model=self.model,
                on_activity=on_activity, stop_event=stop_event,
            )
        finally:
            if session_id:
                self.running.discard(session_id)

    @staticmethod
    def _reply(res) -> str:
        """Format an OcResult as a chat reply (error replies get a slime preface)."""
        return res.text if res.code == 0 else f"Hmm, that wobbled wrong:\n{res.text}"

    def _send_to(self, session_id, message, on_activity, stop_event, cwd=None, files=None) -> str:
        reply = self._reply(self._run(
            message, session_id=session_id, cwd=cwd, files=files,
            on_activity=on_activity, stop_event=stop_event,
        ))
        memory.write_task(session_id, self._session_title(session_id), reply)
        return reply

    def _send_new(self, message, on_activity, stop_event, cwd=None, files=None) -> str:
        res = self._run(
            message, cwd=cwd, title=_short(message, 50), files=files,
            on_activity=on_activity, stop_event=stop_event,
        )
        reply = self._reply(res)
        if res.session_id:
            self._active = {"id": res.session_id, "title": _short(message, 30)}
            self.refresh_sessions()  # include the new session, then write memory
            memory.set_active_task(res.session_id)
            memory.write_task(res.session_id, _short(message, 60), reply)
        return reply

    def _dispatch(self, idxs, command, on_activity, stop_event) -> str:
        parts: list[str] = []
        for i in idxs:
            if stop_event and stop_event.is_set():
                parts.append("(stopped)")
                break
            s = self._index_to_session(i)
            if not s:
                continue
            label = _short(s.get("title") or s["id"], 30)
            if on_activity:
                on_activity(f"#{i}")
            res = self._run(
                command, session_id=s["id"],
                on_activity=on_activity, stop_event=stop_event,
            )
            mark = "✓" if res.code == 0 else "✗"
            parts.append(f"#{i} {label} {mark}\n{res.text}")
        return "\n\n".join(parts) if parts else "Nothing to do."
