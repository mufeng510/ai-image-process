"""Config load/save/import/export."""
from __future__ import annotations

import json
from pathlib import Path

from app.config.paths import user_config_dir
from app.config.schema import AppConfig, default_config


class ConfigManager:
    def __init__(self, path: Path | None = None, portable_mode: bool = False) -> None:
        self.path = path or (user_config_dir(portable_mode) / "config.json")

    def load(self) -> AppConfig:
        if not self.path.exists():
            cfg = default_config()
            self.save(cfg)
            return cfg
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return AppConfig.from_dict(data)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n"
        self.path.write_text(payload, encoding="utf-8")

    def export_to(self, dest: Path, config: AppConfig) -> None:
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n"
        dest.write_text(payload, encoding="utf-8")

    def import_from(self, src: Path) -> AppConfig:
        data = json.loads(src.read_text(encoding="utf-8"))
        cfg = AppConfig.from_dict(data)
        self.save(cfg)
        return cfg

    def reset(self) -> AppConfig:
        cfg = default_config()
        self.save(cfg)
        return cfg
