"""Throwaway: construct the desktop UI, render bubbles, screenshot, exit."""
import sys

from PySide6.QtWidgets import QApplication

import companion.desktop as d

app = QApplication(sys.argv)
win = d.Companion()
win.core.history = [
    {"role": "slime", "text": "hi! i'm Goo, your slime. *wobble*"},
    {"role": "user", "text": "ls"},
    {"role": "slime", "text": "opencode sessions:\n  1. Greeting in 3 words\nReply `2`, `1,3: <cmd>`, or `all: <cmd>`."},
    {"role": "user", "text": "1: run the tests and fix any failures you find"},
    {"role": "slime", "text": "Ran the suite — all 14 tests green. *wobble* Nothing to fix."},
]
win._set_status("ready")
win._show_input()
win.entry.setText("type here…")
win.show()
app.processEvents()
win.render_bubbles()
app.processEvents()

out = "scripts/_smoke_ui.png"
win.grab().save(out)
print("saved", out, win.width(), "x", win.height())
app.quit()
