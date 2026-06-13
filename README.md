# opencode-companion

A pixel-art slime desktop companion that drives [opencode](https://opencode.ai) by voice or text.

The slime ("Goo") sits on your desktop as a frameless, always-on-top, per-pixel-transparent Qt (PySide6) window with a system-tray icon. You talk to it via a text input or push-to-talk microphone, and it routes your commands to opencode sessions in the background.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.9+ and a working [opencode](https://opencode.ai) CLI in your `PATH`.

### Optional: voice (STT)

For microphone input, install the extra speech-to-text dependencies:

```bash
pip install sounddevice sherpa-onnx
```

On first use the engine downloads a small Paraformer-zh model automatically.

## Usage

### Desktop companion (default)

```bash
companion
# or
python -m companion.desktop
```

A tiny slime appears on your screen. Interactions:

- **Click the slime** -- toggle the text input box
- **Type + Enter** -- send a message to the active opencode session (or start a new one)
- **Type `/`** -- dropdown of built-in commands **and** installed opencode agents/skills
- **Drag the slime** -- move it around your screen
- **Right-drag the slime** (or **wheel over the slime**) -- resize the companion
- **Click the camera button** -- screenshot your screen (the pet hides itself) and attach it to your next message; the agent sees it via `opencode run --file`
- **Click the mic button** (or use `mic` in the CLI) -- push-to-talk, record + transcribe + send
- **Wheel over the chat** -- scroll back through history (a thin scrollbar appears on hover)
- **BUILD / PLAN pill** (top-left) -- toggle modes; **PLAN** runs opencode's read-only agent and blocks every mutating tool (see *Safety* below)
- **☰ button** -- open the session list: click a session to view its transcript, then type to run a prompt on it via the CLI. A green dot marks a session with a run in flight, blue marks the open one. Pick **↩ Goo (chat)** to return to the companion chat.
- **System tray icon** -- left-click to show/hide, right-click to quit
- **x button** -- quit

While the agent works, the bubble shows the live step (e.g. `running command: npm test`) and how long it's been on it, so you can tell what's happening and whether it's stuck.

### Text-mode REPL (headless)

```bash
companion-cli
# or
python -m companion.main
```

A simple terminal chat that shares the same brain (`Core`) as the desktop pet.

## Safety: permission prompts & plan mode

The agent never silently changes your files. Before any **mutating** tool runs
(file edits — including the hashline MCP edit path — and `bash`), a small opencode
plugin asks the companion and you get an **Allow / Always / Deny** bubble. Allow
proceeds, Deny surfaces as a tool error the agent handles (flow continues). Reads
and searches are auto-allowed. The plugin (`companion/opencode_plugin/`) installs
into opencode's plugin dir and is inert unless launched by the companion.

The **PLAN** pill is a hard "make no changes" guarantee: it runs opencode's
read-only `plan` agent **and** tells the bridge to auto-deny every mutating tool.

By default, casual chat runs in a sandbox dir (`<project>/temp`) so it can't touch
real files; sessions opened from the list run in their own directories.

## Memory

Goo has a tiered memory inspired by **[Project N.E.K.O](https://github.com/Project-N-E-K-O/N.E.K.O)**:

- **recent** (近期) — short-term rolling exchanges
- **facts** (事实) — durable facts about you and the project
- **reflection** (反思) — higher-level insights and preferences
- **profile** (人格) — static identity
- **per-session task** — each session's goal + latest progress, for quick resume

On idle, opencode itself consolidates *recent* into *facts*/*reflection* ("the
more you chat, the more it knows you"). All live memory is per-user runtime state
under `~/.config/opencode/agent/slime/` — it never enters the repo.

## Shorthand

Both the desktop UI and the CLI accept these shortcuts:

| Command | Meaning |
|---|---|
| `ls` | List opencode sessions |
| `2` | Make session #2 active (plain talk goes there) |
| `1,3: <cmd>` | Run `<cmd>` on sessions #1 and #3 |
| `1-3: <cmd>` | Run on sessions #1 through #3 |
| `all: <cmd>` | Run on every listed session |
| `new: <cmd>` | Start a brand-new session |
| `<anything else>` | Goes to the active session, or starts a new one |

## Options

| Flag | Description |
|---|---|
| `-m`, `--model` | opencode model id (e.g. `opencode/deepseek-v4-flash-free`) |

## Portable Windows build

Build a self-contained portable folder (bundles PySide6, the STT model, and
sherpa-onnx — no Python needed to run it):

```bash
pip install -e ".[build]"
python scripts/build_exe.py        # or: pyinstaller opencode-companion.spec
```

Output: the **`dist/Goo/`** folder — `Goo.exe` plus `_internal/` (Qt, the
sprites, the persona/memory seeds under `agents/`, and the STT model under
`stt/models/`). Zip the folder to move it between machines; run `Goo.exe`.

On first run it installs Goo's agent + memory into `~/.config/opencode/agent/slime/`
(`slime.md`, `profile.md`, `task_current.md`, …) — those build up as you chat.

Notes:
- It still calls the external **`opencode` CLI**, which must be on the user's
  `PATH` — that can't be bundled.
- Size is ~**400 MB**, of which the bundled Paraformer STT model is ~230 MB. The
  spec ships only the Qt modules actually used (QtCore/QtGui/QtWidgets) — WebEngine,
  Quick/QML, the software-OpenGL fallback and ffmpeg codecs are stripped out. The
  pet paints with QPainter (raster), so it relies on your system's OpenGL; very old
  or headless boxes without it may need that software fallback restored.
- The spec is a **onedir** build (visible, editable structure, fast startup). For
  a single-file `.exe` instead, change `EXE(... exclude_binaries=True)` + `COLLECT`
  back to a onefile `EXE` — smaller to share but slower to launch.

## Regenerating sprites

The pixel-art frames live in `companion/assets/`. To regenerate them (requires `pillow`):

```bash
python scripts/gen_slime.py
```

## Project layout

```
opencode-companion/
  companion/
    __init__.py
    core.py            # Brain: routes input to opencode sessions
    opencode.py        # Subprocess wrapper around the opencode CLI
    desktop.py         # PySide6 (Qt) desktop pet UI
    main.py            # Headless text REPL
    persona.py         # Installs the slime agent into opencode
    memory.py          # Tiered memory (recent/facts/reflection/tasks)
    permits.py         # Permission bridge server (consent prompts)
    voice.py           # Mic capture + transcription
    sprites.py         # Loads PNG frames and animation sequences
    theme.py           # Palette / sizing constants
    opencode_plugin/   # opencode plugin that gates mutating tools
    assets/            # Pixel-art PNGs (idle, blink, talk, wink, …)
  stt/
    __init__.py        # Offline Chinese STT (Paraformer-zh via sherpa-onnx)
    _engine.py
    _download.py       # Auto-downloads the ONNX model
    models/
  agents/
    slime.md           # Goo's personality (opencode agent definition)
    memory/profile.md  # Static identity seed (other memory is runtime-only)
  scripts/
    gen_slime.py       # Sprite generator (pillow)
    _smoke_ui.py       # UI smoke test / screenshot
  pyproject.toml
```

## Acknowledgements

This project stands on excellent open source:

- **[opencode](https://opencode.ai)** — the coding agent CLI this companion drives, plus its agent / plugin / MCP system.
- **[Qt for Python — PySide6](https://doc.qt.io/qtforpython/)** (LGPL) — the renderer: frameless per-pixel-alpha window, tray icon, painting.
- **[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)** + **Paraformer-zh** (k2-fsa / FunASR) — offline speech-to-text.
- **[Pillow](https://python-pillow.org/)** — generates the pixel-art sprites.
- **NumPy**, **soundfile**, **sounddevice** — audio capture/IO.
- **[Project N.E.K.O](https://github.com/Project-N-E-K-O/N.E.K.O)** — the five-dimensional memory design (working / recent / facts / reflection / persona) that inspired Goo's tiered memory.
- **[Open agent skills](https://skills.sh) ecosystem** (`npx skills`) — the `SKILL.md` skills surfaced in the `/` dropdown.

Thanks to all of the above and their authors. ♥

## License

See the repository for license details.
