from pathlib import Path

from app.core.conflicts import ConflictPolicy, resolve_output_path


def test_rename_policy(tmp_path: Path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"1")
    out = resolve_output_path(p, ConflictPolicy.RENAME)
    assert out == tmp_path / "a_1.jpg"
    out.write_bytes(b"2")
    out2 = resolve_output_path(p, ConflictPolicy.RENAME)
    assert out2 == tmp_path / "a_2.jpg"


def test_skip_policy(tmp_path: Path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"1")
    assert resolve_output_path(p, ConflictPolicy.SKIP) is None
