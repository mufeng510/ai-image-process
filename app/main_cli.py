"""CLI entry for core processing (no GUI)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config.manager import ConfigManager
from app.config.schema import default_config
from app.core.models import CancelToken, ProgressEvent
from app.core.pipeline import run_job
from app.version import __version__


def _progress(ev: ProgressEvent) -> None:
    print(f"[{ev.kind.value}] {ev.message or ''} file={ev.file_path or ''} step={ev.step_id or ''} {ev.index}/{ev.total}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai-image-process", description="AI Image Process core CLI")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("inputs", nargs="+", help="input files and/or folders")
    p.add_argument("-o", "--output", required=True, help="output directory")
    p.add_argument("--config", help="optional config json path")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for deterministic device/quality")
    p.add_argument("--no-provenance", action="store_true", help="disable provenance cleanup step")
    p.add_argument("--json-summary", action="store_true", help="print job summary JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.config:
        cfg = ConfigManager(Path(args.config)).load()
    else:
        cfg = default_config()
    if args.no_provenance:
        cfg.steps.provenance_cleanup.enabled = False
    cfg.output.directory = args.output

    result = run_job(
        cfg,
        [Path(x) for x in args.inputs],
        output_dir=args.output,
        progress_cb=_progress,
        cancel_token=CancelToken(),
        seed=args.seed,
    )
    summary = {
        "job_id": result.job_id,
        "success": result.success_count,
        "failed": result.failure_count,
        "cancelled": result.cancelled,
        "failures": [
            {"file": str(f.source_path), "error": f.error} for f in result.failed
        ],
    }
    if args.json_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"done success={summary['success']} failed={summary['failed']} cancelled={summary['cancelled']}")
        for f in result.failed:
            print(f"FAIL {f.source_path}: {f.error}")
    return 1 if result.failed and not result.success else 0


if __name__ == "__main__":
    sys.exit(main())
