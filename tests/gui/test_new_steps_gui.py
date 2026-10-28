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


def _isolated_config(monkeypatch, tmp_path):
    """Point MainWindow at a throwaway config so tests never touch/read the
    user's real config file (which may enable any steps)."""
    import app.gui.main_window as mw
    from app.config.manager import ConfigManager

    monkeypatch.setattr(
        mw, "ConfigManager",
        lambda *a, **k: ConfigManager(tmp_path / "test-config.json"),
    )


def test_main_window_toggles_and_hidden_count(qapp, tmp_path, monkeypatch):
    _isolated_config(monkeypatch, tmp_path)
    win = MainWindow()
    assert win.chk_rotate is not None and win.chk_hidden is not None and win.chk_live is not None
    assert win.chk_rotate.isChecked() is False
    assert win.chk_hidden.isChecked() is False
    assert win.chk_live.isChecked() is False
    lib = tmp_path / "lib"; lib.mkdir()
    from PIL import Image

    Image.new("RGB", (20, 20), (1, 2, 3)).save(lib / "h.jpg")
    win.hidden_edit.setText(str(lib))
    # 扫描在后台 daemon 线程进行，等待它完成；结果由 QTimer 回填 UI，
    # 但断言不依赖 QTimer 时序，直接检查后台扫描结果。
    from PySide6.QtWidgets import QApplication
    import time

    app = QApplication.instance()
    deadline = time.time() + 10
    while time.time() < deadline:
        app.processEvents()
        if win._scan_done:
            break
        time.sleep(0.02)
    assert win._scan_done, "后台扫描未在超时前完成"
    scan_id, result = win._scan_result or (None, None)
    assert result is not None and isinstance(result, list), f"扫描结果异常：{result!r}"
    usable = [e for e in result if e.usable]
    assert len(usable) == 1, f"期望 1 张可用图片，实际 {len(usable)} 张"
    # 直接驱动 GUI 线程回调回填 UI，不依赖 QTimer 定时触发
    win._on_scan_timer()
    assert "1" in win.lbl_hidden_count.text() and "扫描中" not in win.lbl_hidden_count.text()
    win.close()
    # 显式等待后台扫描线程结束，避免 pytest 退出时 daemon 线程导致
    # PySide6 teardown 崩溃（CI runner 上尤为明显）。
    if win._scan_thread is not None:
        win._scan_thread.join(timeout=2)


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


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def _capture_box(monkeypatch, mw):
    """Record the import dialog's text instead of showing it."""
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        seen["info"] = self.informativeText()
        seen["detail"] = self.detailedText()
        return mw.QMessageBox.StandardButton.Ok

    monkeypatch.setattr(mw.QMessageBox, "exec", fake_exec)
    return seen


def test_iphone_import_shows_guidance_and_writes_nothing(qapp, tmp_path, monkeypatch):
    """The button is a hint: it shows the steps and leaves the disk untouched."""
    _isolated_config(monkeypatch, tmp_path)
    import app.gui.main_window as mw
    from PIL import Image

    out = tmp_path / "exports" / "20261018-010101"
    out.mkdir(parents=True)
    Image.new("RGB", (16, 16), (1, 2, 3)).save(out / "001.jpg")
    (out / "001.mov").write_bytes(b"\x00" * 64)

    win = MainWindow()
    assert win.btn_iphone is not None
    win.out_edit.setText(str(out.parent))
    before = _tree(tmp_path)   # after construction: the click is what must not write
    seen = _capture_box(monkeypatch, mw)
    win._import_iphone()

    assert "不会复制或修改任何文件" in seen["text"]
    assert "批量导入" in seen["info"]
    assert "同名" in seen["info"]
    # the folder is only shown as text
    assert str(out.parent) in seen["detail"]
    # no copy, no side folder, no new file anywhere
    assert _tree(tmp_path) == before
    win.close()


def test_iphone_import_prefers_the_last_run_folder_as_the_hint(qapp, tmp_path, monkeypatch):
    _isolated_config(monkeypatch, tmp_path)
    import app.gui.main_window as mw

    root = tmp_path / "exports"
    root.mkdir()
    win = MainWindow()
    win.out_edit.setText(str(root))
    win._last_output_dir = root / "20261018-010101"
    seen = _capture_box(monkeypatch, mw)
    win._import_iphone()
    assert str(win._last_output_dir) in seen["detail"]
    win.close()


def test_iphone_import_works_without_any_output_configured(qapp, tmp_path, monkeypatch):
    """No output dir is not an error: the steps are still what the user needs."""
    _isolated_config(monkeypatch, tmp_path)
    import app.gui.main_window as mw

    win = MainWindow()
    win.out_edit.setText("")
    seen = _capture_box(monkeypatch, mw)
    warn = {}
    monkeypatch.setattr(mw.QMessageBox, "warning",
                        lambda *a, **k: warn.setdefault("called", True))
    win._import_iphone()
    assert "批量导入" in seen["info"]
    assert warn == {}          # no error dialog on the way
    assert not [p for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith("iphone-sync")]
    win.close()


def test_preflight_error_popup_path(qapp, tmp_path, monkeypatch):
    _isolated_config(monkeypatch, tmp_path)
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
