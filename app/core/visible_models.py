"""Visible-watermark backend/model management for the remove-ai-watermarks extra.

The learned fill backends (migan/lama) download their ONNX weights from
Hugging Face on first use; nothing is bundled with this app. This module
lets the GUI surface package/model status and run a user-initiated
download that pre-seeds the exact cache the backend reads.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import dataclass
from typing import Callable

PACKAGE_NAME = "remove-ai-watermarks"

# (hf_repo_id, filename) for each learned backend; mirrors
# remove_ai_watermarks.region_eraser so the cache check and the download
# land on the same files the backend resolves through huggingface_hub.
LEARNED_BACKENDS: dict[str, tuple[str, str]] = {
    "migan": ("andraniksargsyan/migan", "migan.onnx"),
    "lama": ("Carve/LaMa-ONNX", "lama_fp32.onnx"),
}

FILL_BACKENDS = ("auto", "cv2", "migan", "lama")


@dataclass
class PackageStatus:
    importable: bool
    version: str | None
    visible_ready: bool  # package + cv2 pixel runtime importable
    onnx_ready: bool  # onnxruntime importable (required by migan/lama)


def package_status() -> PackageStatus:
    importable = importlib.util.find_spec("remove_ai_watermarks") is not None
    version: str | None = None
    visible_ready = False
    onnx_ready = False
    if importable:
        try:
            version = importlib.metadata.version(PACKAGE_NAME)
        except importlib.metadata.PackageNotFoundError:
            version = None
        try:
            importlib.import_module("remove_ai_watermarks.api")
            importlib.import_module("cv2")
            visible_ready = True
        except Exception:  # noqa: BLE001
            visible_ready = False
        try:
            importlib.import_module("onnxruntime")
            onnx_ready = True
        except Exception:  # noqa: BLE001
            onnx_ready = False
    return PackageStatus(importable=importable, version=version, visible_ready=visible_ready, onnx_ready=onnx_ready)


def model_status(backend: str) -> str:
    """Return one of "not_installed", "not_downloaded", "downloaded", "unknown".

    "not_installed" means huggingface-hub is unavailable (the migan/lama
    extras pull it in), so neither check nor download is possible here.
    """
    if backend not in LEARNED_BACKENDS:
        raise ValueError(f"backend {backend!r} has no downloadable model")
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:  # noqa: BLE001
        return "not_installed"
    repo_id, filename = LEARNED_BACKENDS[backend]
    try:
        cached = try_to_load_from_cache(repo_id=repo_id, filename=filename)
    except Exception:  # noqa: BLE001
        return "unknown"
    return "downloaded" if cached else "not_downloaded"


def download_model(backend: str, log: Callable[[str], None] | None = None) -> str:
    """Pre-download the learned backend weights into the huggingface_hub cache.

    User-invoked from the settings page; nothing downloads silently. Returns
    the cached file path. The backend itself reuses this cache on first use.
    """
    if backend not in LEARNED_BACKENDS:
        raise ValueError(f"backend {backend!r} has no downloadable model")
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "huggingface-hub 未安装。请先安装对应后端支持："
            f'pip install "{PACKAGE_NAME}[{backend}]"'
        ) from exc

    repo_id, filename = LEARNED_BACKENDS[backend]
    if log:
        log(f"开始下载 {repo_id}/{filename} …")
    path = hf_hub_download(repo_id=repo_id, filename=filename)
    if log:
        log(f"模型已缓存：{path}")
    return str(path)


def install_hint(backend: str) -> str:
    return f'pip install "{PACKAGE_NAME}[{backend}]"'
