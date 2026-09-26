"""CLI entry for core processing (no GUI)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config.manager import ConfigManager
from app.config.schema import default_config
from app.core.dependency_installer import ensure_runtime_site
from app.core.models import CancelToken, ProgressEvent
from app.core.pipeline import DEFAULT_STEP_ORDER, build_default_registry, run_job
from app.version import __version__


def _progress(ev: ProgressEvent) -> None:
    print(f"[{ev.kind.value}] {ev.message or ''} file={ev.file_path or ''} step={ev.step_id or ''} {ev.index}/{ev.total}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai-image-process", description="AI Image Process core CLI")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("inputs", nargs="*", help="input files and/or folders")
    p.add_argument("-o", "--output", required=False, default=None, help="output directory")
    p.add_argument("--config", help="optional config json path")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for deterministic device/quality")
    p.add_argument("--no-provenance", action="store_true", help="disable provenance cleanup step")
    p.add_argument("--enable-rotate-crop", action="store_true", help="enable rotate/crop step")
    p.add_argument("--min-angle", type=float, default=None, help="rotate_crop min angle")
    p.add_argument("--max-angle", type=float, default=None, help="rotate_crop max angle")
    p.add_argument("--hidden-library", default=None, help="enable hidden_image step with this library dir")
    p.add_argument("--hidden-opacity", type=float, default=None, help="hidden overlay opacity 0..0.5")
    p.add_argument("--enable-live-photo", action="store_true", help="enable live photo step")
    p.add_argument("--video-source", choices=["local_motion", "ai_video"], default=None)
    p.add_argument("--list-steps", action="store_true", help="list registry steps in order and exit")
    p.add_argument("--prepare-iphone-import", default=None,
                   help="prepare a dedicated i4Tools live-photo import dir from outputs and print guided steps")
    p.add_argument("--json-summary", action="store_true", help="print job summary JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_steps:
        reg = build_default_registry()
        for sid in DEFAULT_STEP_ORDER:
            try:
                step = reg.get(sid)
                print(f"{step.id}\t{step.title}")
            except KeyError:
                print(f"{sid}\t(missing)")
        return 0
    if not args.inputs or not args.output:
        build_parser().error("inputs and -o/--output are required (unless --list-steps)")
    # Pick up in-app installed packages before any lazy import of the
    # optional remove_ai_watermarks dependency.
    ensure_runtime_site()
    if args.config:
        cfg = ConfigManager(Path(args.config)).load()
    else:
        cfg = default_config()
    if args.no_provenance:
        cfg.steps.provenance_cleanup.enabled = False
    if args.enable_rotate_crop:
        cfg.steps.rotate_crop.enabled = True
    if args.min_angle is not None:
        cfg.steps.rotate_crop.min_angle = args.min_angle
    if args.max_angle is not None:
        cfg.steps.rotate_crop.max_angle = args.max_angle
    if args.hidden_library:
        cfg.steps.hidden_image.enabled = True
        cfg.steps.hidden_image.library_dir = args.hidden_library
    if args.hidden_opacity is not None:
        cfg.steps.hidden_image.enabled = True
        cfg.steps.hidden_image.opacity = args.hidden_opacity
    if args.enable_live_photo:
        cfg.steps.live_photo.enabled = True
    if args.video_source:
        cfg.steps.live_photo.enabled = True
        cfg.steps.live_photo.video_source = args.video_source
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
        "preflight_failed": result.preflight_failed,
        "preflight_error": result.preflight_error,
        "steps": DEFAULT_STEP_ORDER,
        "failures": [
            {"file": str(f.source_path), "error": f.error} for f in result.failed
        ],
    }
    if args.prepare_iphone_import and result.success:
        from app.core.iphone_import.i4tools import I4ToolsImporter

        pairs = []
        for f in result.success:
            outs = getattr(f, "output_path", None)
            # recover bundle mov sibling
            jpg = Path(str(outs)) if outs else None
            mov = jpg.with_suffix(".mov") if jpg else None
            pairs.append((jpg, mov if mov and mov.exists() else None))
        pairs = [(j, m) for j, m in pairs if j and j.exists()]
        imp = I4ToolsImporter()
        prepared = imp.prepare(pairs, Path(args.prepare_iphone_import))
        res = imp.import_live_photos(prepared)
        summary["iphone_import"] = {"prepared_dir": str(prepared), "message": res.message}
        print(res.message)
    if args.json_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        if result.preflight_failed:
            print(f"preflight failed: {result.preflight_error}")
        print(f"done success={summary['success']} failed={summary['failed']} cancelled={summary['cancelled']}")
        for f in result.failed:
            print(f"FAIL {f.source_path}: {f.error}")
    if result.preflight_failed:
        return 2
    return 1 if result.failed and not result.success else 0


if __name__ == "__main__":
    sys.exit(main())
