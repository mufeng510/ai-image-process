from pathlib import Path

import pytest

from app.core.temp_manager import TempManager


def test_temp_under_base(tmp_path: Path):
    tm = TempManager(tmp_path / "t")
    ws = tm.create_job_workspace("abc")
    assert ws.temp_root.exists()
    assert (ws.incoming).exists()
    tm.cleanup_job(ws)
    assert not ws.temp_root.exists()


def test_rejects_outside(tmp_path: Path):
    tm = TempManager(tmp_path / "t")
    with pytest.raises(PermissionError):
        tm._ensure_under_base((tmp_path / "other").resolve())
