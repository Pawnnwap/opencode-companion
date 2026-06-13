"""Wrapper for the opencode CLI.

Two entry points the companion needs:
  - ``run_final_text`` runs a prompt and returns only the assistant's final
    text (tool calls + thinking stripped).
  - ``list_sessions_json`` lists sessions as structured data.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

# Stop a console window from popping up when a windowed (no-console) build spawns
# opencode on Windows. CREATE_NO_WINDOW hides the process we launch; a STARTUPINFO
# with SW_HIDE is inherited by opencode's own children (git, MCP servers, …) so
# their consoles stay hidden too. No effect on other platforms.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _startupinfo():
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


_STARTUPINFO = _startupinfo()

# Opencode's built-in/internal agents — excluded from the agent list.
_INTERNAL_AGENTS = {"summary", "title", "general", "explore", "compaction"}

# Where agent skills (SKILL.md) are installed (the `npx skills` ecosystem).
_SKILL_DIRS = [Path.home() / ".agents" / "skills", Path.home() / ".claude" / "skills"]


class OcResult(NamedTuple):
    code: int
    text: str
    session_id: Optional[str] = None


_TEXT_TYPES = {"text"}
_TOOL_TYPES = {"tool", "tool_use", "tool-call", "tool-result"}
_STEP_START = {"step_start", "step-start"}
_STEP_FINISH = {"step_finish", "step-finish"}
_THINK_TYPES = {"reasoning", "thinking"} | _STEP_START | _STEP_FINISH


def _oneline(text: str, n: int = 60) -> str:
    """Collapse whitespace and truncate — for one-line activity subtitles."""
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _tool_activity(part: dict) -> str:
    """A live activity hint for a tool part: ``"<tool>\\t<detail>"``.

    Detail is what the tool acts on — the command, search pattern/query, URL, or
    file name — so the UI can show *what* it's doing, not just *that* it's busy.
    """
    tool = part.get("tool") or part.get("name") or part.get("type") or "tool"
    inp = (part.get("state") or {}).get("input") or {}
    detail = ""
    if isinstance(inp, dict):
        if inp.get("command"):
            detail = str(inp["command"])
        elif inp.get("pattern"):
            detail = str(inp["pattern"])
        elif inp.get("query"):
            detail = str(inp["query"])
        elif inp.get("url"):
            detail = str(inp["url"])
        else:
            for k in ("path", "filePath", "file", "filename"):
                if inp.get(k):
                    detail = Path(str(inp[k])).name or str(inp[k])
                    break
    detail = _oneline(detail, 48)
    return f"{tool}\t{detail}" if detail else str(tool)


def _part_text(part: dict) -> str:
    """Displayable text for a single part, or "" if it carries none.

    Reasoning / thinking / step bookkeeping is always skipped. For every other
    part type (text, tool, patch, anything new) we pull whatever readable string
    it has — so a reply is never blank when *some* non-thinking output exists.
    """
    ptype = part.get("type", "")
    if ptype in _THINK_TYPES:
        return ""
    # direct text (text parts)
    val = part.get("text")
    if isinstance(val, str) and val.strip():
        return val.strip()
    # tool parts carry their result under state
    state = part.get("state") or {}
    for key in ("output", "title"):
        v = state.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # any other part type: take the first readable string field we recognise
    for key in ("output", "content", "summary", "message"):
        v = part.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# Reasoning marker: shown only as the last resort when a turn produced nothing
# but thinking — so it's clearly the model's thoughts, not its answer.
THINK_MARK = "💭 "


def _think_text(part: dict) -> str:
    """Reasoning/thinking text for a part, or "" (step bookkeeping has none)."""
    if part.get("type") in ("reasoning", "thinking"):
        v = part.get("text")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


_OC_EXE: Optional[str] = None


def _real_exe(path: str) -> str:
    """If ``path`` is a Windows npm shim (.cmd/.bat), return the real .exe it calls.

    Spawning the .cmd means cmd.exe re-launches the real opencode.exe WITHOUT our
    CREATE_NO_WINDOW flag, so the console app pops its own window in a packaged
    (no-console) build. Running the .exe directly lets the flag take effect.
    """
    p = Path(path)
    if p.suffix.lower() not in (".cmd", ".bat"):
        return path
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path
    m = re.search(r'"?([^"\r\n]*?\.exe)"?\s*%\*', text) or re.search(r'([^\s"]+\.exe)', text)
    if not m:
        return path
    target = (m.group(1)
              .replace("%~dp0", str(p.parent) + "\\")
              .replace("%dp0%", str(p.parent))
              .strip().strip('"'))
    real = Path(target)
    if not real.is_absolute():
        real = p.parent / target
    return str(real) if real.exists() else path


def _oc_exe() -> str:
    """Resolve the opencode executable to a directly-spawnable path.

    On Windows ``shutil.which`` returns ``opencode.CMD`` (a shim); we resolve the
    real ``opencode.exe`` it wraps so CREATE_NO_WINDOW actually suppresses the
    console window in a packaged build.
    """
    global _OC_EXE
    if _OC_EXE is None:
        _OC_EXE = _real_exe(shutil.which("opencode") or "opencode")
    return _OC_EXE


def _build_cmd(
    message: str,
    session_id: str | None,
    cwd: str | None,
    title: str | None,
    format: str | None,
    continue_session: bool,
    agent: str | None = None,
    model: str | None = None,
    files: list[str] | None = None,
) -> list[str]:
    cmd = [_oc_exe(), "run", message]
    # --pure causes hangs with --format json, so skip it for JSON
    if format != "json":
        cmd.append("--pure")
    if session_id:
        cmd.extend(["--session", session_id])
    elif continue_session:
        cmd.append("--continue")
    if cwd:
        cmd.extend(["--dir", cwd])
    if title:
        cmd.extend(["--title", title])
    if agent:
        cmd.extend(["--agent", agent])
    if model:
        cmd.extend(["--model", model])
    for f in files or []:
        cmd.extend(["--file", f])
    if format:
        cmd.extend(["--format", format])
    return cmd


def run_final_text(
    message: str,
    *,
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    title: Optional[str] = None,
    files: Optional[list[str]] = None,
    env: Optional[dict] = None,
    timeout: int = 600,
    on_activity: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> OcResult:
    """Run opencode and return ONLY the assistant's final text.

    Tool calls, reasoning/thinking and step bookkeeping are dropped from the
    returned text. ``on_activity`` (if given) receives short status hints such as
    ``"think"`` or a tool name so the UI can animate — these never appear in the
    returned text.

    If the run emits no assistant text at all (e.g. the model stops right after a
    tool call), the reply falls back to the last non-thinking section seen — the
    most recent tool's output/title — so the bubble is never blank.

    Returns ``OcResult(code, text, session_id)``. On error, text holds the message.
    """
    cmd = _build_cmd(
        message, session_id, cwd, title, format="json",
        continue_session=False, agent=agent, model=model, files=files,
    )
    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            env=env, creationflags=_NO_WINDOW, startupinfo=_STARTUPINFO,
        )
        chunks: list[str] = []
        last_section = ""   # newest non-thinking section, used if no text arrives
        last_think = ""     # newest reasoning text, used only if nothing else exists
        new_session_id: Optional[str] = None
        for line in proc.stdout:  # type: ignore[union-attr]
            if stop_event and stop_event.is_set():
                proc.kill()
                proc.wait()
                break
            line = line.strip()
            if not line or line[0] != "{":
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            new_session_id = new_session_id or event.get("sessionID")
            etype = event.get("type", "")
            part = event.get("part", {}) or {}
            ptype = part.get("type", "")

            # Every event line drives a live subtitle (on_activity) so the UI
            # confirms progress; text/sections are also collected for the reply.
            if etype in _TEXT_TYPES or ptype in _TEXT_TYPES:
                txt = part.get("text", "")
                if txt:
                    chunks.append(txt)
                    last_section = txt
                # the answer itself is not a subtitle
            elif etype in _THINK_TYPES or ptype in _THINK_TYPES:
                tk = _think_text(part)
                if tk:
                    last_think = tk
                if on_activity:
                    if etype in _STEP_START or ptype in _STEP_START:
                        on_activity("working")
                    elif etype in _STEP_FINISH or ptype in _STEP_FINISH:
                        pass  # end-of-step marker, nothing to show
                    elif tk:
                        on_activity(_oneline(tk))   # live thought as a subtitle
                    else:
                        on_activity("think")
            else:
                # tool calls and every other part type become a subtitle too,
                # enriched with what the tool is acting on (command / path / query)
                if on_activity:
                    on_activity(_tool_activity(part))
                sect = _part_text(part)
                if sect:
                    last_section = sect

        if not (stop_event and stop_event.is_set()):
            proc.wait(timeout=timeout)

        # Prefer the assistant's text; if none arrived, fall back to the last
        # non-thinking section (e.g. a tool's output); as a last resort show the
        # reasoning (marked) so the reply is never blank.
        final = "".join(chunks).strip() or last_section.strip()
        if not final and last_think.strip():
            final = THINK_MARK + last_think.strip()
        rc = proc.returncode if proc.returncode is not None else 0
        if not final and rc != 0:
            return OcResult(rc, "opencode finished without a reply.", new_session_id)
        return OcResult(rc, final or "(no reply)", new_session_id)

    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
        return OcResult(1, "Error: opencode timed out", None)
    except FileNotFoundError:
        return OcResult(1, "Error: opencode not found in PATH", None)
    except Exception as e:  # noqa: BLE001
        return OcResult(1, f"Error: {e}", None)


def export_session(session_id: str, timeout: int = 30) -> list[dict[str, str]]:
    """Return a session's transcript as ``[{"role", "text"}]`` (user/assistant text).

    Reads ``opencode export <id>`` (JSON on stdout). Reasoning, tool calls and
    step bookkeeping are dropped; roles are normalised to the companion's own
    ``"user"`` / ``"slime"``. Returns an empty list on any error.
    """
    cmd = [_oc_exe(), "export", session_id]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW, startupinfo=_STARTUPINFO,
        )
        if result.returncode != 0 or not (result.stdout or "").strip():
            return []
        data = json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError):
        return []

    out: list[dict[str, str]] = []
    for msg in data.get("messages", []) if isinstance(data, dict) else []:
        info = msg.get("info", {}) or {}
        role = info.get("role")
        if role not in ("user", "assistant"):
            continue
        parts = msg.get("parts") or []
        texts = [
            p.get("text", "")
            for p in parts
            if p.get("type") == "text" and (p.get("text") or "").strip()
        ]
        text = "\n".join(texts).strip()
        if not text:
            # no text part: fall back to the last non-thinking block (tool output…)
            for p in reversed(parts):
                sect = _part_text(p)
                if sect:
                    text = sect
                    break
        if not text:
            # nothing but thinking: show the reasoning (marked) as a last resort
            for p in reversed(parts):
                tk = _think_text(p)
                if tk:
                    text = THINK_MARK + tk
                    break
        if not text:
            continue
        out.append({"role": "user" if role == "user" else "slime", "text": text})
    return out


def list_agents(timeout: int = 15) -> list[str]:
    """Return user-facing primary agent names from ``opencode agent list``.

    Skips subagents, memory sub-agents (``slime/*``) and opencode internals
    (summary/title/general/explore). Returns an empty list on any error.
    """
    cmd = [_oc_exe(), "agent", "list"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW, startupinfo=_STARTUPINFO,
        )
        if result.returncode != 0:
            return []
        out = result.stdout or ""
    except (FileNotFoundError, subprocess.SubprocessError):
        return []

    agents: list[str] = []
    for line in out.splitlines():
        # header lines look like:  "slime (primary)"  (JSON detail lines are indented)
        m = re.match(r"^(\S+)\s+\((primary|subagent|all)\)\s*$", line)
        if not m:
            continue
        name, kind = m.group(1), m.group(2)
        if kind != "primary" or "/" in name or name in _INTERNAL_AGENTS:
            continue
        if name not in agents:
            agents.append(name)
    return agents


def _parse_skill(path: Path, fallback: str) -> tuple[str, str]:
    """Pull (name, short description) from a SKILL.md frontmatter block."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback, ""
    fm = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        fm = text[3:end] if end != -1 else text[3:]
    name = fallback
    m = re.search(r"^name:\s*(.+)$", fm, re.M)
    if m:
        name = m.group(1).strip().strip("\"'")
    desc = ""
    m = re.search(r"^description:\s*(.*)$", fm, re.M)
    if m:
        inline = m.group(1).strip()
        if inline and inline not in (">", "|", ">-", "|-"):
            desc = inline.strip("\"'")
        else:  # folded/literal block: gather the indented lines that follow
            buf = []
            for ln in fm[m.end():].splitlines():
                if ln and not ln[0].isspace():
                    break          # next top-level key
                if ln.strip():
                    buf.append(ln.strip())
            desc = " ".join(buf)
    return name, _oneline(desc, 60)


def list_skills() -> list[tuple[str, str]]:
    """Discover installed agent skills as (name, description), deduped by name."""
    seen: dict[str, str] = {}
    for base in _SKILL_DIRS:
        try:
            if not base.is_dir():
                continue
            for d in sorted(base.iterdir()):
                sf = d / "SKILL.md"
                if not d.is_dir() or not sf.exists():
                    continue
                name, desc = _parse_skill(sf, d.name)
                if name and name not in seen:
                    seen[name] = desc
        except OSError:
            continue
    return list(seen.items())


def list_sessions_json(cwd: Optional[str] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Return opencode sessions as a list of dicts (newest first).

    Each dict has: id, title, updated (epoch ms), created, directory.
    Returns an empty list on any error.
    """
    cmd = [_oc_exe(), "session", "list", "--format", "json"]
    if limit:
        cmd.extend(["-n", str(limit)])
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW, startupinfo=_STARTUPINFO,
        )
        if result.returncode != 0 or not (result.stdout or "").strip():
            return []
        data = json.loads(result.stdout)
        if not isinstance(data, list):
            return []
        data.sort(key=lambda s: s.get("updated", 0), reverse=True)
        return data
    except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError):
        return []
