"""GUI application bootstrap."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.version import __version__


def run_gui(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    app = QApplication(args)
    app.setApplicationName("AI Image Process")
    app.setApplicationVersion(__version__)
    win = MainWindow()
    win.show()
    return app.exec()
