import ast
from pathlib import Path


def test_core_does_not_import_gui():
    root = Path("app/core")
    offenders = []
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name.startswith("app.gui") or n.name.split(".")[0] in {"PySide6", "PyQt6"}:
                        offenders.append((py, n.name))
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("app.gui") or mod.split(".")[0] in {"PySide6", "PyQt6"}:
                    offenders.append((py, mod))
    assert offenders == []
