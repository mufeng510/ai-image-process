"""「处理后清空输入」quick toggle at the selection row."""
from __future__ import annotations

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
from app.core.models import FileResult, JobResult
from app.gui.main_window import MainWindow


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


@pytest.fixture()
def win(qapp, isolated_config, monkeypatch):
    import app.gui.main_window as mw

    # _on_finished pops a modal box; stub it out so the test never blocks.
    class _StubBox:
        @staticmethod
        def information(*a, **k):
            return None

        @staticmethod
        def warning(*a, **k):
            return None

        @staticmethod
        def critical(*a, **k):
            return None

    monkeypatch.setattr(mw, "QMessageBox", _StubBox)
    w = MainWindow()
    yield w
    w.close()


def _selection_row(win):
    """The QHBoxLayout that holds the selection buttons."""
    root = win.btn_add_files.parentWidget().layout()
    for i in range(root.count()):
        lay = root.itemAt(i).layout()
        if lay is None:
            continue
        widgets = [lay.itemAt(j).widget() for j in range(lay.count())]
        if win.btn_add_files in widgets:
            return lay
    return None


def _job(**kw) -> JobResult:
    base = dict(job_id="j1", success=[FileResult(source_path=Path("/tmp/a.jpg"), ok=True)])
    base.update(kw)
    return JobResult(**base)


def test_toggle_lives_next_to_the_selection_buttons(win):
    """It has to be reachable where the selection happens, not buried."""
    assert win.chk_clear_after is not None
    assert win.chk_clear_after.text() == "处理后清空"
    row = _selection_row(win)
    assert row is not None
    widgets = [row.itemAt(i).widget() for i in range(row.count())]
    assert win.btn_add_files in widgets
    assert win.btn_add_folder in widgets
    assert win.btn_clear in widgets
    assert win.chk_clear_after in widgets


def test_default_is_on(win):
    assert win.chk_clear_after.isChecked() is True


def test_config_default_is_on():
    assert default_config().input.clear_after_run is True


def test_toggle_round_trips_through_the_config(win):
    """UI -> config -> UI must land on the same value."""
    win.chk_clear_after.setChecked(False)
    assert win._ui_to_config().input.clear_after_run is False
    win._apply_config_to_ui()
    assert win.chk_clear_after.isChecked() is False

    win.chk_clear_after.setChecked(True)
    assert win._ui_to_config().input.clear_after_run is True
    win._apply_config_to_ui()
    assert win.chk_clear_after.isChecked() is True


def test_apply_config_to_ui_reflects_the_stored_value(win):
    """The window is restored from the config, so the stored value wins."""
    win._config.input.clear_after_run = False
    win._apply_config_to_ui()
    assert win.chk_clear_after.isChecked() is False

    win._config.input.clear_after_run = True
    win._apply_config_to_ui()
    assert win.chk_clear_after.isChecked() is True


def test_finished_run_clears_the_selection(win):
    win._on_paths_dropped(["/tmp/a.jpg", "/tmp/b.jpg"])
    assert len(win._inputs) == 2

    win._on_finished(_job())

    assert win._inputs == []
    assert "已选择" not in win.drop_zone.label.text()


def test_finished_run_keeps_the_selection_when_the_toggle_is_off(win):
    win.chk_clear_after.setChecked(False)
    win._on_paths_dropped(["/tmp/a.jpg"])

    win._on_finished(_job())

    assert len(win._inputs) == 1


def test_individual_failures_still_count_as_finished(win):
    """A run where some files failed is still "处理完" - the batch is over."""
    win._on_paths_dropped(["/tmp/a.jpg"])
    result = _job(failed=[FileResult(source_path=Path("/tmp/bad.jpg"), ok=False, error="boom")])

    win._on_finished(result)

    assert win._inputs == []


def test_cancelled_run_keeps_the_selection(win):
    """A cancelled job is usually resumed, so the selection must survive."""
    win._on_paths_dropped(["/tmp/a.jpg"])

    win._on_finished(_job(cancelled=True))

    assert len(win._inputs) == 1


def test_refused_preflight_keeps_the_selection(win):
    win._on_paths_dropped(["/tmp/a.jpg"])

    win._on_finished(_job(preflight_failed=True, preflight_error="nope"))

    assert len(win._inputs) == 1


def test_manual_clear_still_works(win):
    win._on_paths_dropped(["/tmp/a.jpg"])
    win._clear_inputs()
    assert win._inputs == []
