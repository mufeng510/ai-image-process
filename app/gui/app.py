"""GUI application bootstrap."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.gui.icons import get_app_icon
from app.gui.main_window import MainWindow
from app.version import __version__


def _preload_opencv() -> None:
    """Load the optional native dependencies before any Qt object exists.

    Import order alone decides a hard crash here: when cv2 (or the optional
    remove-ai-watermarks package that wraps it) is first pulled in *after*
    QApplication exists — which happens as soon as the settings dialog asks
    about dependency status — the interpreter can segfault during shutdown.
    Reproduced on Linux with remove-ai-watermarks 0.46.0 + opencv 5.0 +
    PySide6 6.11.x (exit 139). Loading them first makes the same session exit
    cleanly. Both imports are best-effort: neither is required to start.
    """
    for module in ("cv2", "remove_ai_watermarks"):
        try:
            __import__(module)
        except Exception:  # noqa: BLE001
            pass


def run_gui(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    _preload_opencv()
    app = QApplication(args)
    app.setApplicationName("AI Image Process")
    app.setApplicationVersion(__version__)
    icon = get_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    win = MainWindow()
    win.show()
    return app.exec()
