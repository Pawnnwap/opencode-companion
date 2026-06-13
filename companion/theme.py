"""Palette, dimensions and other look-and-feel constants for the desktop pet.

Kept separate from ``desktop.py`` so the renderer holds behaviour and this holds
data — change a colour or size here without touching widget logic.
"""

from __future__ import annotations

# ── palette ───────────────────────────────────────────────────────
PANEL = "#1b2330"
PANEL_BORDER = "#3a5a7e"
USER_BG = "#3a7afe"
USER_FG = "#ffffff"
SLIME_BG = "#eafff0"
SLIME_FG = "#123322"
DIM = "#aebfd0"
ERR_BG = "#3a2030"
ERR_FG = "#ffd7df"
WHITE = "#ffffff"
ENTRY_FG = "#e6edf3"
PENDING_FG = "#5a7a66"   # slime's "…" while thinking

# ── mic button (bright green circle that pops on any background) ───
MIC_BG = "#5fcf80"            # primary fill
MIC_BG_HOVER = "#7ee09c"      # lighter on hover
MIC_BG_RECORDING = "#e04040"  # recording state (red)
MIC_BG_RECORDING_ALT = "#c02828"  # pulse alternate (darker red)
MIC_BORDER = "#e0ffe8"        # pale-green ring for contrast
MIC_BORDER_RECORDING = "#ffe0e0"  # pale-red ring during recording
MIC_R = 22                     # radius of the circle button (at scale 1.0)
MIC_FG = "#ffffff"             # mic glyph colour (pops on green and red fills)

# Pixel-art microphone, drawn cell-by-cell so it stays crisp at any scale.
# '#' = filled, ' ' = transparent. Capsule head + grille + stem + base.
MIC_PIXELS = [
    " ##### ",
    "#######",
    "## # ##",
    "#######",
    "## # ##",
    "#######",
    "## # ##",
    " ##### ",
    "  ###  ",
    "   #   ",
    "   #   ",
    " ##### ",
]

# ── camera button (screenshot → attach to next message) ──────────
CAM_BG = "#3a7afe"            # blue circle, sits left of the mic
CAM_BG_HOVER = "#5a92ff"
CAM_BG_ARMED = "#f0b429"      # amber once a screenshot is staged
CAM_BORDER = "#dbe8ff"
CAM_BORDER_ARMED = "#fff0c2"
CAM_FG = "#ffffff"            # glyph colour

# Pixel-art camera: viewfinder hump, body, ring lens. '#' filled, ' ' transparent.
CAM_PIXELS = [
    "   ##    ",
    " ####### ",
    "#########",
    "## ### ##",
    "## # # ##",
    "## ### ##",
    "#########",
]

# ── session panel ─────────────────────────────────────────────────
PANEL_FILL = (27, 35, 48, 238)   # near-opaque PANEL for the list overlay (RGBA)
ROW_ACTIVE = (58, 90, 126, 90)   # highlight behind the open session's row (RGBA)
ROW_FG = ENTRY_FG
DOT_RUNNING = "#3fd07a"          # green: a run is in flight on this session
DOT_ACTIVE = USER_BG             # blue: the currently open session
DOT_IDLE = DIM                   # grey: idle session

# ── geometry / sizing ─────────────────────────────────────────────
# Base window size (at scale 1.0). Everything else derives from these and the
# current scale, so the whole companion grows/shrinks together.
BASE_W, BASE_H = 380, 600

# Resize limits + steps.
SCALE_MIN, SCALE_MAX = 0.6, 2.5
SCALE_WHEEL_STEP = 0.1     # per wheel notch over the slime
SCALE_DRAG_GAIN = 0.005    # scale change per pixel of right-drag

# ── colour profiles (slime sprite sets under companion/assets/) ───
PROFILES = [
    "matcha", "berry", "ocean", "sunset", "midnight", "coral",
    "mint", "lavender", "peach", "rose", "storm", "lava",
]
DEFAULT_PROFILE = "matcha"
