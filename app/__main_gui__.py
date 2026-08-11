"""Frozen/GUI-focused module entry helper.

Prefer: python -m app gui
Frozen bootloader may call app.gui.app:run_gui directly.
"""
from app.gui.app import run_gui

if __name__ == "__main__":
    raise SystemExit(run_gui())
