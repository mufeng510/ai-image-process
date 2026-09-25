"""Task preflight: validate everything before any output/deletion."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.config.schema import AppConfig
from app.core.errors import to_user_message
from app.core.hidden_images import (
    assign_hidden_images,
    check_hidden_library_path_safety,
    scan_hidden_library,
)
from app.core.image_metadata import extract_hidden_metadata_source
from app.core.models import FileRecord


@dataclass
class PreflightResult:
    ok: bool
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    basenames: dict[str, str] = field(default_factory=dict)  # str(source) -> stem
    hidden_mapping: dict[str, Path] = field(default_factory=dict)
    hidden_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    dedup_removed: int = 0


def _input_dirs(inputs: Sequence[Path]) -> list[Path]:
    dirs: list[Path] = []
    for p in inputs:
        pp = Path(p)
        dirs.append(pp if pp.is_dir() else pp.parent)
    # dedupe, drop missing
    seen: list[Path] = []
    for d in dirs:
        try:
            r = d.expanduser().resolve()
        except OSError:
            r = d.expanduser().absolute()
        if r not in seen:
            seen.append(r)
    return seen


def _compute_basenames(config: AppConfig, records: list[FileRecord]) -> dict[str, str]:
    from datetime import datetime

    from app.core.naming import render_filename

    out: dict[str, str] = {}
    if not config.steps.rename.enabled:
        # Rename OFF (legacy behavior): keep original stems; still shared
        # by JPG+MOV and de-duplicated within the batch below.
        for rec in records:
            out[str(rec.source_path)] = rec.original_name
    else:
        when = datetime.now()
        for rec in records:
            number = config.naming.number_start + rec.index - 1
            try:
                name = render_filename(
                    config.naming.template,
                    original_name=rec.original_name,
                    original_ext=rec.original_ext,
                    when=rec.capture_dt or when,
                    number=number,
                    number_width=config.naming.number_width,
                )
            except Exception as exc:
                raise ValueError(f"命名模板无效：{exc}") from exc
            stem = name.rsplit(".", 1)[0] if "." in name else name
            out[str(rec.source_path)] = stem
    # ensure uniqueness of stems within the batch (rename policy handles disk
    # conflicts at commit time; in-batch collision gets numeric suffix)
    seen: dict[str, int] = {}
    for k, stem in list(out.items()):
        if stem in seen:
            seen[stem] += 1
            out[k] = f"{stem}_{seen[stem]}"
        else:
            seen[stem] = 0
    return out


def run_preflight(
    config: AppConfig,
    inputs: Sequence[Path],
    records: list[FileRecord],
    output_dir: Path,
    rng: random.Random,
    *,
    emit=None,
) -> PreflightResult:
    def log(msg: str) -> None:
        if emit:
            emit(msg)

    # 1. enabled steps
    hidden_on = bool(config.steps.hidden_image.enabled)
    live_on = bool(config.steps.live_photo.enabled)

    # 2. basenames right after dedup (records already deduped by caller)
    try:
        basenames = _compute_basenames(config, records)
    except Exception as exc:
        return PreflightResult(ok=False, error=to_user_message(exc))

    # 3. hidden image checks
    hidden_mapping: dict[str, Path] = {}
    hidden_metadata: dict[str, dict[str, Any]] = {}
    if hidden_on and records:
        lib_raw = (config.steps.hidden_image.library_dir or "").strip()
        if not lib_raw:
            return PreflightResult(ok=False, error="已启用「隐藏图片」，但尚未配置隐藏图片库目录。请选择隐藏图片库后再开始任务。")
        lib = Path(lib_raw).expanduser()
        if not lib.is_dir():
            return PreflightResult(ok=False, error=f"隐藏图片库目录不存在：{lib}")
        unsafe = check_hidden_library_path_safety(lib, _input_dirs(inputs), output_dir)
        if unsafe:
            return PreflightResult(ok=False, error=unsafe)
        # Symlink guard: a link inside an input dir (esp. with recursion on)
        # may resolve into the library even when top-level dirs look safe.
        # Such files must never enter the job as deletable inputs.
        from app.core.hidden_images import _is_within as _within

        try:
            lib_resolved = lib.resolve()
        except OSError:
            lib_resolved = lib.absolute()
        for rec in records:
            try:
                resolved = rec.source_path.resolve()
            except OSError:
                continue
            if _within(resolved, lib_resolved):
                return PreflightResult(
                    ok=False,
                    error=f"输入文件位于隐藏图片库内（可能经由符号链接），存在误删风险，已拒绝启动：{rec.source_path}",
                )
        opacity = float(config.steps.hidden_image.opacity)
        if not (0 < opacity <= 0.5):
            return PreflightResult(ok=False, error=f"隐藏图片不透明度不合法：{opacity}（应为 0~0.5，默认 0.02）")
        exts = {e.lower().lstrip(".") for e in config.input.extensions}
        log("[Preflight] Checking hidden image library...")
        pool = scan_hidden_library(lib, exts)
        log(f"[Preflight] Hidden images: {len(pool)} / {len(records)}")
        need = len(records)
        have = len(pool)
        if have < need:
            missing = need - have
            return PreflightResult(
                ok=False,
                error=(
                    "隐藏图片库中的可用图片数量不足。\n\n"
                    f"本次需要：\n{need} 张\n\n"
                    f"当前可用：\n{have} 张\n\n"
                    f"缺少：\n{missing} 张\n\n"
                    "请补充隐藏图片后再开始任务。"
                ),
                extra={"need": need, "have": have, "missing": missing},
            )
        plan = assign_hidden_images([r.source_path for r in records], pool, rng)
        hidden_mapping = plan.mapping
        for src_str, hpath in hidden_mapping.items():
            try:
                hidden_metadata[src_str] = extract_hidden_metadata_source(hpath)
            except Exception:
                hidden_metadata[src_str] = {}

    # 4. live photo checks
    if live_on:
        from app.core.ffmpeg_resolver import resolve_ffmpeg

        if resolve_ffmpeg() is None:
            # Both sources need ffmpeg: local motion to generate, AI path to
            # normalize the downloaded video into the standard MOV.
            return PreflightResult(
                ok=False,
                error="已启用 Live Photo，但未找到 FFmpeg（本地生成与 AI 视频规范化都需要）。普通图片处理不受影响；请提供 FFmpeg 后再启用 Live Photo。",
            )
        mode = config.steps.live_photo.video_source
        if mode not in ("local_motion", "ai_video"):
            return PreflightResult(ok=False, error=f"未知的 Live Photo 视频来源：{mode}")
        if mode == "ai_video":
            ai = config.steps.live_photo.ai_video
            if not ai.provider.strip() or not ai.endpoint.strip() or not ai.model.strip():
                return PreflightResult(
                    ok=False,
                    error="已启用 Live Photo（AI 视频），但 Provider/Model/Endpoint 尚未配置完整。请先配置后再开始任务。",
                )
            if not ai.api_key.strip():
                return PreflightResult(ok=False, error="已启用 Live Photo（AI 视频），但尚未配置 API Key。")

    # 5. rotate/crop validation
    if config.steps.rotate_crop.enabled:
        lo = float(config.steps.rotate_crop.min_angle)
        hi = float(config.steps.rotate_crop.max_angle)
        if lo > hi:
            return PreflightResult(ok=False, error=f"旋转角度不合法：最小值 {lo}° 大于最大值 {hi}°。")

    return PreflightResult(
        ok=True,
        basenames=basenames,
        hidden_mapping=hidden_mapping,
        hidden_metadata=hidden_metadata,
    )
