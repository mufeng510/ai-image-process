"""CLI surface: refusing an empty job, machine-readable stdout, and dry runs.

The CLI is the seam other programs drive (exit code in, JSON out), so the
promises tested here are the ones a caller depends on:

* an empty job refuses with exit code 2 and a reason, instead of exiting 0
  with success=0 and reading as "done";
* with --json-summary stdout carries the JSON document *alone* (progress is
  rerouted to stderr), so `... | jq` works without scraping around log lines;
* every success line names the file that landed on disk;
* --dry-run reports the plan and writes nothing at all.

Each test builds its own images under tmp_path — nothing here reads from
/tmp, which is volatile on this machine.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PIL import Image

from app.config.schema import default_config
from app.core.models import ProgressKind
from app.core.output_format import OUTPUT_JPG_EXT
from app.core.pipeline import run_job
from app.main_cli import main as cli_main

# A progress line looks like "[job_started] ..." — built from the enum so the
# guard below cannot drift away from what the printer actually emits.
PROGRESS_LINE = re.compile(
    r"^\[(?:" + "|".join(k.value for k in ProgressKind) + r")\]"
)
DONE_LINE = re.compile(r"^done success=(\d+) failed=(\d+) cancelled=(True|False)$")


def _image(path: Path, color=(10, 40, 60)) -> Path:
    """A real 32x24 JPEG (not a PNG wearing a .jpg name: output_write checks)."""
    Image.new("RGB", (32, 24), color).save(path, "JPEG")
    return path


def _inputs(tmp_path: Path, count: int = 1) -> Path:
    src = tmp_path / "in"
    src.mkdir(exist_ok=True)
    for i in range(count):
        _image(src / f"photo{i}.jpg", color=(10 + i, 40, 60))
    return src


def _config_file(tmp_path: Path) -> Path:
    """default_config() minus the steps that need optional external binaries,
    with the scratch dir pinned to tmp_path so a test never touches the real
    user temp dir."""
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False  # needs remove_ai_watermarks
    cfg.steps.device_metadata.enabled = False      # needs exiftool
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg.to_dict(), ensure_ascii=False), encoding="utf-8")
    return path


def _pipeline_config(tmp_path: Path):
    """Same trimmed config for the direct run_job() calls (section 5)."""
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.device_metadata.enabled = False
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    return cfg


@pytest.fixture(autouse=True)
def _no_runtime_site(monkeypatch):
    """ensure_runtime_site() creates a per-user directory and prepends it to
    sys.path. That behaviour has its own tests (test_dependency_installer.py);
    here it would only pollute the real home directory."""
    import app.main_cli as main_cli

    monkeypatch.setattr(main_cli, "ensure_runtime_site", lambda *a, **k: None)


@pytest.fixture
def cli(tmp_path, capsys):
    """Run the CLI in-process. Returns (exit_code, captured).

    Each call drains capsys, so a test that invokes the CLI twice must read
    the two results separately. --config is appended automatically to keep the
    job's scratch directory inside tmp_path.
    """
    config = _config_file(tmp_path)

    def run(*argv: str):
        return cli_main([*argv, "--config", str(config)]), capsys.readouterr()

    return run


# --- 1. an empty job is refused, not reported as success ---------------------


def test_missing_path_exits_2_and_writes_nothing(cli, tmp_path):
    """A typo'd path used to exit 0 with success=0, which reads as a
    successful run to any caller checking the exit code. It must be exit 2,
    and it must not create the output folder either."""
    out = tmp_path / "exports"
    rc, captured = cli(str(tmp_path / "does-not-exist"), "-o", str(out))
    assert rc == 2
    assert "输入路径不存在" in captured.out
    assert str(tmp_path / "does-not-exist") in captured.out  # names the bad path
    assert not out.exists(), "a refused job must leave no output folder behind"
    assert list(tmp_path.rglob(f"*{OUTPUT_JPG_EXT}")) == []  # not a single image anywhere


def test_directory_without_images_exits_2(cli, tmp_path):
    """The directory exists but holds nothing processable: a different refusal
    from a missing path, and the message has to say which one it is."""
    empty = tmp_path / "no-images"
    empty.mkdir()
    (empty / "notes.txt").write_text("not an image", encoding="utf-8")
    out = tmp_path / "exports"
    rc, captured = cli(str(empty), "-o", str(out))
    assert rc == 2
    assert "没有可处理的图片" in captured.out
    assert "输入路径不存在" not in captured.out  # the paths did exist
    assert str(empty) in captured.out  # tells the user what was scanned
    assert not out.exists()


@pytest.mark.parametrize("kind", ["missing", "no-images"])
def test_empty_job_json_summary_is_a_parseable_refusal(cli, tmp_path, kind):
    """--json-summary callers branch on exit code *and* preflight_failed, so the
    refusal must arrive as a valid JSON document on stdout — not as a human
    sentence a caller has to string-match."""
    if kind == "missing":
        target = tmp_path / "does-not-exist"
    else:
        target = tmp_path / "no-images"
        target.mkdir()
        (target / "notes.txt").write_text("not an image", encoding="utf-8")
    rc, captured = cli(str(target), "-o", str(tmp_path / "exports"), "--json-summary")
    assert rc == 2
    summary = json.loads(captured.out)  # whole stdout is one JSON document
    assert summary["preflight_failed"] is True
    assert summary["success"] == 0 and summary["failed"] == 0
    assert summary["outputs"] == [] and summary["failures"] == []
    expected = "输入路径不存在" if kind == "missing" else "没有可处理的图片"
    assert expected in summary["preflight_error"]


# --- 2. --json-summary keeps stdout machine-readable --------------------------


def test_json_summary_sends_progress_to_stderr_only(cli, tmp_path):
    """`ai-image-process ... --json-summary | jq` only works if progress never
    touches stdout. Progress lines must show up on stderr instead — dropped
    entirely would lose the diagnostics the CLI used to print."""
    src, out = _inputs(tmp_path), tmp_path / "exports"
    rc, captured = cli(str(src), "-o", str(out), "--json-summary")
    assert rc == 0
    summary = json.loads(captured.out)  # implies stdout holds nothing else
    leaked = [ln for ln in captured.out.splitlines() if PROGRESS_LINE.match(ln)]
    assert leaked == [], f"progress leaked into stdout: {leaked}"
    assert PROGRESS_LINE.match(captured.err.splitlines()[0]), captured.err[:200]
    assert any("job_started" in ln for ln in captured.err.splitlines())
    for entry in summary["outputs"]:
        assert set(entry) == {"source", "output"}
        produced = Path(entry["output"])
        assert produced.is_file() and produced.suffix == OUTPUT_JPG_EXT


# --- 3. the summary names what was produced -----------------------------------


def test_summary_outputs_point_at_real_files(cli, tmp_path):
    """A caller must not have to diff the filesystem to learn what it got: each
    success entry pairs the input it came from with the file on disk."""
    src, out = _inputs(tmp_path, count=2), tmp_path / "exports"
    rc, captured = cli(str(src), "-o", str(out), "--json-summary")
    assert rc == 0
    summary = json.loads(captured.out)
    assert summary["success"] == 2
    assert len(summary["outputs"]) == summary["success"]
    produced = {e["output"] for e in summary["outputs"]}
    assert len(produced) == 2  # distinct files, not the same one twice
    assert {e["source"] for e in summary["outputs"]} == {
        str(src / "photo0.jpg"), str(src / "photo1.jpg")
    }
    for entry in summary["outputs"]:
        assert Path(entry["output"]).is_file()
    # Everything lands inside the directory the user picked, never next to
    # the inputs (per-run sub-folder).
    assert all(Path(p).is_relative_to(out) for p in produced)


# --- 4. --dry-run reports a plan and writes nothing --------------------------


def test_dry_run_reports_plan_and_touches_no_files(cli, tmp_path):
    """Dry run is a preview: it must answer "would this work, and where would it
    write" without producing a single byte. Exit 0 because the *plan* is valid;
    success stays 0 because nothing succeeded."""
    src, out = _inputs(tmp_path, count=2), tmp_path / "exports"
    rc, captured = cli(str(src), "-o", str(out), "--dry-run", "--json-summary")
    assert rc == 0
    summary = json.loads(captured.out)
    assert summary["dry_run"] is True
    assert summary["success"] == 0 and summary["failed"] == 0
    assert summary["preflight_failed"] is False  # the plan itself passed preflight
    assert summary["planned_input_count"] == 2  # matches the images on disk
    planned = summary["planned_output_dir"]
    assert planned, "a dry run without a planned directory is useless to a caller"
    assert Path(planned).parent == out  # the per-run leaf under the chosen root
    # output_write is the last step, so a dry run may legitimately never create
    # the folder; what it must never do is leave files in it.
    assert not out.exists() or list(out.iterdir()) == []


def test_dry_run_human_line_states_nothing_was_written(cli, tmp_path):
    """The non-JSON dry run is used interactively: the line has to say the plan
    passed and that no file was produced, otherwise it looks like a real run
    that quietly found nothing to do."""
    src, out = _inputs(tmp_path), tmp_path / "exports"
    rc, captured = cli(str(src), "-o", str(out), "--dry-run")
    assert rc == 0
    assert "dry run" in captured.out
    assert "1" in captured.out  # the planned file count
    assert "未写入任何文件" in captured.out
    assert not out.exists() or list(out.iterdir()) == []


# --- 5. the pipeline's dry_run flag, below the CLI ---------------------------


def test_run_job_dry_run_stops_before_the_run_folder_claim(tmp_path):
    """The promise is stronger than "writes no image": the return happens
    *before* the atomic run-folder mkdir, so even the output directory the job
    would have used does not come into existence."""
    src, exports = _inputs(tmp_path, count=2), tmp_path / "exports"
    result = run_job(_pipeline_config(tmp_path), [src], output_dir=exports,
                     seed=1, temp_base=tmp_path / "tmp", dry_run=True)
    assert result.dry_run is True
    assert isinstance(result.planned_output_dir, Path)
    assert result.planned_output_dir.parent == exports
    assert result.planned_input_count == 2
    assert (result.success_count, result.failure_count) == (0, 0)
    assert result.preflight_failed is False
    assert not exports.exists(), "a dry run must not even claim the run folder"


def test_run_job_without_dry_run_writes_the_files(tmp_path):
    """Control for the test above: same config, dry_run off, the plan must
    actually happen — otherwise "nothing was written" proves nothing."""
    src, exports = _inputs(tmp_path, count=2), tmp_path / "exports"
    result = run_job(_pipeline_config(tmp_path), [src], output_dir=exports,
                     seed=1, temp_base=tmp_path / "tmp", dry_run=False)
    assert result.dry_run is False and result.planned_output_dir is None
    assert result.planned_input_count == 0
    assert (result.success_count, result.failure_count) == (2, 0)
    leaves = [p for p in exports.iterdir() if p.is_dir()]
    assert len(leaves) == 1, "the run folder the dry run refused to claim"
    assert sorted(p.name for p in leaves[0].glob(f"*{OUTPUT_JPG_EXT}")) == [
        f"photo0{OUTPUT_JPG_EXT}", f"photo1{OUTPUT_JPG_EXT}"]
    assert len({str(f.output_path) for f in result.success}) == 2
    for f in result.success:
        assert Path(f.output_path).is_file() and f.output_path.suffix == OUTPUT_JPG_EXT


# --- 6. regressions: the non-JSON path must behave exactly as before --------


def test_progress_still_goes_to_stdout_without_json_summary(cli, tmp_path):
    """Only the JSON mode was supposed to move progress to stderr; a plain run
    still writes it where a human (and `| tee log.txt`) expects to find it."""
    src, out = _inputs(tmp_path), tmp_path / "exports"
    rc, captured = cli(str(src), "-o", str(out))
    assert rc == 0
    kinds = [ln.split("]", 1)[0][1:] for ln in captured.out.splitlines()
             if PROGRESS_LINE.match(ln)]
    assert "job_started" in kinds and "file_succeeded" in kinds and "job_finished" in kinds
    assert captured.err == ""


def test_done_line_format_is_unchanged(cli, tmp_path):
    """Scripts parse this exact line. Adding the outputs list to the JSON
    summary must not alter the human summary, whose last line stays the
    done/tally line."""
    src, out = _inputs(tmp_path), tmp_path / "exports"
    rc, captured = cli(str(src), "-o", str(out))
    assert rc == 0
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    match = DONE_LINE.match(lines[-1])
    assert match, f"last line changed shape: {lines[-1]!r}"
    assert (match.group(1), match.group(2), match.group(3)) == ("1", "0", "False")
    assert not any(ln.startswith("FAIL") for ln in lines)


# --- 7. the iPhone import feature is GUI-only --------------------------------


def test_cli_has_no_iphone_import_flag():
    """The import button is a GUI hint; the CLI exposes no flag for it, and a
    retired flag must fail loudly instead of being silently accepted."""
    from app.main_cli import build_parser

    opts = {a.option_strings[0] for a in build_parser()._actions if a.option_strings}
    assert "--prepare-iphone-import" not in opts
    with pytest.raises(SystemExit):
        build_parser().parse_args(["in", "-o", "out", "--prepare-iphone-import"])


def test_run_leaves_no_iphone_import_section_in_the_summary(cli, tmp_path):
    src, out = _inputs(tmp_path), tmp_path / "exports"
    rc, captured = cli(str(src), "-o", str(out), "--json-summary")
    assert rc == 0
    summary = json.loads(captured.out)
    assert "iphone_import" not in summary
    assert "iPhone" not in captured.out and "iPhone" not in captured.err
