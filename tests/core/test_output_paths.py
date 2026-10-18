"""Per-run output folder: resolution rules and end-to-end publishing.

The promise: one directory the user picks, every job publishes into a fresh
timestamped sub-folder of it, repeated runs never mix or overwrite each other,
and resolution itself is pure — a preflight failure leaves no trace on disk.
"""
import re
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from app.config.schema import AppConfig, default_config
from app.core import output_paths
from app.core.output_paths import MAX_SUFFIX_ATTEMPTS, resolve_run_folder, run_folder_name
from app.core.pipeline import run_job

WHEN = datetime(2026, 10, 18, 3, 59, 51)
STAMP = "20261018-035951"


class _FrozenClock(datetime):
    """A datetime whose now() never moves, so two runs land in the same second."""

    @classmethod
    def now(cls, tz=None):  # mirrors datetime.now(tz=None)
        return WHEN


def test_run_folder_name_uses_second_resolution():
    assert run_folder_name(WHEN) == STAMP
    assert run_folder_name() == datetime.now().strftime("%Y%m%d-%H%M%S")  # defaults to now


def test_resolve_run_folder_appends_timestamp_and_creates_nothing(tmp_path):
    """Preflight failure must leave the disk untouched, so resolution is pure."""
    root = tmp_path / "exports"
    assert resolve_run_folder(root, when=WHEN) == root / STAMP
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("taken,expected", [
    ([], STAMP),            # first run of that second
    ([STAMP], f"{STAMP}-2"),
    ([STAMP, f"{STAMP}-2"], f"{STAMP}-3"),
])
def test_resolve_run_folder_walks_suffix_until_free(tmp_path, taken, expected):
    root = tmp_path / "exports"
    root.mkdir()
    for name in taken:
        (root / name).mkdir()
    assert resolve_run_folder(root, when=WHEN) == root / expected


@pytest.mark.parametrize("preexisting", [False, True])
def test_per_run_false_returns_the_root_verbatim(tmp_path, preexisting):
    """No timestamp, no suffix walk: the root comes back as-is either way."""
    root = tmp_path / "exports"
    if preexisting:
        root.mkdir()
        (root / STAMP).mkdir()
    assert resolve_run_folder(root, when=WHEN, per_run=False) == root


def test_resolve_run_folder_expands_user_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_run_folder("~/exports", when=WHEN) == tmp_path / "exports" / STAMP


def test_resolve_run_folder_raises_when_suffixes_run_out(monkeypatch, tmp_path):
    monkeypatch.setattr(output_paths, "MAX_SUFFIX_ATTEMPTS", 3)
    root = tmp_path / "exports"
    for name in (STAMP, f"{STAMP}-2", f"{STAMP}-3"):
        (root / name).mkdir(parents=True)
    with pytest.raises(RuntimeError) as exc:
        resolve_run_folder(root, when=WHEN)
    assert str(root) in str(exc.value)  # names the root it gave up on
    assert MAX_SUFFIX_ATTEMPTS == 1000  # the shipped bound, not the patched one


def test_default_config_enables_per_run_subfolder():
    assert default_config().output.subfolder_per_run is True


@pytest.mark.parametrize("stored,expected", [
    ({}, True),                             # v1 config, field absent
    ({"subfolder_per_run": False}, False),  # explicit opt-out survives
    ({"subfolder_per_run": True}, True),
])
def test_from_dict_keeps_subfolder_per_run(stored, expected):
    """v1 -> v2 migration must not invent or flip the field."""
    legacy = {"config_version": 1, "output": dict(stored)}
    assert AppConfig.from_dict(legacy).output.subfolder_per_run is expected


def _config(tmp_path: Path, **flags):
    """default_config() minus the two steps that need optional binaries."""
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.device_metadata.enabled = False
    cfg.output.subfolder_per_run = flags.get("subfolder", True)
    cfg.output.auto_create_directory = flags.get("auto_create", True)
    cfg.steps.hidden_image.enabled = flags.get("hidden", False)
    if flags.get("template"):
        cfg.naming.preset = "custom"
        cfg.naming.template = flags["template"]
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    return cfg


def _inputs(tmp_path: Path, count: int = 2) -> Path:
    src = tmp_path / "in"
    src.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        Image.new("RGB", (64, 48), (10 * i, 40, 60)).save(src / f"photo{i}.jpg", "JPEG")
    return src


def _run(cfg, src: Path, exports: Path, tmp_path: Path):
    return run_job(cfg, [src], output_dir=exports, seed=1, temp_base=tmp_path / "tmp")


