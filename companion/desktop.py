"""The slime desktop companion.

A frameless, always-on-top, per-pixel-transparent Qt window. A pixel-art slime
sits on the desktop; the chat input and the chat history emerge from it as little
speech bubbles. There is no dashboard — the slime *is* the UI.

    - Click the slime           toggle the text input
    - Type "/"                  dropdown: built-in commands + opencode agents/skills
    - Type + Enter              send to opencode (active session, or a new one)
    - 📷 button                  screenshot the screen, attach it to your next message
    - 🎤 button                  push-to-talk: record, transcribe, send (STT only)
    - Mouse wheel over chat     scroll back through history (a bar appears on hover)
    - Mouse wheel over slime    resize the companion (zoom in / out)
    - Drag the slime            move the pet around your screen
    - Right-drag the slime      resize the companion (drag down = bigger)
    - Drag a file onto slime    paste the file path into the chat input
    - × (top-right)             quit
    - Tray icon                 left-click to show/hide, right-click to quit

Shorthand you can type/say (handled by companion.core):
    ls            list opencode sessions
    2             make session #2 active
    1,3: <cmd>    run <cmd> on sessions #1 and #3
    new: <cmd>    start a new session

Rendered with PySide6 (Qt): true per-pixel alpha (no colour-key hack), a system
tray icon, and clean standalone packaging. The sprites, colours, layout and
animations are identical to before — only the renderer changed.
"""

from __future__ import annotations

import argparse
import math
import os
import queue
import random
import re
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QRegion,
    QStandardItem,
    QStandardItemModel,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QLineEdit,
    QMenu,
    QSystemTrayIcon,
    QWidget,
)

from . import permits, sprites, voice
from .core import Core
from .theme import (
    BASE_H, BASE_W, CAM_BG, CAM_BG_ARMED, CAM_BG_HOVER, CAM_BORDER,
    CAM_BORDER_ARMED, CAM_FG, CAM_PIXELS, DIM, DOT_ACTIVE, DOT_IDLE, DOT_RUNNING,
    ENTRY_FG, ERR_BG, ERR_FG, MIC_BG, MIC_BG_HOVER, MIC_BG_RECORDING,
    MIC_BG_RECORDING_ALT, MIC_BORDER, MIC_BORDER_RECORDING, MIC_FG, MIC_PIXELS,
    MIC_R, PANEL, PANEL_BORDER, PANEL_FILL, PENDING_FG, PROFILES, ROW_ACTIVE,
    ROW_FG, SCALE_DRAG_GAIN, SCALE_MAX, SCALE_MIN, SCALE_WHEEL_STEP, SLIME_BG,
    SLIME_FG, USER_BG, USER_FG, WHITE,
)

# Screenshots are saved here (absolute path passed to opencode via --file).
SHOT_DIR = Path.home() / ".opencode-companion" / "screenshots"

# Heuristic: does a message contain markdown worth rendering? (bold/italic,
# inline + fenced code, bullet/numbered lists, headings, links, blockquotes)
_MD_RE = re.compile(
    r"(\*\*.+?\*\*|__.+?__|`[^`]+`|```|^\s*[-*+] |^\s*\d+\. |^#{1,6} |\[.+?\]\(.+?\)|^> )",
    re.M,
)


def _looks_markdown(text: str) -> bool:
    return bool(text) and bool(_MD_RE.search(text))

# Slash commands offered in the input dropdown (type "/"). Each: (insert, desc).
# Commands ending in a space take an argument; the rest are one-shot actions.
SLASH_COMMANDS = [
    ("/ls", "list opencode sessions"),
    ("/new ", "start a new session with a task"),
    ("/note ", "save a note to memory"),
    ("/all ", "run a command on every session"),
    ("/sessions", "open the session list panel"),
    ("/screenshot", "capture the screen, attach to next message"),
]

# Friendly labels for the live activity hints opencode emits while it works.
# Keys are bare tool names (lower-case). MCP tools arrive namespaced like
# "hashline_read"; _activity_for() strips the "<server>_" prefix before lookup.
# Unknown tools fall back to a readable, de-namespaced form of their raw name.
ACTIVITY_LABELS = {
    "think": "thinking",
    "listening": "listening",
    # file ops
    "read": "reading",
    "edit": "editing",
    "write": "writing",
    "patch": "patching",
    # search / navigation
    "grep": "searching code",
    "glob": "finding files",
    "list": "listing files",
    # web
    "websearch": "searching web",
    "webfetch": "reading page",
    "fetch": "reading page",
    # shell / agents / planning
    "bash": "running command",
    "task": "delegating",
    "todowrite": "planning",
    "todoread": "checking plan",
}


class _Entry(QLineEdit):
    """Chat input: Enter sends, Escape hides."""

    def __init__(self, parent, on_send, on_escape):
        super().__init__(parent)
        self._on_escape = on_escape
        self.returnPressed.connect(on_send)

    def keyPressEvent(self, e):  # noqa: N802 (Qt override)
        if e.key() == Qt.Key_Escape:
            c = self.completer()
            if c is not None and c.popup() is not None and c.popup().isVisible():
                c.popup().hide()   # close the slash menu first
                return
            self._on_escape()
            return
        super().keyPressEvent(e)


