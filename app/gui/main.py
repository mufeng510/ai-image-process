"""Alternative application entrypoint (`python -m app.gui.main`).

Kept as a thin forwarder to `run_gui()` on purpose: it used to build its own
QApplication, which skipped the cv2 preload in `app.gui.app` and reproduced the
segfault-at-exit crash whenever the settings dialog loaded OpenCV.
"""
from __future__ import annotations

import sys

from app.gui.app import run_gui


def main() -> int:
    return run_gui(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
