"""Settings dialog: the ExifTool install button must track the real diagnosis.

The button is only worth anything if it is live exactly when something is
missing: enabled with a green tick invites pointless clicks, disabled when the
runtime is broken leaves the user with no way forward. The status probes are
pinned here so the panel never spawns a real tool and the assertions do not
depend on what the machine running the suite has installed.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

try:
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
except ImportError as exc:  # missing system libs like libGL
    pytest.skip(f"PySide6 import failed due to system libs: {exc}", allow_module_level=True)

from app.config.schema import default_config
from app.core import runtime_install as ri
from app.core import runtime_tools
from app.core.runtime_install import RuntimeProblem
from app.core.runtime_tools import ToolStatus
from app.gui.settings_dialog import SettingsDialog

BROKEN = RuntimeProblem(
    tool="exiftool",
    reason="interpreter_missing",
    detail="包内的 ExifTool 是 perl 脚本，而本机没有可用的 perl 解释器",
    manual="sudo apt-get install -y perl",
    can_auto_install=True,
    extra={"asset": "perl-linux-amd64.tar.xz"},
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pin_panel(monkeypatch, *, exiftool_available: bool, problem=None) -> None:
    """Pin the status probes and the diagnosis the panel reads.

    ``_refresh_runtime_status`` imports the status functions inside its body, so
    patching the module attributes is enough.
    """
    def status(name):
        if name == "exiftool" and exiftool_available:
            return ToolStatus(name, True, Path("/opt/tools/exiftool"), "13.59", "bundled")
        return ToolStatus(name, False, None, "", "")

    for name in ("exiftool", "ffmpeg", "ffprobe"):
        monkeypatch.setattr(runtime_tools, f"{name}_status", lambda n=name, **kw: status(n))
    monkeypatch.setattr(ri, "diagnose", lambda *a, **k: problem)


@pytest.fixture()
def dialog(qapp):
    dlg = SettingsDialog(default_config())
    yield dlg
    dlg.close()


def test_install_button_is_enabled_only_while_exiftool_is_missing(qapp, monkeypatch):
    """One dialog, both states: the button follows a refresh in both directions.

    `_refresh_runtime_status` is what the post-install handler calls, so if it
    cached its answer the button would stay dead (or stay live) after a fix.
    """
    _pin_panel(monkeypatch, exiftool_available=True, problem=None)
    dlg = SettingsDialog(default_config())
    assert dlg.btn_install_exiftool.isEnabled() is False
    assert dlg.lbl_runtime_exiftool.text().startswith("✓")
    assert dlg.btn_install_exiftool.toolTip() == "ExifTool 已可用"

    _pin_panel(monkeypatch, exiftool_available=False, problem=BROKEN)
    dlg._refresh_runtime_status()
    assert dlg.btn_install_exiftool.isEnabled() is True
    assert dlg.lbl_runtime_exiftool.text().startswith("✗")
    # the tooltip has to carry the reason, it is the only hover-in explanation
    assert dlg.btn_install_exiftool.toolTip() == BROKEN.detail

    _pin_panel(monkeypatch, exiftool_available=True, problem=None)
    dlg._refresh_runtime_status()
    assert dlg.btn_install_exiftool.isEnabled() is False
    dlg.close()


def test_panel_explains_the_unix_perl_case(qapp):
    """The panel must name the failure unix users actually hit.

    On a checkout without perl, ExifTool reads as "未找到" and nothing else on
    screen says an interpreter is the missing piece -- so the hint has to, or
    the install button is a mystery.
    """
    dlg = SettingsDialog(default_config())
    texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    hints = [t for t in texts if "perl" in t]
    assert hints, "no label in the settings panel mentions perl"
    assert any("不需要管理员权限" in t for t in hints)      # the promise the button makes
    dlg.close()


def test_finished_install_restores_the_button(dialog, monkeypatch):
    """After a run the button must not stay stuck on "安装中 …" disabled-looking.

    A button left in the busy state after the thread is gone tells the user the
    app is still working, and the next repair attempt looks impossible.
    """
    _pin_panel(monkeypatch, exiftool_available=True, problem=None)
    dialog._refresh_runtime_status()
    dialog.btn_install_exiftool.setText("安装中 …")
    dialog.btn_install_exiftool.setEnabled(False)

    dialog._on_runtime_install_finished()

    assert dialog.btn_install_exiftool.text() == "安装"
    assert dialog.btn_install_exiftool.isEnabled() is False   # healthy again -> disabled


def test_failed_install_offers_the_manual_command(qapp, monkeypatch):
    """When the auto-install fails, the dialog must hand over a copy-paste command.

    This is the only recovery path on a platform without a portable perl, so an
    empty or truncated hint leaves the user with no way to fix it themselves.
    """
    _pin_panel(monkeypatch, exiftool_available=False, problem=BROKEN)
    monkeypatch.setattr(ri, "manual_install_command",
                        lambda tool, *, portable_mode=False: "sudo apt-get install -y perl")
    seen: dict[str, str] = {}

    def fake_exec(self):
        seen["info"] = self.informativeText()
        seen["detail"] = self.detailedText()
        return QMessageBox.StandardButton.Close

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    dlg = SettingsDialog(default_config())
    dlg._rt_log = ["下载 perl-linux-amd64.tar.xz …", "解压完成"]
    dlg._on_runtime_install_failed("exiftool", "下载失败（已重试 3 次）")

    assert "下载失败" in seen["info"]
    assert "sudo apt-get install -y perl" in seen["info"]
    assert "sudo apt-get install -y perl" in seen["detail"]
    assert "解压完成" in seen["detail"]          # the progress log is kept for support
    assert dlg._rt_error == "下载失败（已重试 3 次）"
    dlg.close()