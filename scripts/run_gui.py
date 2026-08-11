#!/usr/bin/env python3
"""GUI entry used by PyInstaller and developers."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root importability when running from source
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.gui.app import run_gui


if __name__ == "__main__":
    raise SystemExit(run_gui())
