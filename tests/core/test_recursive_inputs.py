"""递归扫描子文件夹：收集、去重与输出路径安全护栏。"""
from __future__ import annotations

import random
from pathlib import Path

from app.config.schema import default_config
from app.core.preflight import run_preflight
from app.core.steps.deduplicate import deduplicate_records
from app.core.steps.input_normalize import collect_inputs, to_records


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "album"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "a.jpg").write_bytes(b"IMG-X")
    (root / "sub" / "b.jpg").write_bytes(b"IMG-X")  # 与 a.jpg 内容相同
    (root / "sub" / "deep" / "c.jpg").write_bytes(b"IMG-Y")
    (root / "notes.txt").write_text("not an image", encoding="utf-8")
    return root


def test_recursive_collect_finds_nested_images(tmp_path):
    root = _tree(tmp_path)
    cfg = default_config()

    cfg.input.recurse_folders = True
    found = collect_inputs([root], cfg)
    assert {p.name for p in found} == {"a.jpg", "b.jpg", "c.jpg"}

    cfg.input.recurse_folders = False
    found = collect_inputs([root], cfg)
    assert {p.name for p in found} == {"a.jpg"}


def test_recursive_then_dedup_keeps_one_per_content(tmp_path):
    """去重发生在收集之后，跨子目录的相同内容会被合并，保留字典序第一张。"""
    root = _tree(tmp_path)
    cfg = default_config()
    cfg.input.recurse_folders = True
    records = to_records(collect_inputs([root], cfg))
    assert len(records) == 3

    unique, removed = deduplicate_records(records, "md5")
    assert removed == 1
    assert len(unique) == 2
    kept = {r.source_path.name for r in unique}
    assert kept == {"a.jpg", "c.jpg"}  # a.jpg 排在 sub/b.jpg 之前
    assert [r.index for r in unique] == [1, 2]


def _safe_cfg():
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False  # 开发环境未装 remove-ai-watermarks
    cfg.steps.hidden_image.enabled = False
    cfg.steps.live_photo.enabled = False
    cfg.steps.device_metadata.enabled = False
    return cfg


def test_preflight_refuses_output_inside_recursive_input(tmp_path):
    root = _tree(tmp_path)
    cfg = _safe_cfg()
    cfg.input.recurse_folders = True
    out = root / "out"  # 位于输入目录树内
    records = to_records(collect_inputs([root], cfg))

    result = run_preflight(cfg, [root], records, out, random.Random(1))
    assert result.ok is False
    assert "递归扫描" in result.error
    assert "输出目录" in result.error


def test_preflight_allows_output_inside_input_when_not_recursive(tmp_path):
    root = _tree(tmp_path)
    cfg = _safe_cfg()
    cfg.input.recurse_folders = False
    out = root / "out"
    records = to_records(collect_inputs([root], cfg))

    result = run_preflight(cfg, [root], records, out, random.Random(1))
    assert result.ok is True


def test_preflight_allows_output_next_to_explicit_file_input(tmp_path):
    """显式文件输入不会扫描其父目录，不应被重叠检查误伤。"""
    root = _tree(tmp_path)
    cfg = _safe_cfg()
    cfg.input.recurse_folders = True
    src = root / "a.jpg"
    out = root / "out"
    records = to_records(collect_inputs([src], cfg))

    result = run_preflight(cfg, [src], records, out, random.Random(1))
    assert result.ok is True
