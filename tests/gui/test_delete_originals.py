"""「处理完成后删除原件」homepage toggle and its post-run deletion rules."""
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
    w.chk_delete_originals.setChecked(True)
    yield w
    w.close()


def _result(src: Path, out: Path, *, failed=()) -> JobResult:
    return JobResult(
        job_id="j1",
        success=[FileResult(source_path=Path(src), ok=True, output_path=Path(out))],
        failed=[FileResult(source_path=Path(f), ok=False, error="boom") for f in failed],
    )


def _make_file(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"img")
    return p


def _make_out(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    o = out / "result.JPG"
    o.write_bytes(b"out")
    return o


def test_default_is_off():
    assert default_config().input.delete_originals_after_run is False


def test_round_trips_through_the_config(win):
    win.chk_delete_originals.setChecked(False)
    assert win._ui_to_config().input.delete_originals_after_run is False
    win._apply_config_to_ui()
    assert win.chk_delete_originals.isChecked() is False

    win.chk_delete_originals.setChecked(True)
    assert win._ui_to_config().input.delete_originals_after_run is True


def test_toggle_off_never_deletes(win, tmp_path):
    src = _make_file(tmp_path, "a.jpg")
    out = _make_out(tmp_path)
    win.chk_delete_originals.setChecked(False)
    win._on_paths_dropped([str(src)])
    win._on_finished(_result(src, out))
    assert src.exists()


def test_file_input_is_deleted_after_success(win, tmp_path):
    src = _make_file(tmp_path, "a.jpg")
    out = _make_out(tmp_path)
    win._on_paths_dropped([str(src)])
    win._on_finished(_result(src, out))
    assert not src.exists()


def test_file_input_kept_when_it_failed(win, tmp_path):
    src = _make_file(tmp_path, "bad.jpg")
    out = _make_out(tmp_path)
    win._on_paths_dropped([str(src)])
    result = JobResult(
        job_id="j1",
        success=[FileResult(source_path=tmp_path / "ok.jpg", ok=True, output_path=out)],
        failed=[FileResult(source_path=src, ok=False, error="boom")],
    )
    win._on_finished(result)
    assert src.exists()


def test_folder_input_is_deleted_wholesale_after_success(win, tmp_path):
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"1")
    (folder / "b.jpg").write_bytes(b"2")
    (folder / "notes.txt").write_text("unrelated but inside the folder")
    out = _make_out(tmp_path)
    win._on_paths_dropped([str(folder)])
    result = JobResult(
        job_id="j1",
        success=[FileResult(source_path=folder / "a.jpg", ok=True, output_path=out)],
    )
    win._on_finished(result)
    assert not folder.exists()


def test_folder_kept_when_any_file_failed(win, tmp_path):
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"1")
    (folder / "b.jpg").write_bytes(b"2")
    out = _make_out(tmp_path)
    win._on_paths_dropped([str(folder)])
    result = JobResult(
        job_id="j1",
        success=[FileResult(source_path=folder / "a.jpg", ok=True, output_path=out)],
        failed=[FileResult(source_path=folder / "b.jpg", ok=False, error="boom")],
    )
    win._on_finished(result)
    assert folder.exists() and (folder / "b.jpg").exists()


def test_nothing_deleted_without_committed_outputs(win, tmp_path):
    src = _make_file(tmp_path, "a.jpg")
    win._on_paths_dropped([str(src)])
    # output_write disabled: success without an on-disk output
    result = JobResult(
        job_id="j1",
        success=[FileResult(source_path=src, ok=True, output_path=None)],
    )
    win._on_finished(result)
    assert src.exists()


def test_outputs_on_disk_are_required(win, tmp_path):
    src = _make_file(tmp_path, "a.jpg")
    win._on_paths_dropped([str(src)])
    result = JobResult(
        job_id="j1",
        success=[FileResult(source_path=src, ok=True,
                            output_path=tmp_path / "out" / "gone.JPG")],
    )
    win._on_finished(result)  # output does not exist on disk
    assert src.exists()


def test_cancelled_run_deletes_nothing(win, tmp_path):
    src = _make_file(tmp_path, "a.jpg")
    out = _make_out(tmp_path)
    win._on_paths_dropped([str(src)])
    result = JobResult(
        job_id="j1",
        success=[FileResult(source_path=src, ok=True, output_path=out)],
        cancelled=True,
    )
    win._on_finished(result)
    assert src.exists()


def test_refused_preflight_deletes_nothing(win, tmp_path):
    src = _make_file(tmp_path, "a.jpg")
    win._on_paths_dropped([str(src)])
    result = JobResult(job_id="j1", preflight_failed=True, preflight_error="nope")
    win._on_finished(result)
    assert src.exists()


def test_dry_run_like_result_deletes_nothing(win, tmp_path):
    src = _make_file(tmp_path, "a.jpg")
    win._on_paths_dropped([str(src)])
    result = JobResult(job_id="j1", dry_run=True, planned_input_count=1)
    win._on_finished(result)
    assert src.exists()
