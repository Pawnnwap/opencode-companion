"""Load the slime's pixel-art frames as Qt pixmaps and define its animations.

Qt's QPixmap reads PNG with its alpha channel intact, so the slime composites
with true per-pixel transparency against the desktop — no colour-key hack, clean
edges on every monitor.

Colour profiles live in companion/assets/<profile>/. Pass the profile name to
``load_pixmaps()`` to switch the slime's colour.
"""

from __future__ import annotations

from PySide6.QtGui import QPixmap

from ._paths import res_root

ASSETS = res_root() / "companion" / "assets"

FRAME_NAMES = [
    # base idle + bounce
    "slime_idle_0", "slime_idle_1", "slime_idle_2",
    # eyes
    "slime_blink", "slime_wink", "slime_wink2",
    # talk (lip-sync: small / mid / big) + lean poses
    "slime_talk_0", "slime_talk_1", "slime_talk_2",
    "slime_talk_l", "slime_talk_r",
    # think + neutral pause + lean poses
    "slime_think", "slime_think_1", "slime_neutral",
    "slime_think_l", "slime_think_r",
    # emotions
    "slime_happy", "slime_excited",
    "slime_surprised", "slime_sleepy",
    "slime_error",
]

DEFAULT_PROFILE = "matcha"

# (frame, milliseconds) sequences, looped by the animator.
ANIMATIONS = {
    # ── idle: gentle bounce arc with occasional blink/wink ─────
    "idle": [
        ("slime_idle_0", 1400),
        ("slime_idle_2", 200),      # stretch up (bounce apex)
        ("slime_idle_0", 800),
        ("slime_idle_1", 200),      # squash down (bounce bottom)
        ("slime_idle_0", 2000),
        ("slime_blink", 140),
        ("slime_idle_0", 600),
        ("slime_idle_2", 180),      # mini bounce
        ("slime_idle_0", 1000),
        ("slime_wink", 160),        # cheeky wink
        ("slime_idle_0", 1200),
        ("slime_idle_1", 200),      # another bounce
        ("slime_idle_0", 1800),
        ("slime_blink", 140),
        ("slime_idle_0", 800),
    ],

    # ── think: concentrated look-up, leaning side to side (discrete wiggle) ─
    "think": [
        ("slime_think", 380),
        ("slime_think_l", 320),     # lean left
        ("slime_think", 360),
        ("slime_think_r", 320),     # lean right
        ("slime_think_1", 180),     # flat-mouth blink
        ("slime_think_l", 320),
        ("slime_think", 340),
        ("slime_think_r", 320),
        ("slime_neutral", 320),     # brief upright pause
        ("slime_think", 360),
    ],

    # ── talk: lip-sync mouth + side-to-side lean (discrete wiggle) ─
    "talk": [
        ("slime_talk_0", 130),      # small mouth, upright
        ("slime_talk_l", 140),      # mid mouth, lean left
        ("slime_talk_1", 130),      # big mouth, upright
        ("slime_talk_r", 140),      # mid mouth, lean right
        ("slime_talk_2", 120),      # mid mouth, upright
        ("slime_talk_l", 140),      # lean left
        ("slime_talk_0", 130),
        ("slime_talk_r", 140),      # lean right
        ("slime_blink", 110),       # quick blink
    ],

    # ── happy: ^_^ smile, occasional excited jump ──────────────
    "happy": [
        ("slime_happy", 700),
        ("slime_excited", 250),     # little jump with sparkles
        ("slime_happy", 500),
        ("slime_excited", 250),
        ("slime_happy", 900),
        ("slime_blink", 140),
        ("slime_happy", 600),
        ("slime_idle_2", 200),
        ("slime_happy", 800),
    ],

    # ── surprised: big round eyes, occasional blinks ───────────
    "surprised": [
        ("slime_surprised", 1000),
        ("slime_think_1", 160),
        ("slime_surprised", 700),
        ("slime_think_1", 160),
        ("slime_surprised", 800),
        ("slime_surprised", 600),
        ("slime_think_1", 160),
        ("slime_surprised", 600),
    ],

    # ── sleepy: droopy eyes, slow blinks, flat neutral pause ────
    "sleepy": [
        ("slime_sleepy", 2200),
        ("slime_think_1", 260),     # slow flat-mouth blink
        ("slime_sleepy", 1800),
        ("slime_think_1", 260),     # slow flat-mouth blink
        ("slime_sleepy", 2000),
        ("slime_neutral", 600),     # flat pause (no smile when sleepy)
        ("slime_sleepy", 2400),
    ],

    # ── sleep: deep sleep (sleepy loop + zzz drawn by QPainter) ──
    "sleep": [
        ("slime_sleepy", 3000),
        ("slime_think_1", 300),     # slow blink
        ("slime_sleepy", 4000),
        ("slime_think_1", 300),
        ("slime_sleepy", 3500),
    ],

    # ── error: sweat drop, worried mouth, neutral pauses ────────
    "error": [
        ("slime_error", 800),
        ("slime_neutral", 350),     # flat pause (no smile during error)
        ("slime_error", 900),
        ("slime_think_1", 160),     # flat-mouth blink
        ("slime_error", 700),
        ("slime_error", 600),
        ("slime_neutral", 400),
        ("slime_error", 800),
    ],
}


def load_pixmaps(profile: str = DEFAULT_PROFILE) -> dict[str, QPixmap]:
    """Load every frame for a colour profile.

    Requires a QGuiApplication to already exist. Falls back to the default
    profile if the requested one has no sprites, and to slime_idle_0 for any
    missing frame.
    """
    def _load_from(p: str) -> dict[str, QPixmap] | None:
        asset_dir = ASSETS / p
        images: dict[str, QPixmap] = {}
        for name in FRAME_NAMES:
            path = asset_dir / f"{name}.png"
            if path.exists():
                pm = QPixmap(str(path))
                if not pm.isNull():
                    images[name] = pm
        if "slime_idle_0" not in images:
            return None
        for name in FRAME_NAMES:
            images.setdefault(name, images["slime_idle_0"])
        return images

    images = _load_from(profile)
    if images is None and profile != DEFAULT_PROFILE:
        # fall back to default profile
        images = _load_from(DEFAULT_PROFILE)
    if images is None:
        raise FileNotFoundError(
            f"No slime sprites in {ASSETS / DEFAULT_PROFILE}. "
            f"Run: python scripts/gen_slime.py"
        )
    return images
