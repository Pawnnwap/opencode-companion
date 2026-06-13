# Profile

Static identity seed. Goo builds the rest from your chats (recent → facts →
reflection). Prime the **User** section below if you like, or just start talking.

## Project

**opencode-companion** — a desktop pet (slime "Goo") that wraps the [opencode](https://opencode.ai) CLI.
- Floating, frameless PySide6 (Qt) window with a pixel-art slime companion.
- Voice input via push-to-talk + offline STT (Paraformer-zh, sherpa-onnx).
- Chat bubbles with scroll history.
- opencode session management: list, switch, multi-session dispatch.
- Shorthand commands: `ls` (list), `2` (switch), `1,3: <cmd>` (dispatch), `new: <cmd>` (create).

**Tech stack**
- Python 3.9+, PySide6 (Qt), Pillow (sprite generation only).
- opencode CLI (subprocess).

## User

- **Name**: _(unset — tell Goo who you are)_
- **Preferences**: _(unset)_

## opencode settings

- **Model**: opencode default (override with `-m` / `--model`).
- **Agent**: `slime` (this persona).
- Run via: `opencode run [--session <id>] [--agent slime] <message>`.