def test_run_job_publishes_into_one_timestamped_subfolder(tmp_path):
    src, exports = _inputs(tmp_path), tmp_path / "exports"
    result = _run(_config(tmp_path), src, exports, tmp_path)
    assert (result.preflight_failed, result.success_count, result.failure_count) == (False, 2, 0)
    subs = sorted(p for p in exports.iterdir() if p.is_dir())
    assert len(subs) == 1
    assert re.fullmatch(r"\d{8}-\d{6}", subs[0].name)
    assert sorted(p.name for p in subs[0].glob("*.jpg")) == ["photo0.jpg", "photo1.jpg"]
    assert list(exports.glob("*.jpg")) == []  # nothing written straight into the root


def test_repeated_runs_never_share_or_overwrite_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(output_paths, "datetime", _FrozenClock)  # force the same second
    src, exports = _inputs(tmp_path), tmp_path / "exports"
    _run(_config(tmp_path), src, exports, tmp_path)
    first = exports / STAMP
    before = {p.name: p.stat().st_size for p in first.glob("*.jpg")}
    assert len(before) == 2 and all(size > 0 for size in before.values())
    _run(_config(tmp_path), src, exports, tmp_path)
    assert sorted(p.name for p in exports.iterdir()) == [STAMP, f"{STAMP}-2"]
    assert {p.name: p.stat().st_size for p in first.glob("*.jpg")} == before  # run 1 intact
    assert len(list((exports / f"{STAMP}-2").glob("*.jpg"))) == 2


def test_subfolder_per_run_false_writes_into_the_chosen_directory(tmp_path):
    src, exports = _inputs(tmp_path), tmp_path / "exports"
    result = _run(_config(tmp_path, subfolder=False), src, exports, tmp_path)
    assert (result.success_count, result.failure_count) == (2, 0)
    assert sorted(p.name for p in exports.glob("*.jpg")) == ["photo0.jpg", "photo1.jpg"]
    assert [p for p in exports.iterdir() if p.is_dir()] == []


@pytest.mark.parametrize("break_it", ["hidden_no_library", "unsafe_template"])
def test_preflight_failure_never_creates_the_output_root(tmp_path, break_it):
    src, exports = _inputs(tmp_path), tmp_path / "exports"
    cfg = _config(tmp_path, hidden=break_it == "hidden_no_library",
                  template="../escape_{number}" if break_it == "unsafe_template" else None)
    result = _run(cfg, src, exports, tmp_path)
    assert result.preflight_failed is True and result.preflight_error
    assert (result.success_count, result.failure_count) == (0, 0)
    assert not exports.exists(), "a refused job must not leave an empty folder behind"


def test_missing_root_without_auto_create_fails_every_file(tmp_path):
    """auto_create governs the directory the user picked — not the per-run leaf."""
    src, exports = _inputs(tmp_path), tmp_path / "exports"
    result = _run(_config(tmp_path, auto_create=False), src, exports, tmp_path)
    assert result.preflight_failed is False  # a per-file failure, not a refusal
    assert (result.success_count, result.failure_count) == (0, 2)
    errors = [f.error or "" for f in result.failed]
    assert all("output directory missing" in e for e in errors)
    reported = [e.split("output directory missing:")[1].splitlines()[0].strip() for e in errors]
    assert [Path(p) for p in reported] == [exports.resolve()] * 2  # the root, not the leaf
    assert not exports.exists()


