"""Versioned application configuration schema."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


CONFIG_VERSION = 1


@dataclass
class OutputConfig:
    directory: str = ""
    use_source_directory: bool = False
    auto_create_directory: bool = True
    conflict_policy: str = "rename"  # overwrite|skip|rename
    preserve_originals: bool = True
    allow_overwrite_originals: bool = False


@dataclass
class NamingConfig:
    preset: str = "original"
    template: str = "{original_name}"
    number_start: int = 1
    number_width: int = 3


@dataclass
class ProvenanceStepConfig:
    enabled: bool = True
    mode: str = "metadata"


@dataclass
class ReencodeStepConfig:
    enabled: bool = True
    format: str = "jpeg"
    quality_min: int = 96
    quality_max: int = 99
    apply_srgb_icc: bool = True


@dataclass
class DeviceMetadataStepConfig:
    enabled: bool = True
    selection: str = "random"  # random|fixed
    fixed_device_id: str | None = None
    randomize_datetime: bool = True
    offset_min_minutes: int = 10
    offset_max_minutes: int = 10000
    software_tag: str = "iOS Camera"


@dataclass
class SimpleStepConfig:
    enabled: bool = True


@dataclass
class StepsConfig:
    provenance_cleanup: ProvenanceStepConfig = field(default_factory=ProvenanceStepConfig)
    reencode: ReencodeStepConfig = field(default_factory=ReencodeStepConfig)
    device_metadata: DeviceMetadataStepConfig = field(default_factory=DeviceMetadataStepConfig)
    rename: SimpleStepConfig = field(default_factory=SimpleStepConfig)
    output_write: SimpleStepConfig = field(default_factory=SimpleStepConfig)


@dataclass
class InputConfig:
    recurse_folders: bool = False
    extensions: list[str] = field(default_factory=lambda: ["jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"])


@dataclass
class RuntimeConfig:
    cleanup_temp_on_success: bool = True
    cleanup_temp_on_startup: bool = True
    worker_count: int = 1
    log_level: str = "info"
    portable_mode: bool = False


@dataclass
class PathsConfig:
    temp_dir: str = ""
    log_dir: str = ""


@dataclass
class AppConfig:
    config_version: int = CONFIG_VERSION
    ui_language: str = "zh-CN"
    output: OutputConfig = field(default_factory=OutputConfig)
    naming: NamingConfig = field(default_factory=NamingConfig)
    steps: StepsConfig = field(default_factory=StepsConfig)
    input: InputConfig = field(default_factory=InputConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        data = migrate_config(deepcopy(data))
        output = OutputConfig(**{k: v for k, v in data.get("output", {}).items() if k in OutputConfig.__dataclass_fields__})
        naming = NamingConfig(**{k: v for k, v in data.get("naming", {}).items() if k in NamingConfig.__dataclass_fields__})
        steps_raw = data.get("steps", {})
        steps = StepsConfig(
            provenance_cleanup=ProvenanceStepConfig(**_filter(steps_raw.get("provenance_cleanup", {}), ProvenanceStepConfig)),
            reencode=ReencodeStepConfig(**_filter(steps_raw.get("reencode", {}), ReencodeStepConfig)),
            device_metadata=DeviceMetadataStepConfig(**_filter(steps_raw.get("device_metadata", {}), DeviceMetadataStepConfig)),
            rename=SimpleStepConfig(**_filter(steps_raw.get("rename", {}), SimpleStepConfig)),
            output_write=SimpleStepConfig(**_filter(steps_raw.get("output_write", {}), SimpleStepConfig)),
        )
        input_cfg = InputConfig(**_filter(data.get("input", {}), InputConfig))
        runtime = RuntimeConfig(**_filter(data.get("runtime", {}), RuntimeConfig))
        paths = PathsConfig(**_filter(data.get("paths", {}), PathsConfig))
        return cls(
            config_version=int(data.get("config_version", CONFIG_VERSION)),
            ui_language=str(data.get("ui_language", "zh-CN")),
            output=output,
            naming=naming,
            steps=steps,
            input=input_cfg,
            runtime=runtime,
            paths=paths,
        )


def _filter(raw: dict[str, Any], cls: type) -> dict[str, Any]:
    return {k: v for k, v in (raw or {}).items() if k in cls.__dataclass_fields__}


def default_config() -> AppConfig:
    return AppConfig()


def migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    version = int(data.get("config_version", 1))
    if version < 1:
        data["config_version"] = 1
    # future migrations go here
    data["config_version"] = max(version, CONFIG_VERSION)
    return data
