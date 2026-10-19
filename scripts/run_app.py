#!/usr/bin/env python3
"""Packaged entry point with two personalities: one bundle, two executables.

PyInstaller compiles exactly one entry script per Analysis and hands the same
`a.scripts` list to every EXE that COLLECT bundles, so two EXEs cannot boot
different code. Both therefore launch this dispatcher, which picks a
personality from the executable name:

    AI-Image-Process       -> GUI   (console=False, double-click friendly)
    AI-Image-Process-CLI   -> CLI   (console=True, so a parent shell on
                                       Windows can capture stdout at all)

Sharing one bundle is the point: a second Analysis + COLLECT would duplicate
every dependency plus the bundled ExifTool and FFmpeg (~600 MB) to buy a
decision argv[0] can make for free.

Set AI_IMAGE_PROCESS_ENTRY=cli|gui to force a personality when running from
source, where the script name says neither.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repo root importability when running from source
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wants_cli() -> bool:
    forced = os.environ.get("AI_IMAGE_PROCESS_ENTRY", "").strip().lower()
    if forced in {"cli", "gui"}:
        return forced == "cli"
    # "AI-Image-Process-CLI" -> cli. The GUI name has to stay free of the
    # substring, hence the sibling is spelled with a dash on both sides.
    return "cli" in Path(sys.argv[0]).name.lower()


def main() -> int:
    if _wants_cli():
        from app.main_cli import main as cli_main

        return cli_main(sys.argv[1:])
    from app.gui.app import run_gui

    return run_gui(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())