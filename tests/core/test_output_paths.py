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