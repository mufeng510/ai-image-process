"""Preflight's ExifTool gate: refuse before a silent no-op or a late failure.

ExifTool is the one external runtime whose absence does not announce itself.
With the runner missing, the device-metadata step still reports ok=True and
writes no Make/Model/ISO, and Live Photo dies much later with "photo asset
identifier missing" -- a symptom the user has never heard of. So a run that
enabled either step must be refused *before* anything is written, with a message
that says which step caused it.

The diagnosis itself is covered in ``test_runtime_install.py``; here the gate is
driven through the real ``run_preflight`` so the wiring (which steps count,
``extra``, ordering against the FFmpeg check) cannot regress unnoticed.
"""
from __future__ import annotations

import platform
import random
from pathlib import Path

from PIL import Image

from app.config.schema import default_config
from app.core import runtime_install as ri
from app.core import runtime_tools
from app.core.preflight import run_preflight
from app.core.runtime_install import RuntimeProblem
from app.core.steps.input_normalize import collect_inputs, to_records

BROKEN = RuntimeProblem(
    tool="exiftool",
    reason="interpreter_missing",
    detail="包内的 ExifTool 是 perl 脚本，而本机没有可用的 perl 解释器",
    manual="sudo apt-get install -y perl",
    can_auto_install=True,
    extra={"asset": "perl-linux-amd64.tar.xz"},
)


def _records(tmp_path: Path, count: int = 1):
    """A directory of generated JPEGs plus the records preflight expects."""
    src = tmp_path / "in"
    src.mkdir(exist_ok=True)
    for i in range(count):
        Image.new("RGB", (16, 16), (i + 1, i + 1, i + 1)).save(src / f"img_{i}.jpg")
    cfg = default_config()
    cfg.steps.hidden_image.enabled = False     # keep the library checks out of it
    recs = to_records(collect_inputs([src], cfg))
    assert len(recs) == count
    return cfg, src, recs


def _pin_diagnose(monkeypatch, problem: RuntimeProblem | None) -> list:
    """Stand in for the diagnosis and record the arguments preflight passes it."""
    seen: list[tuple] = []

    def diagnose(tool, *, portable_mode=False):
        seen.append((tool, portable_mode))
        return problem

    monkeypatch.setattr(ri, "diagnose", diagnose)
    return seen


def _preflight(cfg, src, recs, tmp_path):
    return run_preflight(cfg, [src], recs, tmp_path / "out", random.Random(0))


def test_device_metadata_is_refused_when_exiftool_cannot_run(tmp_path, monkeypatch):
    """End to end through the real diagnosis: no usable ExifTool, step on, refuse.

    Pinned one level below preflight (status probe + candidate paths + platform)
    so the whole chain is exercised, still without touching the network, PATH
    or the user's data directory.
    """
    monkeypatch.setattr(runtime_tools, "exiftool_status",
                        lambda **kw: runtime_tools.ToolStatus("exiftool", False))
    monkeypatch.setattr(ri, "_script_candidates",
                        lambda tool, portable_mode: [tmp_path / "exiftool"])
    (tmp_path / "exiftool").write_text("#!/bin/sh\nexec perl exiftool.pl\n", encoding="utf-8")
    monkeypatch.setattr(platform, "system", lambda: "Linux")   # the unix branch, anywhere
    monkeypatch.setattr(ri, "_platform_asset", lambda: "perl-linux-amd64.tar.xz")
    monkeypatch.setattr(ri, "_perl_manual_command", lambda: "sudo apt-get install -y perl")

    cfg, src, recs = _records(tmp_path)
    assert cfg.steps.device_metadata.enabled is True     # default on: no setup needed
    result = _preflight(cfg, src, recs, tmp_path)

    assert result.ok is False
    assert "ExifTool" in result.error
    assert "「写入设备信息」" in result.error            # the step that caused it
    assert "perl" in result.error                        # the actual cause
    assert result.extra["runtime"] == "exiftool"
    assert result.extra["reason"] == "interpreter_missing"
    assert result.extra["manual"] == "sudo apt-get install -y perl"


