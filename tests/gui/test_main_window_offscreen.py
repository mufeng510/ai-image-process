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


def test_main_window_builds(qapp):
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
