"""AI video provider factory (vendor-neutral)."""
from __future__ import annotations

from pathlib import Path

from app.config.schema import AIVideoConfig
from app.core.live_photo.providers.base import AIVideoProvider, GenericHttpAIVideoProvider, MockAIVideoProvider


def build_ai_provider(cfg: AIVideoConfig, *, mock_fixture: Path | None = None) -> AIVideoProvider:
    if (cfg.provider or "").strip().lower() == "mock" and mock_fixture is not None:
        return MockAIVideoProvider(mock_fixture, endpoint=cfg.endpoint, model=cfg.model,
                                   api_key=cfg.api_key, timeout_seconds=cfg.timeout_seconds,
                                   retry_count=cfg.retry_count, prompt=_full_prompt(cfg),
                                   duration_seconds=cfg.duration_seconds)
    prompt = _full_prompt(cfg)
    return GenericHttpAIVideoProvider(
        endpoint=cfg.endpoint.strip(), model=cfg.model.strip(), api_key=cfg.api_key,
        timeout_seconds=int(cfg.timeout_seconds), retry_count=int(cfg.retry_count),
        prompt=prompt, duration_seconds=float(cfg.duration_seconds),
    )


def _full_prompt(cfg: AIVideoConfig) -> str:
    base = (cfg.prompt or "").strip()
    extra = (cfg.extra_prompt or "").strip()
    if base and extra:
        return base + "\n\nAdditional direction:\n" + extra
    return base or extra