def test_live_photo_alone_is_enough_to_be_refused(tmp_path, monkeypatch):
    """Live Photo needs ExifTool too, so turning device metadata off is no escape.

    The two steps fail in opposite ways (silent no-write vs. late crash), which
    is why the gate covers either one independently.
    """
    _pin_diagnose(monkeypatch, BROKEN)
    cfg, src, recs = _records(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.steps.live_photo.enabled = True
    result = _preflight(cfg, src, recs, tmp_path)

    assert result.ok is False
    assert result.extra["runtime"] == "exiftool"
    assert "「Live Photo」" in result.error
    assert "「写入设备信息」" not in result.error        # only the enabled step is named


def test_both_steps_are_named_when_both_are_enabled(tmp_path, monkeypatch):
    """The refusal must list every step that is waiting on ExifTool.

    A message naming only one of them invites "let me just switch that one off"
    and a second failed run.
    """
    _pin_diagnose(monkeypatch, BROKEN)
    cfg, src, recs = _records(tmp_path)
    cfg.steps.device_metadata.enabled = True
    cfg.steps.live_photo.enabled = True
    result = _preflight(cfg, src, recs, tmp_path)

    assert result.ok is False
    assert "「写入设备信息」、「Live Photo」" in result.error


def test_disabled_steps_are_not_blocked_by_a_missing_exiftool(tmp_path, monkeypatch):
    """Neither step enabled means ExifTool is nobody's problem -- run anyway.

    The precise claim is "not blocked *because of* ExifTool"; the general
    pipeline must keep working on a machine with no ExifTool at all.
    """
    _pin_diagnose(monkeypatch, BROKEN)
    cfg, src, recs = _records(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.steps.live_photo.enabled = False
    result = _preflight(cfg, src, recs, tmp_path)

    assert "ExifTool" not in result.error
    assert result.extra.get("runtime") is None
    assert result.ok is True


def test_a_usable_exiftool_blocks_nothing(tmp_path, monkeypatch):
    """The gate must not fire on a healthy machine -- that would block every run."""
    _pin_diagnose(monkeypatch, None)
    cfg, src, recs = _records(tmp_path)
    cfg.steps.device_metadata.enabled = True
    result = _preflight(cfg, src, recs, tmp_path)

    assert result.ok is True
    assert result.extra.get("runtime") is None
    # the run really proceeds: names were computed for every record
    assert set(result.basenames) == {str(r.source_path) for r in recs}
    assert all(stem for stem in result.basenames.values())


def test_an_empty_task_never_touches_the_gate(tmp_path, monkeypatch):
    """Nothing to process, nothing to refuse: an empty folder is not an error."""
    _pin_diagnose(monkeypatch, BROKEN)
    cfg, src, _ = _records(tmp_path)
    result = _preflight(cfg, src, [], tmp_path)

    assert result.ok is True
    assert result.extra.get("runtime") is None


def test_the_gate_runs_before_the_ffmpeg_check(tmp_path, monkeypatch):
    """Live Photo with neither runtime: the ExifTool answer comes first.

    The checks are ordered so the message names the fix that unblocks the most,
    and a test keeps that ordering from quietly swapping.
    """
    import app.core.ffmpeg_resolver as fr

    _pin_diagnose(monkeypatch, BROKEN)
    monkeypatch.setattr(fr, "resolve_ffmpeg", lambda: None)
    cfg, src, recs = _records(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.steps.live_photo.enabled = True
    result = _preflight(cfg, src, recs, tmp_path)

    assert result.ok is False
    assert result.extra.get("runtime") == "exiftool"
    assert "FFmpeg" not in result.error


def test_preflight_threads_portable_mode_into_the_diagnosis(tmp_path, monkeypatch):
    """A portable install resolves ExifTool from the app directory, not the user one.

    Dropping the flag would diagnose against the wrong search path and offer an
    install button for a tool that is already right there.
    """
    seen = _pin_diagnose(monkeypatch, None)
    cfg, src, recs = _records(tmp_path)
    cfg.runtime.portable_mode = True
    _preflight(cfg, src, recs, tmp_path)
    assert seen == [("exiftool", True)]

    seen.clear()
    cfg.runtime.portable_mode = False
    _preflight(cfg, src, recs, tmp_path)
    assert seen == [("exiftool", False)]


def test_an_earlier_refusal_keeps_its_own_message(tmp_path, monkeypatch):
    """Two problems, one run: preflight must report the first one it finds.

    The output-format check (1b) runs before the ExifTool gate (3b). If the
    gate jumped ahead it would replace "this PNG would be published as a .jpg"
    with "ExifTool is missing", and fixing the ExifTool would just produce the
    next failure with no clue about the first.
    """
    src = tmp_path / "in"
    src.mkdir()
    Image.new("RGB", (16, 16), (5, 5, 5)).save(src / "a.png")
    cfg = default_config()
    cfg.steps.hidden_image.enabled = False
    cfg.steps.reencode.enabled = False          # nothing re-encodes -> PNG passes through
    cfg.steps.device_metadata.enabled = True
    recs = to_records(collect_inputs([src], cfg))
    _pin_diagnose(monkeypatch, BROKEN)

    result = _preflight(cfg, src, recs, tmp_path)
    assert result.ok is False
    assert "non_jpeg" in result.extra                 # the format check owns this refusal
    assert result.extra.get("runtime") is None
    assert "ExifTool" not in result.error