"""Test-session bootstrap for Qt/OpenCV import order.

cv2 and Qt can coexist, but only if cv2 is imported *before* QApplication is
constructed, so preloading here keeps that order deterministic across the
whole session (mirrors app/gui/app.py:_preload_opencv, which protects the
real application).

Measured on Linux/Python 3.13/PySide6 6.11.2 (2026-10): the application path
exits cleanly (0/20 runs). The *test* process still segfaults during
interpreter shutdown in roughly 20-40% of runs after printing a complete
passing summary, and that flake is independent of this preload — it reproduces
with remove-ai-watermarks/cv2 unimportable as well, so it is a Qt teardown
issue in this environment rather than an import-order one. When you see it,
check the summary line before assuming a real failure.

Both imports are optional: CI and source checkouts without the [visible] extra
simply skip them.
"""
try:  # pragma: no cover - environment dependent
    import cv2  # noqa: F401
except Exception:  # noqa: BLE001
    pass
try:  # pragma: no cover - environment dependent
    import remove_ai_watermarks  # noqa: F401
except Exception:  # noqa: BLE001
    pass
