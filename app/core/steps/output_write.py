"""Write final output file(s) with conflict policy; Live Photo commits atomically."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config.schema import AppConfig
from app.core.conflicts import ConflictPolicy, resolve_output_path
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


def _resolve_bundle(dest_jpg: Path, dest_mov: Path, policy: ConflictPolicy):
    """Treat jpg+mov as one bundle: rename together, skip together, overwrite together."""
    jpg_exists = dest_jpg.exists()
    mov_exists = dest_mov.exists()
    if not jpg_exists and not mov_exists:
        return dest_jpg, dest_mov
    if policy == ConflictPolicy.OVERWRITE:
        return dest_jpg, dest_mov
    if policy == ConflictPolicy.SKIP:
        return None, None
    # rename: shared new stem (bounded attempts; conflicts resolved by policy)
    stem, n = dest_jpg.stem, 1
    while n <= 10000:
        cand_jpg = dest_jpg.parent / f"{stem}_{n}.jpg"
        cand_mov = dest_mov.parent / f"{stem}_{n}.mov"
        if not cand_jpg.exists() and not cand_mov.exists():
            return cand_jpg, cand_mov
        n += 1
    raise RuntimeError(f"too many conflicting outputs for bundle stem {stem!r}")


class OutputWriteStep(Step):
    id = "output_write"
    title = "输出处理结果"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.output_write.enabled)

    def run(self, ctx: StepContext) -> StepResult:
        try:
            out_dir = Path(ctx.resources["output_dir"]).expanduser().resolve()
            if ctx.config.output.auto_create_directory:
                out_dir.mkdir(parents=True, exist_ok=True)
            elif not out_dir.exists():
                return StepResult(self.id, False, error=f"output directory missing: {out_dir}")

            policy = ConflictPolicy(ctx.config.output.conflict_policy)
            bundle = getattr(ctx.record, "live_photo_bundle", None)

            if bundle is not None and ctx.config.steps.live_photo.enabled:
                stem = ctx.record.output_stem or Path(bundle.photo_path).stem
                dest_jpg = out_dir / f"{stem}.jpg"
                dest_mov = out_dir / f"{stem}.mov"
                final_jpg, final_mov = _resolve_bundle(dest_jpg, dest_mov, policy)
                if final_jpg is None:
                    return StepResult(self.id, True, message="skipped existing bundle")
                for final in (final_jpg, final_mov):
                    if ctx.config.output.preserve_originals:
                        try:
                            if final.resolve() == ctx.record.source_path.resolve():
                                return StepResult(self.id, False,
                                                  error="refusing to overwrite source while preserve_originals=true")
                        except OSError:
                            pass
                # Atomic-ish commit: stage to unique temp names first, then rename.
                # No half-committed bundle may remain on failure. Rollback only
                # removes files this run created (pre-existing user files under
                # overwrite policy are never unlinked by rollback).
                import uuid as _uuid

                tag = _uuid.uuid4().hex[:8]
                tmp_jpg = final_jpg.with_name(f"{final_jpg.stem}.part-{tag}.jpg")
                tmp_mov = final_mov.with_name(f"{final_mov.stem}.part-{tag}.mov")
                for t in (tmp_jpg, tmp_mov):
                    if t.exists():
                        t.unlink()
                jpg_preexisted = final_jpg.exists()
                try:
                    shutil.copy2(bundle.photo_path, tmp_jpg)
                    shutil.copy2(bundle.video_path, tmp_mov)
                    tmp_jpg.replace(final_jpg)
                    tmp_mov.replace(final_mov)
                except Exception:
                    for t in (tmp_jpg, tmp_mov):
                        try:
                            if t.exists():
                                t.unlink()
                        except OSError:
                            pass
                    # roll back a half-renamed bundle, but never a file that
                    # already existed before this run
                    try:
                        if final_jpg.exists() and not final_mov.exists() and not jpg_preexisted:
                            final_jpg.unlink()
                    except OSError:
                        pass
                    raise
                ctx.record.output_path = final_jpg
                ctx.record.output_paths = [final_jpg, final_mov]
                created = ctx.resources.setdefault("created_outputs", [])
                created.extend([final_jpg, final_mov])
                return StepResult(self.id, True, message=f"committed bundle {final_jpg.name}+{final_mov.name}")

            name = ctx.record.output_name or f"{ctx.record.original_name}.jpg"
            dest = out_dir / name
            final = resolve_output_path(dest, policy)
            if final is None:
                return StepResult(self.id, True, message="skipped existing")

            # safety: never write onto source if preserve originals
            if ctx.config.output.preserve_originals:
                try:
                    if final.resolve() == ctx.record.source_path.resolve():
                        return StepResult(self.id, False, error="refusing to overwrite source while preserve_originals=true")
                except OSError:
                    pass

            shutil.copy2(ctx.record.current_path, final)
            ctx.record.output_path = final
            ctx.record.output_paths = [final]
            created = ctx.resources.setdefault("created_outputs", [])
            created.append(final)
            return StepResult(self.id, True, message=str(final))
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