class Companion(QWidget):
    def __init__(self, model: str | None = None, profile: str = "matcha"):
        super().__init__()
        self.core = Core(model=model, profile=profile)
        self.ui_queue: queue.Queue = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.busy = False
        self.scroll_px = 0          # pixels scrolled up from the bottom (0 = newest)
        self._pin_top = False       # next render: align newest message's top to viewport top
        self._viewport = QRect()    # chat viewport (for clipping + masking)
        self._text_cache: dict[str, dict] = {}   # text -> layout (size + markdown doc)
        self.state = "idle"
        self._anim_idx = 0
        self._dots = "."
        self._activity_label = ""   # current step shown in the pending bubble
        self._activity_at = 0.0     # monotonic time the current step started (elapsed)
        self._idle_since: float | None = None
        self._profile = profile
        self._cur_frame = "slime_idle_0"
        self._status_text = "starting…"
        self._placed: list[dict] = []   # bubble draw instructions for paintEvent
        self._press: tuple[QPoint, QPoint] | None = None
        self._moved = False
        self._resizing: tuple[int, float] | None = None  # (start global-y, start scale)
        self._mic_hover = False
        self._mic_pulsing = False
        self._mic_pulse_on = False
        self._cam_hover = False
        self._pending_shot: str | None = None   # screenshot staged for the next send
        self._agents: list[str] = []            # opencode agents (pick switches agent)
        self._skills: list[tuple[str, str]] = []  # installed skills (pick passes through)
        self.scale = 1.0
        self._zzz_t = 0.0                 # animation time for "zzz" sleep bubbles
        self._zzz_timer = None            # dedicated refresh timer for zzz animation

        # scrollbar state
        self._sb = {
            "rect": QRect(),        # painted track
            "thumb": QRectF(),      # painted thumb
            "hover_rect": QRect(),  # whole chat area: hovering it reveals the bar
            "track_zone": QRect(),  # narrow right strip: click to page up/down
            "visible": False,
            "dragging": False,
            "max_off": 0, "track_h": 1, "thumb_h": 0, "vp": 1,
        }
        self._sb_hide_timer = QTimer(self)
        self._sb_hide_timer.setSingleShot(True)
        self._sb_hide_timer.setInterval(800)   # stay visible 800ms after mouse leaves
        self._sb_hide_timer.timeout.connect(self._sb_hide)

        # session panel + per-session view
        self.show_sessions = False
        self.sessions: list[dict] = []
        self._session_rows: list[dict] = []
        self._panel_rect = QRect()
        self.view_session_id: str | None = None   # None = companion chat view
        self.session_msgs: list[dict] = []
        self._view_title = ""

        # permission prompts (opencode plugin asks before mutating tools)
        self._perm = None                 # current permits.PermRequest awaiting a click
        self._perm_chips: list[tuple] = []  # [(QRect, label, decision, always)]
        self._perm_rect = QRect()
        self._perm_server = None

        self._build_window()
        self._build_widgets()
        self._load_sprites()
        self._apply_scale()        # builds scaled assets, fonts, geometry, fixed size
        self._place_initial()      # park bottom-right of the screen
        self._build_tray()
        self._start_idle_timer()
        self._tick_anim()
        self._tick_dots()
        self._poll_queue()
        self.render_bubbles()
        self._set_status("ready")
        self._load_palette()       # discover opencode agents + skills (async)
        self._start_permissions()  # gate mutating tool calls via the bridge plugin

    # ── scale helper ──────────────────────────────────────────────

    def _s(self, v: float) -> int:
        """Scale a base measurement to the current size and round to a pixel."""
        return round(v * self.scale)

    def _qfont(self, base_pt: float, *, family: str = "Segoe UI", bold: bool = False) -> QFont:
        """A QFont at ``base_pt`` scaled to the current size."""
        f = QFont(family)
        f.setPointSizeF(base_pt * self.scale)
        if bold:
            f.setBold(True)
        return f

    def _run_bg(self, work, done):
        """Run ``work()`` off the UI thread; deliver its result to ``done`` on the UI thread."""
        def worker():
            result = work()
            self.ui_queue.put(lambda: done(result))
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _bubble_style(role: str, mic_pulsing: bool):
        """Return (bg, fg, side) for a message bubble of ``role``."""
        if role == "user":
            return USER_BG, USER_FG, "right"
        if role == "pending":
            # during voice recording, dots appear on the speaker's (right) side
            if mic_pulsing:
                return USER_BG, USER_FG, "right"
            return SLIME_BG, PENDING_FG, "left"
        if role == "error":
            return ERR_BG, ERR_FG, "left"
        return SLIME_BG, SLIME_FG, "left"

    # ── window ────────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowTitle("Goo")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

    def _build_widgets(self):
        # text input (hidden until the slime is clicked)
        self.entry = _Entry(self, self._on_send, self._hide_input)
        self.entry.setStyleSheet(
            f"QLineEdit {{ background: {PANEL}; color: {ENTRY_FG};"
            f" border: 1px solid {PANEL_BORDER}; border-radius: 2px;"
            f" padding: 2px 6px; }}"
            f" QLineEdit:focus {{ border: 1px solid {USER_BG}; }}"
        )
        self.entry.hide()
        self.input_visible = False
        self._build_slash_menu()

    def _build_slash_menu(self):
        """Dropdown of slash commands shown when the input starts with '/'.

        Combines the built-in functionalities with the opencode agents/skills
        discovered at startup (picking one switches the agent)."""
        cmd_role = Qt.UserRole + 1   # holds the insert text, separate from display
        entries = list(SLASH_COMMANDS)
        for name, desc in self._skills:
            entries.append((f"/{name} ", f"skill · {desc}" if desc else "skill"))
        for a in self._agents:
            entries.append((f"/{a}", f"agent · switch to the {a} agent"))
        model = QStandardItemModel(self)
        for insert, desc in entries:
            it = QStandardItem()
            it.setEditable(False)
            it.setData(f"{insert.strip()}   {desc}", Qt.DisplayRole)  # popup text
            it.setData(insert, cmd_role)                              # inserted text
            model.appendRow(it)
        completer = QCompleter(model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchStartsWith)
        completer.setCompletionRole(cmd_role)                # match + insert by command
        completer.popup().setStyleSheet(
            f"QListView {{ background: {PANEL}; color: {ENTRY_FG};"
            f" border: 1px solid {PANEL_BORDER}; outline: 0; padding: 2px; }}"
            f" QListView::item {{ padding: 3px 6px; border-radius: 3px; }}"
            f" QListView::item:selected {{ background: {USER_BG}; color: {WHITE}; }}"
        )
        self.entry.setCompleter(completer)

    def _load_palette(self):
        """Discover opencode agents + installed skills (off-thread) for the menu."""
        self._run_bg(self.core.list_agents, self._on_agents)
        self._run_bg(self.core.list_skills, self._on_skills)

    def _on_agents(self, agents: list[str]):
        self._agents = [a.lower() for a in agents]
        self._build_slash_menu()

    def _on_skills(self, skills: list[tuple[str, str]]):
        self._skills = skills
        self._build_slash_menu()

    # ── permission prompts ─────────────────────────────────────────

    def _start_permissions(self):
        """Install the bridge plugin + start the localhost permission server."""
        permits.ensure_plugin_installed()
        try:
            self._perm_server = permits.PermissionServer(self._perm_notify)
            self._perm_server.block_all = self.core.plan_mode
            self._perm_server.start()
            os.environ["COMPANION_PERMS_URL"] = self._perm_server.url
        except OSError:
            self._perm_server = None   # no port: plugin stays inert (env unset)

    def _perm_notify(self, req):
        """Called on the server thread — marshal the ask onto the UI thread."""
        self.ui_queue.put(lambda: self._show_permission(req))

    def _show_permission(self, req):
        self._perm = req
        self._set_state("surprised")
        self._set_status("permission?")
        self.render_bubbles()

    def _resolve_permission(self, decision: str, always: bool = False):
        req = self._perm
        if req is None:
            return
        if always and decision == "allow" and self._perm_server is not None:
            self._perm_server.allow.add(req.tool)
        req.resolve(decision)
        self._perm = None
        self._set_status("…working" if decision == "allow" else "denied")
        self.render_bubbles()

    def _toggle_plan_mode(self):
        on = not self.core.plan_mode
        self.core.set_plan_mode(on)
        if self._perm_server is not None:
            self._perm_server.block_all = on   # hard-deny every mutating tool
        self._set_status("plan mode · read-only" if on else "build mode")
        self.render_bubbles()

    @staticmethod
    def _perm_summary(tool: str, args) -> str:
        if isinstance(args, dict):
            for key in ("command", "path", "filePath", "filepath", "file"):
                v = args.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        try:
            import json as _json
            return _json.dumps(args, ensure_ascii=False)[:140]
        except (TypeError, ValueError):
            return ""

    def _layout_permission(self):
        self._perm_chips = []
        if self._perm is None:
            self._perm_rect = QRect()
            return
        margin = self._s(14)
        w = self.win_w - 2 * margin
        h = self._s(100)
        bottom = self.slime_top - self._s(8)
        top = max(self._s(40), bottom - h)
        self._perm_rect = QRect(margin, top, w, bottom - top)
        pad, ch, gap = self._s(10), self._s(28), self._s(8)
        cy = self._perm_rect.bottom() - pad - ch
        cw = (w - 2 * pad - 2 * gap) // 3
        x = self._perm_rect.x() + pad
        for label, decision, always in (
            ("Allow", "allow", False), ("Always", "allow", True), ("Deny", "deny", False),
        ):
            self._perm_chips.append((QRect(x, cy, cw, ch), label, decision, always))
            x += cw + gap

    def _paint_permission(self, p: QPainter):
        if self._perm is None:
            return
        r = self._perm_rect
        rr = self._s(10)
        p.setPen(QPen(QColor(CAM_BG_ARMED), max(1, self._s(2))))   # amber = caution
        p.setBrush(QColor(*PANEL_FILL))
        p.drawRoundedRect(QRectF(r), rr, rr)
        pad = self._s(10)
        p.setPen(QColor(WHITE))
        p.setFont(self._qfont(10, bold=True))
        p.drawText(QRectF(r.x() + pad, r.y() + pad, r.width() - 2 * pad, self._s(20)),
                   Qt.AlignLeft | Qt.AlignVCenter, f"✋ Allow  {self._perm.tool} ?")
        p.setPen(QColor(DIM))
        p.setFont(self._qfont(8))
        p.drawText(QRectF(r.x() + pad, r.y() + pad + self._s(20),
                          r.width() - 2 * pad, self._s(34)),
                   Qt.TextWordWrap, self._perm_summary(self._perm.tool, self._perm.args))
        chip_color = {"Allow": MIC_BG, "Always": USER_BG, "Deny": MIC_BG_RECORDING}
        p.setFont(self._qfont(9, bold=True))
        for rect, label, _decision, _always in self._perm_chips:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(chip_color[label]))
            p.drawRoundedRect(QRectF(rect), self._s(6), self._s(6))
            p.setPen(QColor(WHITE))
            p.drawText(QRectF(rect), Qt.AlignCenter, label)

    def _load_sprites(self):
        # keep the originals; scaled copies are produced in _apply_scale
        self._orig_images = sprites.load_pixmaps(self._profile)

    def _apply_scale(self):
        """(Re)compute every scaled asset, font and region for the current scale."""
        s = self.scale
        self.win_w = round(BASE_W * s)
        self.win_h = round(BASE_H * s)
        self.setFixedSize(self.win_w, self.win_h)

        # fonts
        self._font = self._qfont(10)
        self._font_small = self._qfont(8)
        self._font_status = self._qfont(9, family="Consolas")
        self._fm = QFontMetrics(self._font)
        self.entry.setFont(self._font)
        self._text_cache.clear()   # font/width changed: rebuild text layouts

        # scaled sprites — FastTransformation = nearest-neighbour, keeps pixels crisp
        self.images = {}
        for name, pm in self._orig_images.items():
            self.images[name] = pm.scaled(
                round(pm.width() * s), round(pm.height() * s),
                Qt.KeepAspectRatio, Qt.FastTransformation,
            )

        idle = self.images["slime_idle_0"]
        self.slime_w = idle.width()
        self.slime_h = idle.height()
        self.slime_cx = self.win_w // 2
        self.slime_by = self.win_h - self._s(8)        # bottom anchor of slime
        self.slime_top = self.slime_by - self.slime_h

        # interactive regions
        cs = self._s(22)
        m = self._s(8)
        self._close_rect = QRect(self.win_w - m - cs, m, cs, cs)
        # session-list toggle, just left of the close button
        self._list_rect = QRect(self._close_rect.x() - cs - self._s(6), m, cs, cs)
        # build/plan mode pill, top-left
        self._plan_rect = QRect(m, self._s(6), self._s(52), self._s(18))
        self._mic_r = self._s(MIC_R)
        self._cam_r = self._mic_r
        # stack vertically at bottom-right: mic on top, camera below it
        bx = self.win_w - self._s(30)
        cam_y = self.slime_by - self._s(28)                       # lower button, near bottom
        mic_y = cam_y - (2 * self._mic_r + self._s(8))           # mic sits above the camera
        self._mic_center = QPoint(bx, mic_y)
        self._cam_center = QPoint(bx, cam_y)
        self._slime_rect = QRect(
            self.slime_cx - self.slime_w // 2, self.slime_top,
            self.slime_w, self.slime_h,
        )

        if self.input_visible:
            self._position_entry()

    def _place_initial(self):
        screen = QGuiApplication.primaryScreen().geometry()
        x = screen.width() - self.win_w - 30
        y = screen.height() - self.win_h - 70
        self.move(x, y)

    # ── resize ────────────────────────────────────────────────────

    def _set_scale(self, new_scale: float):
        """Change the companion's size, keeping the slime's feet anchored on screen."""
        new_scale = max(SCALE_MIN, min(SCALE_MAX, new_scale))
        if abs(new_scale - self.scale) < 1e-3:
            return
        anchor = self.mapToGlobal(QPoint(self.slime_cx, self.slime_by))
        self.scale = new_scale
        self._apply_scale()
        self.move(anchor - QPoint(self.slime_cx, self.slime_by))
        self.render_bubbles()

    # ── system tray ───────────────────────────────────────────────

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(QIcon(self._orig_images["slime_idle_0"]), self)
        self._tray.setToolTip("Goo")
        menu = QMenu()
        act_toggle = QAction("Show / hide", self)
        act_toggle.triggered.connect(self._toggle_visible)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_toggle)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visible()

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    # ── painting ──────────────────────────────────────────────────

    def paintEvent(self, _ev):  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # leave SmoothPixmapTransform OFF so pixel art stays crisp when scaled
        self._paint_bubbles(p)
        if self.show_sessions:
            self._paint_sessions(p)
        self._paint_slime(p)
        self._paint_buttons(p)
        self._paint_status(p)
        self._paint_scrollbar(p)
        self._paint_permission(p)   # on top: consent prompt
        p.end()

    def _paint_bubbles(self, p: QPainter):
        p.setFont(self._font)
        p.save()
        p.setClipRect(self._viewport)   # clip partial bubbles at the viewport edges
        for b in self._placed:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(b["bg"]))
            p.drawRoundedRect(b["rect"], b["r"], b["r"])
            if b["doc"] is not None:
                # rendered markdown — clip to the text rect INTERSECTED with the
                # viewport (IntersectClip; plain setClipRect would replace it and
                # let tall docs paint past the viewport, over the slime)
                p.save()
                p.setClipRect(b["trect"], Qt.IntersectClip)
                p.translate(b["trect"].topLeft())
                ctx = QAbstractTextDocumentLayout.PaintContext()
                ctx.palette.setColor(QPalette.Text, QColor(b["fg"]))
                b["doc"].documentLayout().draw(p, ctx)
                p.restore()
            else:
                p.setPen(QColor(b["fg"]))
                p.drawText(b["trect"], Qt.TextWordWrap, b["text"])
        p.restore()

    def _paint_slime(self, p: QPainter):
        pm = self.images[self._cur_frame]
        sx = getattr(self, '_munch_sx', 1.0)
        sy = getattr(self, '_munch_sy', 1.0)

        if sx == 1.0 and sy == 1.0:
            # fast path — no munch scaling active
            x = self.slime_cx - pm.width() // 2
            y = self.slime_by - pm.height()
            p.drawPixmap(x, y, pm)
        else:
            # munch: scale the pixmap about its bottom-centre anchor
            tw = round(pm.width() * sx)
            th = round(pm.height() * sy)
            x = self.slime_cx - tw // 2
            y = self.slime_by - th
            p.drawPixmap(QRect(x, y, tw, th), pm)
        # draw "zzz" bubbles when sleeping
        if self.state == "sleep":
            self._paint_zzz(p, x, y)

    def _paint_buttons(self, p: QPainter):
        rr = self._s(6)
        # session-list toggle (left of close); brighter when the panel is open
        p.setPen(QPen(QColor(PANEL_BORDER)))
        p.setBrush(QColor(USER_BG if self.show_sessions else PANEL))
        p.drawRoundedRect(QRectF(self._list_rect), rr, rr)
        p.setPen(QColor(WHITE if self.show_sessions else DIM))
        p.setFont(self._qfont(12))
        p.drawText(QRectF(self._list_rect), Qt.AlignCenter, "☰")

        # close button, top-right
        p.setPen(QPen(QColor(PANEL_BORDER)))
        p.setBrush(QColor(PANEL))
        p.drawRoundedRect(QRectF(self._close_rect), rr, rr)
        p.setPen(QColor(DIM))
        p.setFont(self._qfont(13, bold=True))
        p.drawText(QRectF(self._close_rect), Qt.AlignCenter, "×")

        # camera button — blue circle left of the mic (amber once a shot is staged)
        armed = self._pending_shot is not None
        cam_fill = CAM_BG_ARMED if armed else (CAM_BG_HOVER if self._cam_hover else CAM_BG)
        cam_border = CAM_BORDER_ARMED if armed else CAM_BORDER
        p.setPen(QPen(QColor(cam_border), max(1, self._s(2))))
        p.setBrush(QColor(cam_fill))
        p.drawEllipse(self._cam_center, self._cam_r, self._cam_r)
        self._paint_glyph(p, CAM_PIXELS, self._cam_center, self._cam_r, CAM_FG)

        # mic button — bright green circle, bottom-right near the slime
        border = MIC_BORDER_RECORDING if self._mic_pulsing else MIC_BORDER
        p.setPen(QPen(QColor(border), max(1, self._s(2))))
        p.setBrush(QColor(self._mic_fill()))
        p.drawEllipse(self._mic_center, self._mic_r, self._mic_r)
        self._paint_glyph(p, MIC_PIXELS, self._mic_center, self._mic_r, MIC_FG)

    def _paint_glyph(self, p: QPainter, pixels, center: QPoint, r: int, color: str):
        """Draw a pixel-art glyph ('#'/' ' rows) centred in a circle of radius r."""
        gh, gw = len(pixels), len(pixels[0])
        px = max(1, round(r * 2 * 0.5 / gh))   # glyph ~half the diameter tall
        ox = center.x() - gw * px // 2
        oy = center.y() - gh * px // 2
        p.setRenderHint(QPainter.Antialiasing, False)    # keep pixels crisp
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        for ry, row in enumerate(pixels):
            for cx, ch in enumerate(row):
                if ch != " ":
                    p.drawRect(ox + cx * px, oy + ry * px, px, px)
        p.setRenderHint(QPainter.Antialiasing, True)

    def _paint_status(self, p: QPainter):
        self._paint_plan_toggle(p)
        p.setPen(QColor(DIM))
        p.setFont(self._font_status)
        label = f"#{self._view_title}" if self.view_session_id else self.core.active_label()
        text = f"{label} · {self._status_text}"
        sx = self._plan_rect.right() + self._s(8)   # start right of the mode pill
        # leave room for the ☰ / × buttons on the right
        sw = self._list_rect.left() - self._s(6) - sx
        p.drawText(QRectF(sx, self._s(6), max(self._s(20), sw), self._s(20)),
                   Qt.AlignVCenter | Qt.AlignLeft, text)

    def _paint_plan_toggle(self, p: QPainter):
        """Binary Build/Plan pill (top-left). Plan = opencode's read-only agent."""
        plan = self.core.plan_mode
        r = self._plan_rect
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(USER_BG if plan else MIC_BG))   # blue = plan, green = build
        p.drawRoundedRect(QRectF(r), r.height() / 2, r.height() / 2)
        p.setPen(QColor(WHITE))
        p.setFont(self._qfont(8, bold=True))
        p.drawText(QRectF(r), Qt.AlignCenter, "PLAN" if plan else "BUILD")

    def _paint_scrollbar(self, p: QPainter):
        if not self._sb_visible():
            return
        rr = self._s(3)
        # track
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(self._sb["rect"]), rr, rr)
        # thumb — brighter when being dragged
        alpha = 180 if self._sb["dragging"] else 120
        p.setBrush(QColor(255, 255, 255, alpha))
        p.drawRoundedRect(self._sb["thumb"], rr, rr)

    def _paint_zzz(self, p: QPainter, slime_x: int, slime_y: int):
        """Draw animated 'zzz' bubbles floating above the sleeping slime."""
        t = self._zzz_t
        font = self._qfont(10, bold=True)
        p.setFont(font)

        # Three "z" at staggered phases, floating upward and fading
        for i, (base_size, phase) in enumerate([
            (8, 0.0), (10, 0.35), (12, 0.7)
        ]):
            cycle = (t * 0.4 + phase) % 1.0  # 0→1 over ~2.5s, staggered
            # position: rise from slime top, drift slightly right
            rise = cycle * self._s(50)
            drift = self._s(8) * cycle + self._s(i * 6)
            zx = slime_x + self.slime_w + drift - self._s(20)
            zy = slime_y + self._s(10) - rise
            # alpha: fade in then out
            if cycle < 0.15:
                alpha = int(255 * cycle / 0.15)
            elif cycle > 0.75:
                alpha = int(255 * (1.0 - cycle) / 0.25)
            else:
                alpha = 255
            alpha = max(0, min(255, alpha))
            size = base_size + int(cycle * 4)
            f = self._qfont(size, bold=True)
            p.setFont(f)
            p.setPen(QColor(200, 220, 255, alpha))
            label = "z" * (i + 1)
            p.drawText(QPointF(zx, zy), label)

    # ── session panel ─────────────────────────────────────────────

    def _layout_sessions(self):
        """Compute the panel + clickable row rects for the current size."""
        pad, rh, gap = self._s(10), self._s(30), self._s(4)
        x1, x2 = self._s(14), self.win_w - self._s(14)
        top = self._s(40)
        bottom = self.slime_top - self._s(10)
        rows: list[dict] = []
        y = top + self._s(34)  # below the panel title

        # "back to chat" home row first
        rows.append({"kind": "chat", "rect": QRect(x1 + pad, y, x2 - x1 - 2 * pad, rh)})
        y += rh + gap
        for s in self.sessions:
            if y + rh > bottom:
                break
            rows.append({"kind": "session", "session": s,
                         "rect": QRect(x1 + pad, y, x2 - x1 - 2 * pad, rh)})
            y += rh + gap

        self._session_rows = rows
        self._panel_rect = QRect(x1, top, x2 - x1, min(y, bottom) - top + self._s(6))

    def _paint_sessions(self, p: QPainter):
        rr = self._s(10)
        p.setPen(QPen(QColor(PANEL_BORDER)))
        p.setBrush(QColor(*PANEL_FILL))
        p.drawRoundedRect(QRectF(self._panel_rect), rr, rr)

        # title
        p.setPen(QColor(DIM))
        p.setFont(self._font)
        p.drawText(QRectF(self._panel_rect.x() + self._s(12), self._panel_rect.y() + self._s(6),
                          self._panel_rect.width() - self._s(24), self._s(24)),
                   Qt.AlignLeft | Qt.AlignVCenter, "Sessions")

        dr = self._s(5)
        for row in self._session_rows:
            r = row["rect"]
            if row["kind"] == "chat":
                active = self.view_session_id is None
                dot = DOT_ACTIVE if active else DOT_IDLE
                label = "↩  Goo (chat)"
            else:
                s = row["session"]
                sid = s["id"]
                active = self.view_session_id == sid
                if sid in self.core.running:
                    dot = DOT_RUNNING
                elif active:
                    dot = DOT_ACTIVE
                else:
                    dot = DOT_IDLE
                label = s.get("title") or "(untitled)"

            if active:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(*ROW_ACTIVE))
                p.drawRoundedRect(QRectF(r), self._s(6), self._s(6))

            cy = r.y() + r.height() // 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(dot))
            p.drawEllipse(QPoint(r.x() + self._s(10), cy), dr, dr)

            p.setPen(QColor(ROW_FG))
            p.setFont(self._font)
            tx = r.x() + self._s(22)
            avail = r.width() - self._s(28)
            el = self._fm.elidedText(label, Qt.ElideRight, avail)
            p.drawText(QRect(tx, r.y(), avail, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, el)

    def _mic_fill(self):
        """Return the current mic fill colour, accounting for recording pulse."""
        if self._mic_pulsing:
            return MIC_BG_RECORDING_ALT if self._mic_pulse_on else MIC_BG_RECORDING
        if self._mic_hover:
            return MIC_BG_HOVER
        return MIC_BG

    def _start_mic_pulse(self):
        """Begin red pulsing animation on the mic button."""
        self._mic_pulsing = True
        self._mic_pulse_on = False
        self.update()
        self._mic_pulse_tick()

    def _mic_pulse_tick(self):
        if not self._mic_pulsing:
            return
        self._mic_pulse_on = not self._mic_pulse_on
        self.update()
        QTimer.singleShot(400, self._mic_pulse_tick)

    def _stop_mic_pulse(self):
        """Stop pulsing and restore the mic to idle green."""
        self._mic_pulsing = False
        self.update()

    # ── screenshot ────────────────────────────────────────────────

    def _capture_screenshot(self):
        """Grab the screen (with the pet hidden) and stage it for the next message."""
        if self.busy or self._pending_shot is not None:
            return
        # hide the pet so it isn't in the shot; grab once the compositor catches up
        self.hide()
        QTimer.singleShot(180, self._do_capture)

    def _do_capture(self):
        screen = QGuiApplication.primaryScreen()
        pm = screen.grabWindow(0) if screen else None
        self.show()
        self.raise_()
        if pm is None or pm.isNull():
            self._set_status("screenshot failed")
            return
        try:
            SHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = str(SHOT_DIR / time.strftime("shot_%Y%m%d_%H%M%S.png"))
            if not pm.save(path):
                raise OSError("save failed")
        except OSError:
            self._set_status("screenshot save failed")
            return
        self._pending_shot = path
        self._set_status("screenshot ready — ask about it")
        self._show_input()   # camera button goes amber; type a question + Enter

    # ── session panel control ─────────────────────────────────────

    def _toggle_sessions(self):
        self.show_sessions = not self.show_sessions
        if self.show_sessions:
            self._refresh_sessions_async()
        self.render_bubbles()

    def _refresh_sessions_async(self):
        self._run_bg(self.core.refresh_sessions, self._on_sessions)

    def _on_sessions(self, sess: list[dict]):
        self.sessions = sess
        if self.show_sessions:
            self.render_bubbles()

    def _open_session(self, s: dict):
        """Open a session: make it the active target and show its transcript."""
        sid = s["id"]
        self.view_session_id = sid
        self._view_title = (s.get("title") or sid)[:30]
        self.core.set_active(s)
        self.show_sessions = False
        self.scroll_px = 0
        self.session_msgs = [{"role": "slime", "text": "opening…"}]
        self._set_status("loading…")
        self.render_bubbles()
        self._run_bg(lambda: self.core.session_transcript(sid),
                     lambda msgs: self._on_transcript(sid, msgs))

    def _on_transcript(self, sid: str, msgs: list[dict]):
        if self.view_session_id != sid:
            return
        self.session_msgs = msgs or [{"role": "slime", "text": "(no messages yet)"}]
        self._set_status("ready")
        self.scroll_px = 0
        self.render_bubbles()

    def _back_to_chat(self):
        self.view_session_id = None
        self.show_sessions = False
        self.scroll_px = 0
        self._set_status("ready")
        self.render_bubbles()

    # ── slime interaction: click / drag-move / drag-resize / wheel ──

    def _on_slime(self, pos: QPoint) -> bool:
        return self._slime_rect.contains(pos)

    def _on_mic_btn(self, pos: QPoint) -> bool:
        dx = pos.x() - self._mic_center.x()
        dy = pos.y() - self._mic_center.y()
        return dx * dx + dy * dy <= self._mic_r * self._mic_r

    def _on_cam_btn(self, pos: QPoint) -> bool:
        dx = pos.x() - self._cam_center.x()
        dy = pos.y() - self._cam_center.y()
        return dx * dx + dy * dy <= self._cam_r * self._cam_r

    def mousePressEvent(self, e):  # noqa: N802 (Qt override)
        pos = e.position().toPoint()
        if e.button() == Qt.RightButton:
            # right-drag on the slime resizes the companion
            if self._on_slime(pos):
                self._resizing = (e.globalPosition().toPoint().y(), self.scale)
            return
        if e.button() != Qt.LeftButton:
            return
        if self._close_rect.contains(pos):
            self.quit()
            return
        if self._perm is not None:
            # modal while a permission is pending: only the chips (or close) act
            for rect, _label, decision, always in self._perm_chips:
                if rect.contains(pos):
                    self._resolve_permission(decision, always)
                    break
            return
        if self._plan_rect.contains(pos):
            self._toggle_plan_mode()
            return
        if self._list_rect.contains(pos):
            self._toggle_sessions()
            return
        if self.show_sessions:
            for row in self._session_rows:
                if row["rect"].contains(pos):
                    if row["kind"] == "chat":
                        self._back_to_chat()
                    else:
                        self._open_session(row["session"])
                    return
            if self._panel_rect.contains(pos):
                return   # click inside panel chrome: swallow, keep it open
        if self._on_cam_btn(pos):
            self._capture_screenshot()
            return
        if self._on_mic_btn(pos):
            self._on_mic()
            return
        # scrollbar thumb: start drag (hit-test with wider zone for easy grab)
        if self._sb["visible"] and self._sb["max_off"] > 0:
            hit = self._sb["thumb"].toRect().adjusted(-self._s(4), 0, self._s(4), 0)
            if hit.contains(pos):
                self._sb["dragging"] = True
                self._sb["_drag_start"] = self.scroll_px
                self._sb["_drag_y"] = e.globalPosition().toPoint().y()
                return
        # scrollbar track click (not on thumb): page up/down — only on the
        # narrow right strip, so clicking mid-chat doesn't jump the scroll
        if self._sb["visible"] and self._sb["max_off"] > 0 and self._sb["track_zone"].contains(pos):
            page = int(self._sb["vp"] * 0.9)
            up = pos.y() < self._sb["thumb"].center().y()   # above thumb -> older
            self.scroll_px = max(0, min(self._sb["max_off"],
                                        self.scroll_px + (page if up else -page)))
            self.render_bubbles()
            return
        if self._on_slime(pos):
            self._press = (e.globalPosition().toPoint(), self.pos())
            self._moved = False

    def mouseMoveEvent(self, e):  # noqa: N802 (Qt override)
        if self._sb["dragging"]:
            # scrollbar drag: dragging the thumb DOWN moves toward newest (off down)
            track_h = self._sb.get("track_h", 1)
            thumb_h = self._sb.get("thumb_h", 0)
            max_off = self._sb.get("max_off", 0)
            travel = max(1, track_h - thumb_h)
            dy = e.globalPosition().toPoint().y() - self._sb["_drag_y"]
            self.scroll_px = max(0, min(max_off,
                                        round(self._sb["_drag_start"] - dy / travel * max_off)))
            self.render_bubbles()
            return
        if self._resizing is not None:
            start_y, start_scale = self._resizing
            dy = e.globalPosition().toPoint().y() - start_y
            self._set_scale(start_scale + dy * SCALE_DRAG_GAIN)  # drag down = bigger
            return
        if self._press is None:
            # hover feedback for mic/camera buttons + scrollbar visibility
            pos = e.position().toPoint()
            mic_over, cam_over = self._on_mic_btn(pos), self._on_cam_btn(pos)
            sb_hover = self._sb["hover_rect"].contains(pos)
            changed = (mic_over != self._mic_hover or cam_over != self._cam_hover
                       or sb_hover != self._sb["visible"])
            if changed:
                self._mic_hover, self._cam_hover = mic_over, cam_over
                if sb_hover:
                    self._sb_hide_timer.stop()   # cancel pending hide
                    self._sb["visible"] = True
                else:
                    self._sb_hide_timer.start()   # will hide after delay
                if not self._mic_pulsing:
                    self.update()
            return
        # dragging the slime moves the whole window
        delta = e.globalPosition().toPoint() - self._press[0]
        if abs(delta.x()) > 3 or abs(delta.y()) > 3:
            self._moved = True
        self.move(self._press[1] + delta)

    def mouseReleaseEvent(self, e):  # noqa: N802 (Qt override)
        if self._sb["dragging"]:
            self._sb["dragging"] = False
            self._sb_hide_timer.start()   # start linger timer after drag release
            return
        if e.button() == Qt.RightButton:
            self._resizing = None
            return
        if self._press is not None and not self._moved:
            self._toggle_input()
        self._press = None

    # ── drag & drop: files onto the slime ──────────────────────────

    def dragEnterEvent(self, e):  # noqa: N802 (Qt override)
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):  # noqa: N802 (Qt override)
        if self._on_slime(e.position().toPoint()):
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802 (Qt override)
        if not self._on_slime(e.position().toPoint()):
            return
        urls = e.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if not path:
            return
        # paste the file path into the input box but don't send
        if not self.input_visible:
            self._show_input()
        self.entry.setText(path)
        self._start_munch()

    def wheelEvent(self, e):  # noqa: N802 (Qt override)
        angle = e.angleDelta().y()
        if self.show_sessions and self._panel_rect.contains(e.position().toPoint()):
            return  # don't scroll history while the panel is open
        if self._on_slime(e.position().toPoint()):
            # wheel over the slime resizes; wheel elsewhere scrolls history
            step = SCALE_WHEEL_STEP if angle > 0 else -SCALE_WHEEL_STEP
            self._set_scale(self.scale + step)
            return
        # wheel up -> older (increase offset from bottom); down -> newer
        step = self._s(48)
        self.scroll_px = max(0, self.scroll_px + (step if angle > 0 else -step))
        # briefly show scrollbar on wheel scroll
        self._sb["visible"] = True
        self._sb_hide_timer.start()
        self.render_bubbles()   # clamps scroll_px to [0, max_off]

    def _sb_hide(self):
        """Hide the scrollbar (called by the linger timer)."""
        if not self._sb["dragging"]:
            self._sb["visible"] = False
            self.update()

    def leaveEvent(self, _ev):  # noqa: N802 (Qt override)
        """Start linger timer to hide scrollbar when mouse leaves the window."""
        if self._sb["visible"] and not self._sb["dragging"]:
            self._sb_hide_timer.start()

    # ── input box ─────────────────────────────────────────────────

    def _position_entry(self):
        # anchored bottom-left at (14, slime_top - 16), like the old canvas window
        h = self._s(28)
        self.entry.setGeometry(
            self._s(14), self.slime_top - self._s(16) - h,
            self.win_w - self._s(70), h,
        )

    def _toggle_input(self):
        if self.input_visible:
            self._hide_input()
        else:
            self._show_input()

    def _show_input(self):
        self._position_entry()
        self.entry.show()
        self.input_visible = True
        self.entry.setFocus()
        self.render_bubbles()

    def _hide_input(self):
        self.entry.hide()
        self.input_visible = False
        if self._pending_shot is not None:
            self._pending_shot = None   # discard staged screenshot on cancel
            self._set_status("ready")
        self.setFocus()
        self.render_bubbles()

    # ── status line ───────────────────────────────────────────────

    def _set_status(self, state_text: str):
        self._status_text = state_text
        self.update()

    # ── bubbles ───────────────────────────────────────────────────

    def _activity_for(self, hint: str) -> str:
        """Map a raw opencode activity hint to a friendly label.

        Handles built-ins, MCP tools (namespaced ``server_tool`` — e.g.
        ``hashline_read``), dispatch hints (``#2``), and unknown tools (shown
        de-namespaced so they stay readable and distinct).
        """
        if "\t" in hint:                     # "tool\tdetail" → "label: detail"
            tool, detail = hint.split("\t", 1)
            base = tool.lower()
            label = ACTIVITY_LABELS.get(base)
            if label is None and "_" in base:
                label = ACTIVITY_LABELS.get(base.rsplit("_", 1)[1])
            label = label or tool.replace("_", " ")
            return f"{label}: {detail}" if detail else label
        if hint.startswith("#"):
            return f"session {hint}"
        key = hint.lower()
        if key in ACTIVITY_LABELS:
            return ACTIVITY_LABELS[key]
        if "_" in key:                       # MCP tool: try the bare tool name
            base = key.rsplit("_", 1)[1]
            if base in ACTIVITY_LABELS:
                return ACTIVITY_LABELS[base]
        return hint.replace("_", " ")        # unknown/free-text: show verbatim

    def _pending_text(self) -> str:
        """Live step label + animated dots + seconds on this step (stuck signal)."""
        label = self._activity_label or "thinking"
        elapsed = int(time.monotonic() - self._activity_at) if self._activity_at else 0
        secs = f"  ({elapsed}s)" if elapsed >= 2 else ""
        return f"{label}{self._dots}{secs}"

    def _visible_messages(self):
        base = self.session_msgs if self.view_session_id else self.core.history
        msgs = list(base)
        if self.busy:
            msgs = msgs + [{"role": "pending", "text": self._pending_text()}]
        return msgs

    def _measure(self, text, wrap):
        r = self._fm.boundingRect(QRect(0, 0, wrap, 100000),
                                  Qt.TextWordWrap, text)
        return r.width(), r.height()

    def _text_layout(self, text: str, inner: int) -> dict:
        """Return {tw, th, doc} for a message, rendering markdown when detected.

        Cached by text (cache is cleared on rescale, which changes font/width).
        ``doc`` is a QTextDocument for markdown, or None for plain text.
        """
        cached = self._text_cache.get(text)
        if cached is not None:
            return cached
        if _looks_markdown(text):
            doc = QTextDocument()
            doc.setDefaultFont(self._font)
            doc.setDocumentMargin(0)
            doc.setTextWidth(inner)
            doc.setMarkdown(text)
            # Lay the doc out at the EXACT width the bubble will be, so the
            # background encloses it (no horizontal spill for tables/wide lines).
            tw = min(inner, int(doc.idealWidth()) + 1)
            doc.setTextWidth(tw)
            th = int(doc.size().height()) + 1
            lay = {"tw": tw, "th": th, "doc": doc}
        else:
            tw, th = self._measure(text, inner)
            lay = {"tw": tw, "th": th, "doc": None}
        if len(self._text_cache) > 400:      # bound the cache (pending dots etc.)
            self._text_cache.clear()
        self._text_cache[text] = lay
        return lay

    def render_bubbles(self):
        msgs = self._visible_messages()

        pad_x, pad_y, gap, radius = self._s(10), self._s(7), self._s(8), self._s(11)
        margin = self._s(14)
        max_w = int(self.win_w * 0.76)
        inner = max_w - 2 * pad_x
        top_limit = self._s(40)
        bottom = (self.slime_top - self._s(16)) - (self._s(34) if self.input_visible else self._s(4))
        vp = max(1, bottom - top_limit)               # viewport height
        self._viewport = QRect(0, top_limit, self.win_w, vp)

        # measure every bubble (oldest -> newest), build a virtual column
        items = []          # (msg, bw, bh, doc)
        content_h = 0
        for i, msg in enumerate(msgs):
            lay = self._text_layout(msg["text"] or "", inner)
            bw, bh = lay["tw"] + 2 * pad_x, lay["th"] + 2 * pad_y
            items.append((msg, bw, bh, lay["doc"]))
            content_h += bh + (gap if i < len(msgs) - 1 else 0)

        max_off = max(0, content_h - vp)
        if self._pin_top and items:
            # show the newest message from its top, then let the user scroll down
            nh = items[-1][2]
            self.scroll_px = max(0, min(max_off, nh - vp))
            self._pin_top = False
        self.scroll_px = max(0, min(max_off, self.scroll_px))
        win_start = content_h - vp - self.scroll_px   # virtual y at the viewport top

        draw: list[dict] = []
        y = 0
        for msg, bw, bh, doc in items:
            by0, by1 = y, y + bh
            if by1 > win_start and by0 < win_start + vp:   # intersects viewport
                sy = top_limit + (by0 - win_start)
                bg, fg, side = self._bubble_style(msg["role"], self._mic_pulsing)
                x1 = (self.win_w - margin - bw) if side == "right" else margin
                draw.append({
                    "bg": bg, "fg": fg, "r": radius, "doc": doc,
                    "rect": QRectF(x1, sy, bw, bh),
                    # text rect = the bubble's interior (so the bg always encloses it)
                    "trect": QRectF(x1 + pad_x, sy + pad_y, bw - 2 * pad_x, bh - 2 * pad_y),
                    "text": msg["text"] or "",
                })
            y = by1 + gap

        if self.show_sessions:
            self._layout_sessions()
        self._layout_permission()
        self._placed = draw
        self._compute_scrollbar(top_limit, bottom, content_h, vp)
        self._update_mask(draw)
        self.update()

    def _compute_scrollbar(self, top: int, bottom: int, content_h: int, vp: int):
        """Calculate scrollbar geometry from pixel scroll state (show only on hover)."""
        self._sb["rect"] = QRect()
        self._sb["thumb"] = QRectF()
        self._sb["hover_rect"] = QRect()
        self._sb["track_zone"] = QRect()
        track_h = bottom - top
        max_off = max(0, content_h - vp)
        if track_h <= 0 or max_off <= 0:    # nothing to scroll
            self._sb["max_off"] = 0
            return

        sb_w = self._s(6)
        sb_x = self.win_w - self._s(10)
        self._sb["rect"] = QRect(sb_x, top, sb_w, track_h)
        # hover zone = the WHOLE chat area, so hovering anywhere reveals the bar
        self._sb["hover_rect"] = QRect(0, top, self.win_w, track_h)
        # narrow strip for track page-clicks, so clicking mid-chat doesn't jump
        self._sb["track_zone"] = QRect(self.win_w - self._s(16), top, self._s(16), track_h)

        thumb_h = max(self._s(24), int(track_h * vp / content_h))
        frac = 1 - self.scroll_px / max_off          # 0 = oldest (top), 1 = newest (bottom)
        pos = frac * (track_h - thumb_h)
        self._sb["thumb"] = QRectF(sb_x, top + pos, sb_w, thumb_h)
        self._sb["max_off"] = max_off
        self._sb["track_h"] = track_h
        self._sb["thumb_h"] = thumb_h
        self._sb["vp"] = vp

    def _sb_visible(self) -> bool:
        return self._sb["visible"] and self._sb["thumb"].height() > 0

    # ── scrollbar painting ─────────────────────────────────────────

    def _update_mask(self, draw: list[dict]):
        """Mask the window to its visible content so empty space is click-through."""
        reg = QRegion(QRect(self._s(8), self._s(4),
                            self.win_w - self._s(16), self._s(26)))  # status + buttons band
        for c, r in ((self._mic_center, self._mic_r), (self._cam_center, self._cam_r)):
            reg += QRect(c.x() - r - 2, c.y() - r - 2, 2 * r + 4, 2 * r + 4)
        reg += self._slime_rect
        # the chat viewport: one rect covering all (clipped) bubbles; also makes the
        # whole chat area the hover/wheel zone for the scrollbar
        if draw:
            reg += self._viewport
        if self.input_visible:
            reg += self.entry.geometry()
        if self.show_sessions:
            reg += self._panel_rect
        if self._perm is not None and not self._perm_rect.isNull():
            reg += self._perm_rect
        # scrollbar hover zone
        sb_hover = self._sb.get("hover_rect", QRect())
        if sb_hover.width() > 0 and sb_hover.height() > 0:
            reg += sb_hover
        # zzz area: when sleeping, extend mask above-right of slime for the bubbles
        if self.state == "sleep":
            zzz_rect = QRect(
                self.slime_cx, self.slime_top - self._s(55),
                self._s(50), self._s(60),
            )
            reg += zzz_rect
        self.setMask(reg)

    # ── sending ───────────────────────────────────────────────────

    def _on_send(self):
        text = self.entry.text().strip()
        if not text or self.busy:
            return
        out = self._maybe_slash(text)   # may rewrite, or run a UI action
        self.entry.setText("")
        if out:
            self.send(out)

    def _maybe_slash(self, text: str) -> str | None:
        """Expand a leading slash command. Returns the text to send, or None when
        it was a one-shot UI action (or needs an argument that wasn't given)."""
        if not text.startswith("/"):
            return text
        head, _, rest = text[1:].partition(" ")
        cmd, rest = head.lower(), rest.strip()
        if cmd == "ls":
            return "ls"
        if cmd == "sessions":
            self._toggle_sessions()
            return None
        if cmd == "screenshot":
            self._capture_screenshot()
            return None
        if cmd in ("new", "note", "all"):
            return f"{cmd}: {rest}" if rest else None
        if cmd in self._agents:
            self.core.set_agent(cmd)
            self._set_status(f"agent → {cmd}")
            self.render_bubbles()
            return rest or None   # if a prompt followed, run it under the new agent
        return text   # unknown slash: send verbatim

    def send(self, text: str):
        if self.busy:
            return
        self.busy = True
        self._pin_top = True   # show the new turn from its top
        self.stop_event = threading.Event()
        stop = self.stop_event
        self._mark_active()
        self._set_state("think")
        self._activity_label = "thinking"
        self._activity_at = time.monotonic()

        # consume a staged screenshot, if any
        files = [self._pending_shot] if self._pending_shot else None
        self._pending_shot = None
        shown = f"📷 {text}" if files else text

        def activity(hint):
            label = self._activity_for(hint)

            def apply():
                self._activity_label = label
                self._activity_at = time.monotonic()   # reset elapsed for the new step
                self._set_status(f"…{label}")
                if self.busy:
                    self.render_bubbles()   # reflect the step in the pending bubble
            self.ui_queue.put(apply)

        if self.view_session_id:
            # prompt goes to the open session; run it via the CLI
            sid = self.view_session_id
            self.session_msgs.append({"role": "user", "text": shown})
            self._set_status("running…")
            self.render_bubbles()
            self._run_bg(
                lambda: self.core.run_on_session(sid, text, on_activity=activity,
                                                 stop_event=stop, files=files),
                lambda reply: self._on_session_reply(sid, reply),
            )
            return

        # companion chat: route through the normal brain
        self.core.log("user", shown)
        self._set_status("thinking…")
        self.render_bubbles()
        self._run_bg(
            lambda: self.core.respond(text, on_activity=activity, stop_event=stop, files=files),
            self._on_reply,
        )

    def _reply_anim(self, is_error: bool):
        """Slime reaction after a reply: talk/error -> (happy) -> idle."""
        if is_error:
            self._set_state("error")
            self._set_status("oops…")
            QTimer.singleShot(2000, lambda: self._set_state("idle"))
        else:
            self._set_state("talk")
            self._set_status("ready")

            def _happy_then_idle():
                self._set_state("happy")
                QTimer.singleShot(1500, lambda: self._set_state("idle"))
            QTimer.singleShot(2000, _happy_then_idle)

    def _on_reply(self, reply: str):
        self.busy = False
        self._activity_label = ""
        self._pin_top = True   # show the reply from its top
        is_error = reply.startswith("Hmm, that wobbled wrong")
        self.core.log("error" if is_error else "slime", reply)
        self._mark_active()
        self._reply_anim(is_error)
        self.render_bubbles()

    def _on_session_reply(self, sid: str, reply: str):
        self.busy = False
        self._activity_label = ""
        self._pin_top = True   # show the reply from its top
        is_error = reply.startswith("Hmm, that wobbled wrong")
        if self.view_session_id == sid:
            self.session_msgs.append({"role": "error" if is_error else "slime", "text": reply})
        self._mark_active()
        self._reply_anim(is_error)
        self.render_bubbles()

        # re-sync from the CLI (authoritative — reflects tool edits etc.)
        if not is_error:
            self._run_bg(lambda: self.core.session_transcript(sid),
                         lambda msgs: self._sync_transcript(sid, msgs))

    def _sync_transcript(self, sid: str, msgs: list[dict]):
        if self.view_session_id == sid and msgs:
            self.session_msgs = msgs
            self.render_bubbles()

    # ── microphone ────────────────────────────────────────────────

    def _on_mic(self):
        if self.busy:
            return
        if not voice.available():
            self.core.log("error", "STT not installed. `pip install sounddevice sherpa-onnx`")
            self.render_bubbles()
            return
        self.busy = True
        self._mark_active()
        self._set_state("think")
        self._activity_label = "listening"
        self._activity_at = time.monotonic()
        self._set_status("listening…")
        self._start_mic_pulse()
        self.render_bubbles()
        self._run_bg(voice.listen, self._after_listen)

    def _after_listen(self, text: str | None):
        self.busy = False
        self._activity_label = ""
        self._stop_mic_pulse()
        self._set_state("idle")
        self._set_status("ready")
        if text:
            self.send(text)
        else:
            self._set_status("didn't catch that")
            self.render_bubbles()

    # ── stop ──────────────────────────────────────────────────────

    def _stop_current(self):
        if self.stop_event:
            self.stop_event.set()

    # ── idle expressions ──────────────────────────────────────────

    def _mark_active(self):
        """Reset the idle timer — the user just did something."""
        self._idle_since = None

    def _start_idle_timer(self):
        """Periodically check: if idle long enough, play a random expression."""
        def _check():
            if not self.busy and self.state == "idle":
                now = time.monotonic()
                if self._idle_since is None:
                    self._idle_since = now
                elif now - self._idle_since > 60:
                    # deep idle: enter sleep mode + consolidate memory in the
                    # background (throttled inside core; never blocks the UI)
                    self._set_state("sleep")
                    self._set_status("sleeping 💤")
                    self._idle_since = now
                    self._run_bg(self.core.consolidate_memory, lambda _ok: None)
                elif now - self._idle_since > 15:
                    # pick a random idle expression
                    expr = random.choice(["wink", "sleepy", "surprised", None])
                    if expr:
                        self._set_state(expr)
                        # return to idle after a short play
                        dur = 2000 if expr == "sleepy" else 1200
                        QTimer.singleShot(dur, lambda: self._set_state("idle"))
                        self._idle_since = now  # don't spam expressions
            QTimer.singleShot(3000, _check)  # check every 3s

        QTimer.singleShot(3000, _check)

    # ── animation ─────────────────────────────────────────────────

    def _set_state(self, state: str):
        if state != self.state:
            self.state = state
            self._anim_idx = 0
        # manage zzz animation timer
        if state == "sleep" and self._zzz_timer is None:
            self._zzz_t = 0.0
            self._tick_zzz()
            self.render_bubbles()   # update mask for zzz area
        elif state != "sleep" and self._zzz_timer is not None:
            self._zzz_timer.stop()
            self._zzz_timer = None
            self.render_bubbles()   # remove zzz area from mask

    def _tick_zzz(self):
        """Refresh the zzz animation at ~15 fps while sleeping."""
        if self.state != "sleep":
            self._zzz_timer = None
            return
        self._zzz_t += 0.067  # ~15 fps increment
        self.update()
        self._zzz_timer = QTimer(self)
        self._zzz_timer.setSingleShot(True)
        self._zzz_timer.timeout.connect(self._tick_zzz)
        self._zzz_timer.start(67)

    # ── munch: squash-and-stretch when a file lands on the slime ───

    def _start_munch(self):
        """Brief squash-and-stretch animation (like swallowing a file)."""
        self._munch_t0 = time.time()
        self._munch_sx = 1.0
        self._munch_sy = 1.0
        self._set_state("excited")
        self._tick_munch()

    def _tick_munch(self):
        DUR = 0.40  # whole animation in 400 ms
        t = time.time() - self._munch_t0

        if t >= DUR:
            # finished — reset and show happy, then back to idle
            self._munch_sx = 1.0
            self._munch_sy = 1.0
            self._set_state("happy")
            QTimer.singleShot(1400, lambda: self._set_state("idle"))
            self.update()
            return

        # Two phases — stretch up, then settle
        if t < 0.22:
            # Phase 1 — stretch up ("mouth opens")
            u = t / 0.22
            sx = 1.0 - 0.10 * math.sin(u * math.pi)    # 1.00 → 0.90 → 1.00
            sy = 1.0 + 0.18 * math.sin(u * math.pi)    # 1.00 → 1.18 → 1.00
        else:
            # Phase 2 — damped settle with a tiny bounce
            u = (t - 0.22) / 0.18
            decay = 1.0 - u
            sx = 1.0 + 0.05 * math.sin(u * math.pi * 3) * decay
            sy = 1.0 - 0.05 * math.sin(u * math.pi * 3) * decay

        self._munch_sx = sx
        self._munch_sy = sy
        self.update()
        QTimer.singleShot(16, self._tick_munch)   # ~60 fps

    def _tick_anim(self):
        seq = sprites.ANIMATIONS.get(self.state, sprites.ANIMATIONS["idle"])
        frame, ms = seq[self._anim_idx % len(seq)]
        if frame == "slime_wink":
            frame = random.choice(("slime_wink", "slime_wink2"))   # random eye, one at a time
        self._cur_frame = frame
        self.update()
        self._anim_idx += 1
        QTimer.singleShot(ms, self._tick_anim)

    def _tick_dots(self):
        self._dots = "." * (len(self._dots) % 3 + 1)
        if self.busy:
            self.render_bubbles()
        QTimer.singleShot(450, self._tick_dots)

    # ── queue + lifecycle ─────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                self.ui_queue.get_nowait()()
        except queue.Empty:
            pass
        QTimer.singleShot(40, self._poll_queue)

    def quit(self):
        self._stop_current()
        self._mic_pulsing = False
        if getattr(self, "_perm_server", None) is not None:
            self._perm_server.stop()
        if getattr(self, "_tray", None) is not None:
            self._tray.hide()
        QApplication.instance().quit()


def main():
    parser = argparse.ArgumentParser(description="Slime desktop companion for opencode")
    parser.add_argument("-m", "--model", default=None,
                        help="opencode model, e.g. opencode/deepseek-v4-flash-free")
    parser.add_argument("-p", "--profile", default="matcha", choices=PROFILES,
                        help="Colour profile for the slime (default: matcha)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # closing to tray must not quit
    comp = Companion(model=args.model, profile=args.profile)
    comp.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
