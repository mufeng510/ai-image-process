"""GUI: registry steps, toggles, validation, preflight error display."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:
    pytest.skip(f"PySide6 import failed: {exc}", allow_module_level=True)

from pathlib import Path

from app.config.schema import default_config
from app.core.pipeline import DEFAULT_STEP_ORDER, build_default_registry
from app.gui.main_window import MainWindow
from app.gui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_registry_contains_new_steps_in_order():
    reg = build_default_registry()
    assert DEFAULT_STEP_ORDER.index("rotate_crop") < DEFAULT_STEP_ORDER.index("hidden_image")
    assert DEFAULT_STEP_ORDER.index("hidden_image") < DEFAULT_STEP_ORDER.index("live_photo")
    assert DEFAULT_STEP_ORDER.index("live_photo") < DEFAULT_STEP_ORDER.index("output_write")
    for sid in ("rotate_crop", "hidden_image", "live_photo"):
        assert reg.get(sid) is not None


def test_main_window_toggles_and_hidden_count(qapp, tmp_path):
    win = MainWindow()
    assert win.chk_rotate is not None and win.chk_hidden is not None and win.chk_live is not None
    assert win.chk_rotate.isChecked() is False
    assert win.chk_hidden.isChecked() is False
    assert win.chk_live.isChecked() is False
    lib = tmp_path / "lib"; lib.mkdir()
    from PIL import Image

    Image.new("RGB", (20, 20), (1, 2, 3)).save(lib / "h.jpg")
    win.hidden_edit.setText(str(lib))
    assert "1" in win.lbl_hidden_count.text()
    win.close()


def test_settings_rotate_validation(qapp):
    cfg = default_config()
    dlg = SettingsDialog(cfg)
    dlg.chk_rotate.setChecked(True)
    dlg.min_angle.setValue(5.0)
    dlg.max_angle.setValue(-5.0)
    with pytest.raises(ValueError):
        dlg._collect_ui_config()
    dlg.close()


def test_settings_hidden_and_live_roundtrip(qapp):
    cfg = default_config()
    dlg = SettingsDialog(cfg)
    dlg.chk_hidden.setChecked(True)
    dlg.hidden_dir.setText("/tmp/lib")
    dlg.hidden_opacity.setValue(0.05)
    dlg.chk_live.setChecked(True)
    out = dlg._collect_ui_config()
    assert out.steps.hidden_image.library_dir == "/tmp/lib"
    assert out.steps.live_photo.enabled is True
    dlg.close()


def test_preflight_error_popup_path(qapp):
    from app.core.models import JobResult

    win = MainWindow()
    res = JobResult(job_id="x", preflight_failed=True, preflight_error="隐藏图片库中的可用图片数量不足。")
    # should not raise; popup is modal - monkeypatch away
    import app.gui.main_window as mw

    orig = mw.QMessageBox.warning
    seen = {}
    mw.QMessageBox.warning = lambda *a, **k: seen.setdefault("called", True)
    try:
        win._on_finished(res)
    finally:
        mw.QMessageBox.warning = orig
    assert seen.get("called") is True
    win.close()
