# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — portable single-file Windows build of the slime companion.

Build:  pyinstaller opencode-companion.spec
Output: dist/Goo.exe  (self-contained; STT model + sherpa-onnx bundled)

Note: the app still shells out to the external `opencode` CLI, which must be on
the user's PATH — that is not (and cannot be) bundled here.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

# ── bundled data (read-only resources) ────────────────────────────
datas = [
    ("companion/assets", "companion/assets"),                # sprites
    ("companion/opencode_plugin", "companion/opencode_plugin"),  # permission plugin
    ("agents/slime.md", "agents"),                           # persona source
    ("agents/memory/profile.md", "agents/memory"),           # memory seed
    ("stt/models", "stt/models"),                            # Paraformer model + tokens
]
binaries = []
hiddenimports = collect_submodules("companion") + collect_submodules("stt")

# native libs + data for packages PyInstaller can't fully trace on its own.
# PySide6 is deliberately omitted: collect_all() force-bundles ALL of Qt (WebEngine,
# Quick, 3D … ~400 MB unused) and those binaries slip past `excludes`. The stock
# PySide6 hook pulls only the imported modules (QtCore/QtGui/QtWidgets) + plugins.
for pkg in ("sherpa_onnx", "soundfile", "sounddevice", "numpy"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run_companion.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib",
        # Qt modules we never import (only QtCore/QtGui/QtWidgets are used)
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQmlModels",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtDesigner", "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtPositioning", "PySide6.QtBluetooth", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        # heavy deps nothing we ship actually imports (verified: STT path is pure C++)
        "numba", "llvmlite", "scipy", "PIL", "Pillow",
        # pywin32 GUI/IDE bits (we only use stdlib subprocess)
        "Pythonwin", "win32ui", "win32uiole",
    ],
    noarchive=False,
)

# Prune heavy DLLs a raster QtWidgets app never loads: the software-OpenGL fallback
# and Qt Multimedia's bundled ffmpeg codecs. Our UI paints via QPainter (raster),
# no QML/video. Also drop any WebEngine resource blobs that slipped through.
_DROP_BIN = ("opengl32sw.dll", "avcodec-", "avformat-", "avutil-", "swscale-", "swresample-")
a.binaries = [b for b in a.binaries if not any(x in b[0].lower() for x in _DROP_BIN)]
a.datas = [d for d in a.datas if "qtwebengine" not in d[0].lower()]

pyz = PYZ(a.pure)

# onedir: a self-contained, portable FOLDER (dist/Goo/) with a visible structure
# and editable bundled files (agents/, stt/models, sprites) — faster startup than
# onefile and lets the user inspect/edit memory seeds.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Goo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,            # windowed (no console)
    icon="build/goo.ico" if __import__("os").path.exists("build/goo.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Goo",
)
