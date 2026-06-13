"""Permission bridge for the desktop companion.

A tiny localhost HTTP server that the opencode permission plugin
(``opencode_plugin/permission_bridge.js``) calls before a mutating tool runs.
The companion shows an Allow/Deny bubble and answers here, so the agent pauses
for consent instead of silently bypassing — and resumes once answered.

Also installs the plugin into opencode's auto-load dir so it is active.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

from ._paths import res_root

# Source plugin shipped with the companion (bundled resource when frozen).
PLUGIN_SRC = res_root() / "companion" / "opencode_plugin" / "permission_bridge.js"


def _opencode_plugins_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "opencode" / "plugins"


def ensure_plugin_installed() -> bool:
    """Copy the bridge plugin into opencode's global auto-load dir (idempotent)."""
    try:
        if not PLUGIN_SRC.exists():
            return False
        dst_dir = _opencode_plugins_dir()
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / "companion_permission_bridge.js"
        src_text = PLUGIN_SRC.read_text(encoding="utf-8")
        if not dst.exists() or dst.read_text(encoding="utf-8") != src_text:
            dst.write_text(src_text, encoding="utf-8")
        return True
    except OSError:
        return False


class PermRequest:
    """One pending permission ask, resolved by the UI thread."""

    def __init__(self, tool: str, args):
        self.tool = tool
        self.args = args
        self.result = "deny"          # fail-closed default
        self._event = threading.Event()

    def resolve(self, decision: str):
        self.result = "allow" if decision == "allow" else "deny"
        self._event.set()

    def wait(self, timeout: float) -> str:
        self._event.wait(timeout)
        return self.result


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):       # silence default stderr logging
        pass

    def do_POST(self):  # noqa: N802
        if self.path != "/ask":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("content-length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            data = {}
        decision = self.server.permits.ask(data.get("tool", ""), data.get("args"))
        payload = json.dumps({"decision": decision}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class PermissionServer:
    """127.0.0.1-only server the plugin calls; bridges asks to the UI thread."""

    def __init__(self, notify: Callable[[PermRequest], None], wait_timeout: float = 300.0):
        self._notify = notify             # marshals a PermRequest onto the UI thread
        self._wait_timeout = wait_timeout
        self.allow: set[str] = set()      # tools the user chose "always" this session
        self.block_all = False            # plan mode: auto-deny every mutating tool
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.permits = self        # type: ignore[attr-defined]
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self._thread.start()

    def stop(self):
        try:
            self._httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass

    # Called on a server thread; blocks until the UI resolves the request.
    def ask(self, tool: str, args) -> str:
        if self.block_all:
            return "deny"                 # plan mode: no mutating tool runs, no prompt
        if tool and tool in self.allow:
            return "allow"
        req = PermRequest(tool, args)
        self._notify(req)
        return req.wait(self._wait_timeout)
