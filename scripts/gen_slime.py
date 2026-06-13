"""Generate the slime companion's pixel-art sprites (transparent PNG).

Run:  python scripts/gen_slime.py              # all profiles
      python scripts/gen_slime.py -p berry     # single profile

Draws a small Tamagotchi-style slime on a low-res logical grid, then scales
it up with nearest-neighbour so the pixels stay crisp. Output lands in
companion/assets/<profile>/ and is loaded by companion.sprites.

Profiles (same design, different main colour):
    matcha   green     default
    berry    pink
    ocean    blue
    sunset   orange
    midnight purple

Frames per profile (15 total):
    slime_idle_0 / idle_1 / idle_2  - gentle squash/stretch bounce
    slime_blink                      - eyes closed
    slime_wink                       - one eye closed
    slime_talk_0 / talk_1 / talk_2   - mouth open (small / big / mid)
    slime_think / think_1            - concentrated (look up / look up + blink)
    slime_happy / excited            - cheerful (^_^ smile / jump + sparkles)
    slime_surprised                  - big round eyes, small o mouth
    slime_sleepy                     - half-closed eyes, slight droop
    slime_error                      - sweat drop, worried mouth
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

# Logical grid. Kept small on purpose so the result reads as pixel art.
W, H = 40, 34
SCALE = 6  # final sprite ~ 240px

ASSETS = Path(__file__).resolve().parent.parent / "companion" / "assets"

# ── colour profiles ────────────────────────────────────────────────
# Each profile defines its own body palette. Shared colours (eyes, cheeks,
# mouth, sweat, sparkle) are the same across all profiles.

PALETTES = {
    "matcha": {
        "OUTLINE": (34, 86, 54, 255),
        "BODY_DK": (74, 184, 104, 255),
        "BODY":    (108, 214, 132, 255),
        "BODY_LT": (152, 236, 168, 255),
        "SHINE":   (224, 255, 232, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "berry": {
        "OUTLINE": (86, 34, 68, 255),
        "BODY_DK": (184, 74, 140, 255),
        "BODY":    (214, 108, 168, 255),
        "BODY_LT": (236, 152, 196, 255),
        "SHINE":   (255, 224, 244, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "ocean": {
        "OUTLINE": (34, 68, 86, 255),
        "BODY_DK": (74, 140, 184, 255),
        "BODY":    (108, 168, 214, 255),
        "BODY_LT": (152, 196, 236, 255),
        "SHINE":   (224, 236, 255, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "sunset": {
        "OUTLINE": (86, 56, 34, 255),
        "BODY_DK": (184, 112, 74, 255),
        "BODY":    (214, 140, 108, 255),
        "BODY_LT": (236, 168, 152, 255),
        "SHINE":   (255, 232, 224, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "midnight": {
        "OUTLINE": (54, 34, 86, 255),
        "BODY_DK": (122, 74, 184, 255),
        "BODY":    (140, 108, 214, 255),
        "BODY_LT": (168, 152, 236, 255),
        "SHINE":   (232, 224, 255, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "coral": {
        "OUTLINE": (68, 28, 20, 255),
        "BODY_DK": (170, 68, 52, 255),
        "BODY":    (214, 108, 88, 255),
        "BODY_LT": (236, 152, 136, 255),
        "SHINE":   (255, 232, 224, 255),
        "MOUTH":   (130, 48, 52, 255),
    },
    "mint": {
        "OUTLINE": (28, 68, 60, 255),
        "BODY_DK": (68, 170, 152, 255),
        "BODY":    (108, 214, 196, 255),
        "BODY_LT": (152, 236, 224, 255),
        "SHINE":   (224, 255, 248, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "lavender": {
        "OUTLINE": (48, 34, 68, 255),
        "BODY_DK": (108, 74, 170, 255),
        "BODY":    (152, 128, 212, 255),
        "BODY_LT": (188, 168, 236, 255),
        "SHINE":   (240, 232, 255, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "peach": {
        "OUTLINE": (68, 54, 20, 255),
        "BODY_DK": (170, 138, 52, 255),
        "BODY":    (214, 180, 88, 255),
        "BODY_LT": (236, 208, 136, 255),
        "SHINE":   (255, 244, 224, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "rose": {
        "OUTLINE": (68, 28, 40, 255),
        "BODY_DK": (170, 68, 92, 255),
        "BODY":    (214, 108, 136, 255),
        "BODY_LT": (236, 152, 172, 255),
        "SHINE":   (255, 232, 240, 255),
        "MOUTH":   (150, 56, 72, 255),
    },
    "storm": {
        "OUTLINE": (44, 52, 56, 255),
        "BODY_DK": (108, 124, 140, 255),
        "BODY":    (148, 164, 180, 255),
        "BODY_LT": (184, 196, 208, 255),
        "SHINE":   (232, 240, 248, 255),
        "MOUTH":   (180, 92, 96, 255),
    },
    "lava": {
        "OUTLINE": (68, 16, 12, 255),
        "BODY_DK": (170, 36, 28, 255),
        "BODY":    (214, 68, 56, 255),
        "BODY_LT": (236, 120, 108, 255),
        "SHINE":   (255, 224, 220, 255),
        "MOUTH":   (48, 8, 12, 255),
    },
}

# Shared across all profiles — face / effects colours stay the same.
CLEAR     = (0, 0, 0, 0)
EYE       = (38, 54, 46, 255)
EYE_GLINT = (255, 255, 255, 255)
CHEEK     = (255, 158, 170, 235)
SWEAT     = (140, 200, 255, 255)
SPARKLE   = (255, 255, 180, 255)

# Active palette — set by build() before generating frames.
P: dict[str, tuple] = PALETTES["matcha"]


def _blank() -> list[list[tuple]]:
    return [[CLEAR for _ in range(W)] for _ in range(H)]


def _put(grid, x, y, color):
    if 0 <= x < W and 0 <= y < H:
        grid[y][x] = color


# ── body ────────────────────────────────────────────────────────────

def _body_mask(squash: float) -> list[list[bool]]:
    """Return a boolean mask of the slime blob.

    squash > 0 => wider & shorter (bottom of bounce);
    squash < 0 => taller & narrower (top of bounce).
    """
    mask = [[False] * W for _ in range(H)]
    cx = (W - 1) / 2.0
    base_y = H - 3
    rx = (W / 2.0 - 2) * (1.0 + 0.10 * squash)
    ry = (H - 6) * (1.0 - 0.14 * squash)
    for y in range(H):
        for x in range(W):
            if y > base_y:
                continue
            ny = (y - base_y) / ry
            nx = (x - cx) / rx
            if nx * nx + ny * ny <= 1.0:
                mask[y][x] = True
    return mask


def _draw_base(grid, squash: float):
    mask = _body_mask(squash)
    for y in range(H):
        for x in range(W):
            if not mask[y][x]:
                continue
            edge = (
                not mask[y - 1][x] if y > 0 else True
            ) or (
                not mask[y + 1][x] if y < H - 1 else True
            ) or (
                not mask[y][x - 1] if x > 0 else True
            ) or (
                not mask[y][x + 1] if x < W - 1 else True
            )
            if edge:
                grid[y][x] = P["OUTLINE"]
                continue
            top = min(yy for yy in range(H) if mask[yy][x])
            bottom = max(yy for yy in range(H) if mask[yy][x])
            t = (y - top) / max(1, (bottom - top))
            if t < 0.30:
                grid[y][x] = P["BODY_LT"]
            elif t > 0.78:
                grid[y][x] = P["BODY_DK"]
            else:
                grid[y][x] = P["BODY"]
    return mask


def _draw_shine(grid, mask):
    pts = [(13, 8), (14, 8), (12, 9), (13, 9), (14, 9), (13, 10)]
    for x, y in pts:
        if mask[y][x]:
            grid[y][x] = P["SHINE"]


def _draw_cheeks(grid, mask, dy=0):
    for x in (11, 12, 27, 28):
        y = 22 + dy
        if 0 <= y < H and mask[y][x]:
            grid[y][x] = CHEEK


def _shear(grid, lean: float):
    """Lean a composed frame: shift each row horizontally, feet fixed.

    ``lean`` > 0 leans right, < 0 leans left. The shift grows toward the top
    (pivot at the feet), so the whole slime tilts as one discrete pose.
    """
    if not lean:
        return grid
    base_y = H - 3
    out = _blank()
    for y in range(H):
        dx = round(lean * (base_y - y))
        row = grid[y]
        for x in range(W):
            c = row[x]
            if c[3] != 0:
                nx = x + dx
                if 0 <= nx < W:
                    out[y][nx] = c
    return out


# ── eyes ────────────────────────────────────────────────────────────

def _draw_eyes_open(grid, look_up=False):
    dy = -1 if look_up else 0
    for ex in (15, 24):
        for ox in (0, 1):
            for oy in (0, 1, 2):
                _put(grid, ex + ox, 16 + oy + dy, EYE)
        _put(grid, ex, 16 + dy, EYE_GLINT)


def _draw_eyes_closed(grid):
    for ex in (15, 24):
        for ox in (0, 1, 2):
            _put(grid, ex + ox - 1, 18, EYE)


def _draw_eyes_wink(grid):
    # left eye closed (line), right eye open
    for ox in (0, 1, 2):
        _put(grid, 15 + ox - 1, 18, EYE)
    for ox in (0, 1):
        for oy in (0, 1, 2):
            _put(grid, 24 + ox, 16 + oy, EYE)
    _put(grid, 24, 16, EYE_GLINT)


def _draw_eyes_wink_r(grid):
    # mirror of _draw_eyes_wink: right eye closed (line), left eye open
    for ox in (0, 1, 2):
        _put(grid, 24 + ox - 1, 18, EYE)
    for ox in (0, 1):
        for oy in (0, 1, 2):
            _put(grid, 15 + ox, 16 + oy, EYE)
    _put(grid, 15, 16, EYE_GLINT)


def _draw_eyes_happy(grid):
    _put(grid, 15, 16, EYE); _put(grid, 16, 16, EYE)
    _put(grid, 15, 17, EYE); _put(grid, 16, 17, EYE)
    _put(grid, 16, 18, EYE)
    _put(grid, 15, 16, EYE_GLINT)
    _put(grid, 23, 16, EYE); _put(grid, 24, 16, EYE)
    _put(grid, 23, 17, EYE); _put(grid, 24, 17, EYE)
    _put(grid, 23, 18, EYE)
    _put(grid, 23, 16, EYE_GLINT)


def _draw_eyes_surprised(grid):
    for ox in (0, 1, 2):
        for oy in (0, 1, 2):
            _put(grid, 14 + ox, 15 + oy, EYE)
            _put(grid, 23 + ox, 15 + oy, EYE)
    _put(grid, 14, 15, EYE_GLINT); _put(grid, 14, 16, EYE_GLINT)
    _put(grid, 23, 15, EYE_GLINT); _put(grid, 23, 16, EYE_GLINT)


def _draw_eyes_sleepy(grid):
    for ex in (15, 24):
        for ox in (0, 1, 2):
            _put(grid, ex + ox - 1, 17, EYE)


# ── mouths ──────────────────────────────────────────────────────────

def _draw_mouth_smile(grid):
    for x in (19, 20):
        _put(grid, x, 22, P["MOUTH"])
    _put(grid, 18, 21, P["MOUTH"])
    _put(grid, 21, 21, P["MOUTH"])


def _draw_mouth_big_smile(grid):
    _put(grid, 17, 21, P["MOUTH"])
    _put(grid, 18, 22, P["MOUTH"])
    _put(grid, 19, 23, P["MOUTH"]); _put(grid, 20, 23, P["MOUTH"])
    _put(grid, 21, 22, P["MOUTH"])
    _put(grid, 22, 21, P["MOUTH"])


def _draw_mouth_open(grid, big=False):
    h = 3 if big else 2
    for dx in range(4):
        for dy in range(h):
            _put(grid, 18 + dx, 21 + dy, P["MOUTH"])


def _draw_mouth_open_mid(grid):
    for dx in range(3):
        for dy in range(2):
            _put(grid, 18 + dx, 21 + dy, P["MOUTH"])


def _draw_mouth_flat(grid):
    for x in range(18, 22):
        _put(grid, x, 22, P["MOUTH"])


def _draw_mouth_o(grid):
    _put(grid, 18, 21, P["MOUTH"]); _put(grid, 19, 21, P["MOUTH"])
    _put(grid, 20, 21, P["MOUTH"]); _put(grid, 21, 21, P["MOUTH"])
    _put(grid, 18, 22, P["MOUTH"]); _put(grid, 21, 22, P["MOUTH"])
    _put(grid, 19, 23, P["MOUTH"]); _put(grid, 20, 23, P["MOUTH"])


def _draw_mouth_wavy(grid):
    _put(grid, 17, 21, P["MOUTH"])
    _put(grid, 18, 22, P["MOUTH"])
    _put(grid, 19, 21, P["MOUTH"])
    _put(grid, 20, 22, P["MOUTH"])
    _put(grid, 21, 21, P["MOUTH"])
    _put(grid, 22, 22, P["MOUTH"])


# ── effects ─────────────────────────────────────────────────────────

def _draw_sweat(grid, mask):
    drop = [(7, 10), (6, 11), (7, 11), (8, 11),
            (6, 12), (7, 12), (7, 13)]
    for x, y in drop:
        if 0 <= y < H and 0 <= x < W:
            _put(grid, x, y, SWEAT)


def _draw_sparkle(grid, mask):
    _put(grid, 7, 5, SPARKLE)
    _put(grid, 6, 6, SPARKLE); _put(grid, 7, 6, SPARKLE); _put(grid, 8, 6, SPARKLE)
    _put(grid, 7, 7, SPARKLE)
    _put(grid, 31, 4, SPARKLE)
    _put(grid, 30, 5, SPARKLE); _put(grid, 31, 5, SPARKLE); _put(grid, 32, 5, SPARKLE)
    _put(grid, 31, 6, SPARKLE)
    _put(grid, 19, 3, SPARKLE); _put(grid, 20, 3, SPARKLE)
    _put(grid, 18, 4, SPARKLE); _put(grid, 21, 4, SPARKLE)


# ── render ──────────────────────────────────────────────────────────

def _render(grid, name: str, profile: str):
    img = Image.new("RGBA", (W, H), CLEAR)
    px = img.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = grid[y][x]
    img = img.resize((W * SCALE, H * SCALE), Image.NEAREST)
    out_dir = ASSETS / profile
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.png"
    img.save(out)
    print(f"  {profile:8s}  {out.name:20s}  ({img.width}x{img.height})")


# ── build one profile ───────────────────────────────────────────────

def _build_frames(profile: str):
    """Generate all 15 frames for a single colour profile."""
    global P
    P = PALETTES[profile]

    # idle 0
    g = _blank(); m = _draw_base(g, squash=0.0)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_smile(g); _draw_cheeks(g, m)
    _render(g, "slime_idle_0", profile)

    # idle 1 (squashed)
    g = _blank(); m = _draw_base(g, squash=0.85)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_smile(g); _draw_cheeks(g, m, dy=1)
    _render(g, "slime_idle_1", profile)

    # blink
    g = _blank(); m = _draw_base(g, squash=0.0)
    _draw_shine(g, m); _draw_eyes_closed(g); _draw_mouth_smile(g); _draw_cheeks(g, m)
    _render(g, "slime_blink", profile)

    # talk 0 (small mouth)
    g = _blank(); m = _draw_base(g, squash=0.2)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_open(g, big=False); _draw_cheeks(g, m)
    _render(g, "slime_talk_0", profile)

    # talk 1 (big mouth)
    g = _blank(); m = _draw_base(g, squash=0.5)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_open(g, big=True); _draw_cheeks(g, m, dy=1)
    _render(g, "slime_talk_1", profile)

    # think
    g = _blank(); m = _draw_base(g, squash=0.0)
    _draw_shine(g, m); _draw_eyes_open(g, look_up=True); _draw_mouth_flat(g); _draw_cheeks(g, m)
    _render(g, "slime_think", profile)

    # neutral (eyes forward, flat mouth — used for pauses during think/error/sleepy)
    g = _blank(); m = _draw_base(g, squash=0.0)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_flat(g); _draw_cheeks(g, m)
    _render(g, "slime_neutral", profile)

    # idle 2 (stretched up, bounce apex)
    g = _blank(); m = _draw_base(g, squash=-0.5)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_smile(g); _draw_cheeks(g, m, dy=-1)
    _render(g, "slime_idle_2", profile)

    # wink (left eye)
    g = _blank(); m = _draw_base(g, squash=0.0)
    _draw_shine(g, m); _draw_eyes_wink(g); _draw_mouth_smile(g); _draw_cheeks(g, m)
    _render(g, "slime_wink", profile)

    # wink2 (right eye — mirror, so winks alternate eyes)
    g = _blank(); m = _draw_base(g, squash=0.0)
    _draw_shine(g, m); _draw_eyes_wink_r(g); _draw_mouth_smile(g); _draw_cheeks(g, m)
    _render(g, "slime_wink2", profile)

    # happy
    g = _blank(); m = _draw_base(g, squash=0.15)
    _draw_shine(g, m); _draw_eyes_happy(g); _draw_mouth_big_smile(g); _draw_cheeks(g, m, dy=1)
    _render(g, "slime_happy", profile)

    # excited
    g = _blank(); m = _draw_base(g, squash=-0.7)
    _draw_sparkle(g, m); _draw_shine(g, m)
    _draw_eyes_open(g); _draw_mouth_open(g, big=True); _draw_cheeks(g, m, dy=-1)
    _render(g, "slime_excited", profile)

    # surprised
    g = _blank(); m = _draw_base(g, squash=-0.2)
    _draw_shine(g, m); _draw_eyes_surprised(g); _draw_mouth_o(g); _draw_cheeks(g, m)
    _render(g, "slime_surprised", profile)

    # sleepy
    g = _blank(); m = _draw_base(g, squash=0.3)
    _draw_shine(g, m); _draw_eyes_sleepy(g); _draw_mouth_flat(g); _draw_cheeks(g, m, dy=1)
    _render(g, "slime_sleepy", profile)

    # talk 2 (mid mouth)
    g = _blank(); m = _draw_base(g, squash=0.35)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_open_mid(g); _draw_cheeks(g, m)
    _render(g, "slime_talk_2", profile)

    # think 1 (think + blink)
    g = _blank(); m = _draw_base(g, squash=0.0)
    _draw_shine(g, m); _draw_eyes_closed(g); _draw_mouth_flat(g); _draw_cheeks(g, m)
    _render(g, "slime_think_1", profile)

    # error
    g = _blank(); m = _draw_base(g, squash=0.25)
    _draw_shine(g, m); _draw_eyes_open(g, look_up=True)
    _draw_sweat(g, m); _draw_mouth_wavy(g); _draw_cheeks(g, m)
    _render(g, "slime_error", profile)

    # ── wiggle poses (discrete lean frames for think/talk) ──────────
    # think leaning left / right
    g = _blank(); m = _draw_base(g, squash=0.08)
    _draw_shine(g, m); _draw_eyes_open(g, look_up=True); _draw_mouth_flat(g); _draw_cheeks(g, m)
    _render(_shear(g, -0.20), "slime_think_l", profile)

    g = _blank(); m = _draw_base(g, squash=0.08)
    _draw_shine(g, m); _draw_eyes_open(g, look_up=True); _draw_mouth_flat(g); _draw_cheeks(g, m)
    _render(_shear(g, 0.20), "slime_think_r", profile)

    # talk leaning left / right (mid-open mouth)
    g = _blank(); m = _draw_base(g, squash=0.4)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_open_mid(g); _draw_cheeks(g, m)
    _render(_shear(g, -0.20), "slime_talk_l", profile)

    g = _blank(); m = _draw_base(g, squash=0.4)
    _draw_shine(g, m); _draw_eyes_open(g); _draw_mouth_open_mid(g); _draw_cheeks(g, m)
    _render(_shear(g, 0.20), "slime_talk_r", profile)


# ── build ───────────────────────────────────────────────────────────

def build(profile: str | None = None):
    if profile:
        profiles = [profile]
    else:
        profiles = list(PALETTES.keys())

    total = len(profiles) * 21
    print(f"Generating slime sprites ({len(profiles)} profiles, {total} frames)...\n")

    for name in profiles:
        print(f"  [{name}]")
        _build_frames(name)

    print(f"\nDone.  {total} frames in {len(profiles)} profiles.")


# ── cli ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate slime pixel-art sprites")
    parser.add_argument(
        "-p", "--profile",
        choices=list(PALETTES.keys()),
        default=None,
        help="Single profile to generate (default: all)",
    )
    args = parser.parse_args()
    build(args.profile)
