"""设置页「外部运行时」只展示状态，不再提供自动安装按钮。

发行版三个运行时均已内置，原先的「安装」按钮在健康状态下永远置灰，属于
无效入口；现在移除按钮与安装线程，面板只保留状态标签。这里固定状态探针，
让断言不依赖跑测试机器实际装了什么。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ImportError as exc:  # missing system libs like libGL
    pytest.skip(f"PySide6 import failed due to system libs: {exc}", allow_module_level=True)

from app.config.schema import default_config
from app.core import runtime_tools
from app.core.runtime_tools import ToolStatus
from app.gui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pin_panel(monkeypatch, *, exiftool_available: bool) -> None:
    def status(name):
        if name == "exiftool" and exiftool_available:
            return ToolStatus(name, True, Path("/opt/tools/exiftool"), "13.59", "bundled")
        return ToolStatus(name, False, None, "", "")

    for name in ("exiftool", "ffmpeg", "ffprobe"):
        monkeypatch.setattr(runtime_tools, f"{name}_status", lambda n=name, **kw: status(n))


def test_no_install_button(qapp):
    dlg = SettingsDialog(default_config())
    assert not hasattr(dlg, "btn_install_exiftool")
    assert not hasattr(dlg, "RuntimeInstallWorker")
    assert not hasattr(dlg, "_rt_thread")
    dlg.close()


def test_panel_shows_status_only(qapp, monkeypatch):
    _pin_panel(monkeypatch, exiftool_available=True)
    dlg = SettingsDialog(default_config())
    assert dlg.lbl_runtime_exiftool.text().startswith("✓")
    assert "13.59" in dlg.lbl_runtime_exiftool.text()
    assert dlg.lbl_runtime_ffmpeg.text().startswith("✗")
    assert dlg.lbl_runtime_ffprobe.text().startswith("✗")

    _pin_panel(monkeypatch, exiftool_available=False)
    dlg._refresh_runtime_status()
    assert dlg.lbl_runtime_exiftool.text().startswith("✗")
    dlg.close()


def test_runtime_group_is_last_in_processing_tab(qapp):
    dlg = SettingsDialog(default_config())
    page = dlg.tabs.widget(1)  # 处理
    # 不再有任何名为「安装」的按钮（依赖安装按钮叫「安装依赖」，不在此列）
    buttons = [btn.text() for btn in page.findChildren(QPushButton)]
    assert not any(t.strip() in ("安装", "安装中 …") for t in buttons)
    # 运行时提示存在且说明仅显示状态
    texts = [lbl.text() for lbl in page.findChildren(QLabel)]
    assert any("仅显示当前可用状态" in t for t in texts)
    dlg.close()
