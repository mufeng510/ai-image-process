"""GUI module structural checks without requiring display libs."""
from __future__ import annotations

import ast
from pathlib import Path


def test_gui_modules_parse():
    root = Path("app/gui")
    files = sorted(root.rglob("*.py"))
    assert files
    for py in files:
        ast.parse(py.read_text(encoding="utf-8"), filename=str(py))


def test_main_window_defines_expected_symbols():
    tree = ast.parse(Path("app/gui/main_window.py").read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert "MainWindow" in names
