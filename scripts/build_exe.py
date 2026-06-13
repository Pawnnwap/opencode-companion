"""Build a portable Windows .exe of the slime companion (PyInstaller).

    python scripts/build_exe.py

Produces dist/Goo.exe — self-contained, with the STT model + sherpa-onnx bundled.
The external `opencode` CLI must still be on the user's PATH at runtime.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "build" / "goo.ico"
SPRITE = ROOT / "companion" / "assets" / "matcha" / "slime_idle_0.png"


def make_icon():
    """Render a multi-size .ico from the matcha idle sprite (best-effort)."""
    try:
        from PIL import Image
    except ImportError:
        print("  (Pillow not installed — skipping icon, exe uses default)")
        return
    if not SPRITE.exists():
        print("  (sprite missing — skipping icon)")
        return
    ICON.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(SPRITE).convert("RGBA")
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    canvas.save(ICON, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"  icon -> {ICON}")


def main():
    print("Generating icon...")
    make_icon()
    print("Running PyInstaller (this takes a few minutes; the STT model is ~240 MB)...")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "opencode-companion.spec"]
    raise SystemExit(subprocess.call(cmd, cwd=str(ROOT)))


if __name__ == "__main__":
    main()