def test_settings_dialog_subfolder_checkbox_roundtrip(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from app.gui.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    dlg = SettingsDialog(default_config())
    assert dlg.chk_subfolder.isChecked() is True  # bound from the default config
    dlg.chk_subfolder.setChecked(False)
    assert dlg._collect_ui_config().output.subfolder_per_run is False
    dlg.close()
    del app


# --- regressions: a run folder that leaked, lingered, or was claimed twice ------


def _isolated_config(monkeypatch, tmp_path):
    """Point MainWindow at a throwaway config, never the user's real one."""
    import app.gui.main_window as mw
    from app.config.manager import ConfigManager

    monkeypatch.setattr(
        mw, "ConfigManager",
        lambda *a, **k: ConfigManager(tmp_path / "test-config.json"),
    )


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # must precede QApplication
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def _finished_result(out_dir: Path):
    """A successful JobResult as _on_finished sees it: one published output."""
    from app.core.models import FileResult, JobResult
    return JobResult(job_id="job-1", success=[FileResult(
        source_path=Path("/tmp/whatever/in/x.jpg"), ok=True, output_path=out_dir / "x.jpg")])


def test_finished_never_backfills_the_output_path_field(qapp, tmp_path, monkeypatch):
    """out_edit is the *next* run's root: filling it with this run's leaf would
    nest one level deeper per click, and closeEvent would persist the nesting."""
    import app.gui.main_window as mw
    from app.gui.main_window import MainWindow

    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
    _isolated_config(monkeypatch, tmp_path)
    win, root = MainWindow(), tmp_path / "exports"
    win.out_edit.setText(str(root))
    win._on_finished(_finished_result(Path("/tmp/whatever/20261018-010101")))
    assert win._last_output_dir == Path("/tmp/whatever/20261018-010101")  # the code ran
    assert win.out_edit.text() == str(root)
    win.deleteLater()


def test_two_runs_leave_the_typed_output_root_untouched(qapp, tmp_path, monkeypatch):
    """The stacking users actually saw: run, then run again without touching the
    field — the text must still be exactly what they typed."""
    import app.gui.main_window as mw
    from app.gui.main_window import MainWindow

    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
    _isolated_config(monkeypatch, tmp_path)
    win, root = MainWindow(), tmp_path / "exports"
    win.out_edit.setText(str(root))
    for stamp in ("20261018-010101", "20261018-020202"):
        win._on_finished(_finished_result(Path(f"/tmp/whatever/{stamp}")))
        assert win.out_edit.text() == str(root)
    win.deleteLater()


def test_run_folder_created_but_never_written_is_reclaimed(tmp_path):
    """A placeholder this run made and never filled must not linger empty."""
    src = tmp_path / "in"
    src.mkdir()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(src / "fake.jpg", "PNG")
    exports = tmp_path / "exports"
    cfg = _config(tmp_path)
    for step in (cfg.steps.reencode, cfg.steps.rotate_crop, cfg.steps.hidden_image):
        step.enabled = False  # preflight reads the .jpg extension and lets it by
    result = _run(cfg, src, exports, tmp_path)
    assert result.preflight_failed is False  # output_write is what rejects it
    assert (result.success_count, result.failure_count) == (0, 1)
    assert "非 JPEG" in (result.failed[0].error or "")
    assert exports.exists()  # the root the user picked stays...
    assert not [p for p in exports.iterdir() if p.is_dir()]  # ...without an empty leaf


def test_placeholder_creation_survives_another_job_taking_the_name(tmp_path, monkeypatch):
    """mkdir(exist_ok=False) is the atomic claim: a concurrent job that wins the
    window between resolving a name and creating it must push us to -2."""
    monkeypatch.setattr(output_paths, "datetime", _FrozenClock)  # fixed stamp
    src, exports = _inputs(tmp_path), tmp_path / "exports"
    real, seen = output_paths.resolve_run_folder, []

    def raced(root, *, when=None, per_run=True):
        path = real(root, when=when, per_run=per_run)
        seen.append(path)
        if len(seen) == 1:  # "another process" grabs the name right here
            path.mkdir(parents=True)
            (path / "theirs.jpg").write_bytes(b"not-ours")
        return path

    from app.core import pipeline

    monkeypatch.setattr(pipeline, "resolve_run_folder", raced)
    result = _run(_config(tmp_path), src, exports, tmp_path)
    assert result.success_count == 2
    theirs, ours = exports / STAMP, exports / f"{STAMP}-2"
    assert (theirs / "theirs.jpg").read_bytes() == b"not-ours"  # theirs, untouched
    assert not (theirs / "photo0.jpg").exists()  # we did not share their folder
    assert sorted(p.name for p in ours.glob("*.jpg")) == ["photo0.jpg", "photo1.jpg"]


def test_unusable_run_folder_is_a_refusal_not_a_traceback(tmp_path, monkeypatch):
    """Running out of suffix names is a structured preflight failure, and since
    resolution runs before preflight it leaves nothing on disk."""
    monkeypatch.setattr(output_paths, "datetime", _FrozenClock)
    monkeypatch.setattr(output_paths, "MAX_SUFFIX_ATTEMPTS", 1)
    src, exports = _inputs(tmp_path), tmp_path / "exports"
    for name in (STAMP, f"{STAMP}-2"):
        (exports / name).mkdir(parents=True)
    before = sorted(p.name for p in exports.iterdir())
    result = _run(_config(tmp_path), src, exports, tmp_path)
    assert result.preflight_failed is True and result.preflight_error
    assert (result.success_count, result.failure_count) == (0, 0)
    assert sorted(p.name for p in exports.iterdir()) == before  # nothing added