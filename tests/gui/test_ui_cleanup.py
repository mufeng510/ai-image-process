"""回归测试：高 DPI 显示修复 + 配置项清理。

覆盖三件事：
1. 主窗口内容区可滚动、初始尺寸受屏幕可用几何约束（缩放后不再截断）；
2. 「保留原始图片」改名后不再与「删除原件」表意冲突；
3. GUI 里无效的控件（输出到原图目录、固定为 1 的并发 SpinBox）已移除，
   冲突策略在开启时间戳子目录时置灰并给出说明。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from app.config.schema import default_config  # noqa: E402
from app.gui.main_window import MainWindow  # noqa: E402
from app.gui.settings_dialog import SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    import app.gui.main_window as mw
    from app.config.manager import ConfigManager

    monkeypatch.setattr(
        mw, "ConfigManager",
        lambda *a, **k: ConfigManager(tmp_path / "test-config.json"),
    )


def test_main_window_content_is_scrollable(qapp, isolated_config):
    win = MainWindow()
    assert isinstance(win.centralWidget(), QScrollArea), (
        "主窗口内容区必须是 QScrollArea，否则高 DPI 缩放下底部控件会被截断"
    )
    scroll = win.centralWidget()
    assert scroll.widgetResizable() is True
    assert scroll.widget() is not None
    win.close()


def test_main_window_keeps_only_runtime_controls(qapp, isolated_config):
    """红框内的开关已从主界面移除，设置页必须仍然提供对应项。"""
    win = MainWindow()
    # 输出组：只留删除原件；自动创建目录 / 禁止覆盖原文件已移到设置页
    assert not hasattr(win, "chk_auto_create")
    assert not hasattr(win, "chk_preserve")
    assert "删除原件" in win.chk_delete_originals.text()
    # 处理步骤组：只留 Live Photo / 输出写入
    for name in (
        "chk_provenance", "chk_visible", "chk_reencode", "chk_device",
        "chk_rename", "chk_rotate", "chk_hidden",
    ):
        assert not hasattr(win, name), f"{name} 不应再出现在主界面"
    assert win.chk_live is not None and win.chk_output is not None
    win.close()

    dlg = SettingsDialog(default_config())
    for name in (
        "chk_auto_create", "chk_preserve", "chk_prov", "chk_visible", "chk_reenc",
        "chk_device", "chk_rename", "chk_rotate", "chk_hidden",
    ):
        assert hasattr(dlg, name), f"设置页缺少 {name}"
    dlg.close()


def test_settings_removes_noop_controls(qapp):
    dlg = SettingsDialog(default_config())
    assert not hasattr(dlg, "chk_use_source"), "GUI 不生效的输出到原图目录选项应移除"
    assert not hasattr(dlg, "workers"), "范围 (1,1) 的并发 SpinBox 应改为静态说明"
    assert "禁止覆盖原文件" in dlg.chk_preserve.text()
    dlg.close()


def test_conflict_policy_disabled_when_subfolder_on(qapp):
    dlg = SettingsDialog(default_config())
    # 默认开启时间戳子目录 → 冲突策略置灰且显示说明
    assert dlg.chk_subfolder.isChecked() is True
    assert dlg.conflict.isEnabled() is False
    assert dlg.conflict_note.isHidden() is False  # 对话框未 show，用 isHidden 判断显式隐藏状态
    assert "时间戳" in dlg.conflict_note.text()
    # 关闭后恢复可用
    dlg.chk_subfolder.setChecked(False)
    assert dlg.conflict.isEnabled() is True
    assert dlg.conflict_note.isHidden() is True
    dlg.close()


def test_dead_config_key_removed():
    data = default_config().to_dict()
    assert "allow_overwrite_originals" not in data["output"]
    # 老配置里即使带了这个键，也不会出现在重新导出的配置中
    from app.config.schema import AppConfig

    raw = default_config().to_dict()
    raw["output"]["allow_overwrite_originals"] = True
    assert "allow_overwrite_originals" not in AppConfig.from_dict(raw).to_dict()["output"]
