"""Offscreen GUI smoke tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # missing system libs like libGL
    pytest.skip(f"PySide6 import failed due to system libs: {exc}", allow_module_level=True)

from app.config.schema import default_config
from app.gui.main_window import MainWindow
from app.gui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    import app.gui.main_window as mw
    from app.config.manager import ConfigManager

    monkeypatch.setattr(
        mw, "ConfigManager",
        lambda *a, **k: ConfigManager(tmp_path / "test-config.json"),
    )


def test_main_window_builds(qapp, isolated_config):
    win = MainWindow()
    assert "AI Image Process" in win.windowTitle()
    assert win.btn_start is not None
    win.close()


def test_settings_dialog_roundtrip(qapp):
    cfg = default_config()
    cfg.naming.template = "{date}_{original_name}"
    cfg.naming.preset = "custom"
    cfg.steps.reencode.quality_min = 90
    cfg.steps.reencode.quality_max = 95
    cfg.steps.device_metadata.selection = "random"
    cfg.input.recurse_folders = True
    dlg = SettingsDialog(cfg)
    out = dlg.config()
    # before accept, config() returns original deepcopy until accept collects;
    # call collect via accept path fields:
    collected = dlg._collect_ui_config()
    assert collected.naming.template == "{date}_{original_name}"
    assert collected.steps.reencode.quality_min == 90
    assert collected.input.recurse_folders is True
    dlg.close()


def test_settings_presets_and_validation(qapp):
    cfg = default_config()
    dlg = SettingsDialog(cfg)
    # switch to number preset
    idx = dlg.preset.findData("number")
    assert idx >= 0
    dlg.preset.setCurrentIndex(idx)
    collected = dlg._collect_ui_config()
    assert collected.naming.template == "IMG_{number}"
    # invalid quality range
    dlg.qmin.setValue(99)
    dlg.qmax.setValue(90)
    with pytest.raises(ValueError):
        dlg._collect_ui_config()
    dlg.close()


def test_settings_export_import(qapp, tmp_path: Path):
    cfg = default_config()
    cfg.naming.template = "{datetime}_{original_name}"
    cfg.naming.preset = "custom"
    dlg = SettingsDialog(cfg)
    # simulate export via manager API used by dialog
    from app.config.manager import ConfigManager
    export_path = tmp_path / "cfg.json"
    ConfigManager().export_to(export_path, dlg._collect_ui_config())
    raw = json.loads(export_path.read_text(encoding="utf-8"))
    assert raw["naming"]["template"] == "{datetime}_{original_name}"
    dlg.close()


def test_settings_offers_install_for_both_raiw_features(qapp):
    """Both remove-ai-watermarks-backed features expose an in-app installer."""
    from app.core import dependency_installer

    cfg = default_config()
    dlg = SettingsDialog(cfg)
    assert dlg.btn_install_prov.isVisible() or dlg.btn_install_prov.toolTip()
    assert dlg.btn_install_visible.isVisible() or dlg.btn_install_visible.toolTip()
    assert dlg.btn_install_prov.toolTip() == (
        f'在线安装 {dependency_installer.FEATURE_SPECS["provenance"]}（本功能所需）'
    )
    assert dlg.btn_install_visible.toolTip() == (
        f'在线安装 {dependency_installer.FEATURE_SPECS["visible"]}（本功能所需，含 cv2 后端）'
    )
    dlg.close()


def test_settings_dependency_status_reflects_package_state(qapp):
    from app.core import visible_models

    cfg = default_config()
    dlg = SettingsDialog(cfg)
    st = visible_models.package_status()
    if st.importable:
        assert "已安装" in dlg.prov_status.text()
    else:
        assert "未安装" in dlg.prov_status.text()
        assert "安装依赖" in dlg.prov_status.text()
    # onnx install button enabled only when the package exists but onnx is missing
    assert dlg.btn_install_onnx.isEnabled() == (st.importable and not st.onnx_ready)
    dlg.close()


def test_main_window_construction_not_blocked_by_library_scan(qapp, tmp_path, monkeypatch):
    """构造 MainWindow 时不得在 GUI 主线程同步扫描/完整解码整个隐藏图片库。

    若库文件多，同步扫描会把构造卡在主线程，导致双击打开后窗口
    迟迟不显示。扫描应在后台线程进行，构造本身必须快速返回。
    """
    import app.gui.main_window as mw
    from app.config.manager import ConfigManager
    from PIL import Image

    cfg_path = tmp_path / "test-config.json"
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    Image.new("RGB", (10, 10)).save(lib_dir / "a.jpg")
    cfg_path.write_text(json.dumps({
        "output": {"directory": str(tmp_path / "out"), "auto_create_directory": True,
                   "preserve_originals": True},
        "input": {"clear_after_run": False, "extensions": ["jpg", "jpeg", "png", "webp"]},
        "steps": {
            "provenance_cleanup": {"enabled": True},
            "visible_watermark": {"enabled": False},
            "reencode": {"enabled": True},
            "device_metadata": {"enabled": False},
            "rename": {"enabled": True},
            "rotate_crop": {"enabled": False},
            "hidden_image": {"enabled": True, "library_dir": str(lib_dir), "opacity": 0.02},
            "live_photo": {"enabled": False},
            "output_write": {"enabled": True},
        },
    }))
    monkeypatch.setattr(mw, "ConfigManager", lambda *a, **k: ConfigManager(cfg_path))

    # 把扫描打桩为“很慢”：模拟图片库文件多、完整解码耗时的场景。
    from app.core import hidden_images as hi
    import threading
    released = threading.Event()
    orig = hi.scan_hidden_library_detailed

    def blocking_scan(lib, exts):
        released.wait(timeout=5)
        return orig(lib, exts)

    monkeypatch.setattr(hi, "scan_hidden_library_detailed", blocking_scan)

    import time
    t0 = time.perf_counter()
    win = MainWindow()
    dt = time.perf_counter() - t0
    released.set()  # 允许后台扫描线程结束

    # 构造本身必须快速返回：不在主线程同步等待扫描完成。
    assert dt < 2.0, f"MainWindow 构造耗时过长：{dt:.2f}s"
    # 已启动后台扫描（非阻塞主线程）
    assert win._scan_thread is not None
    win.close()
    # 显式等待后台扫描线程结束，避免 pytest 退出时 daemon 线程导致
    # PySide6 teardown 崩溃。
    if win._scan_thread is not None:
        win._scan_thread.join(timeout=2)
