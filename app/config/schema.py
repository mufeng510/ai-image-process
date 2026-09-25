"""Versioned application configuration schema."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


CONFIG_VERSION = 2

DEFAULT_AI_VIDEO_PROMPT = (
    "Create a subtle, realistic Live Photo motion from the provided image. "
    "Preserve the subject's identity, shape, proportions, color, material, texture, "
    "composition, perspective, and overall visual appearance exactly. "
    "Motion should be minimal and natural, similar to a real handheld camera moment. "
    "Do not introduce new objects. Do not remove existing objects. Do not redesign the subject. "
    "Do not change the product shape, color, material, texture, or proportions. "
    "Avoid dramatic camera movement, strong lighting changes, artificial transitions, or cinematic effects. "
    "The first/anchor frame should remain visually consistent with the provided image."
)


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
class VisibleWatermarkStepConfig:
    enabled: bool = False  # opt-in: needs the optional remove-ai-watermarks[visible] extra
    backend: str = "auto"  # auto|cv2|migan|lama (migan/lama need a model download)


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
class RotateCropStepConfig:
    enabled: bool = False
    min_angle: float = -2.0
    max_angle: float = 2.0


@dataclass
class HiddenImageStepConfig:
    enabled: bool = False
    library_dir: str = ""
    opacity: float = 0.02  # 0..0.5 fraction (default 2%)


@dataclass
class LocalMotionConfig:
    duration_seconds: float = 3.0
    fps: int = 30
    motion_strength: float = 0.06  # relative zoom/pan amplitude, subtle


@dataclass
class AIVideoConfig:
    provider: str = ""
    model: str = ""
    endpoint: str = ""
    api_key: str = ""
    prompt: str = DEFAULT_AI_VIDEO_PROMPT
    extra_prompt: str = ""
    duration_seconds: float = 3.0
    timeout_seconds: int = 300
    retry_count: int = 2


@dataclass
class LivePhotoStepConfig:
    enabled: bool = False
    video_source: str = "local_motion"  # local_motion|ai_video
    local_motion: LocalMotionConfig = field(default_factory=LocalMotionConfig)
    ai_video: AIVideoConfig = field(default_factory=AIVideoConfig)


@dataclass
class DeduplicateStepConfig:
    enabled: bool = True
    algorithm: str = "md5"  # md5, sha1, sha256


@dataclass
class StepsConfig:
    deduplicate: DeduplicateStepConfig = field(default_factory=DeduplicateStepConfig)
    provenance_cleanup: ProvenanceStepConfig = field(default_factory=ProvenanceStepConfig)
    visible_watermark: VisibleWatermarkStepConfig = field(default_factory=VisibleWatermarkStepConfig)
    reencode: ReencodeStepConfig = field(default_factory=ReencodeStepConfig)
    device_metadata: DeviceMetadataStepConfig = field(default_factory=DeviceMetadataStepConfig)
    rename: SimpleStepConfig = field(default_factory=SimpleStepConfig)
    rotate_crop: RotateCropStepConfig = field(default_factory=RotateCropStepConfig)
    hidden_image: HiddenImageStepConfig = field(default_factory=HiddenImageStepConfig)
    live_photo: LivePhotoStepConfig = field(default_factory=LivePhotoStepConfig)
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
            deduplicate=DeduplicateStepConfig(**_filter(steps_raw.get("deduplicate", {}), DeduplicateStepConfig)),
            provenance_cleanup=ProvenanceStepConfig(**_filter(steps_raw.get("provenance_cleanup", {}), ProvenanceStepConfig)),
            visible_watermark=VisibleWatermarkStepConfig(**_filter(steps_raw.get("visible_watermark", {}), VisibleWatermarkStepConfig)),
            reencode=ReencodeStepConfig(**_filter(steps_raw.get("reencode", {}), ReencodeStepConfig)),
            device_metadata=DeviceMetadataStepConfig(**_filter(steps_raw.get("device_metadata", {}), DeviceMetadataStepConfig)),
            rename=SimpleStepConfig(**_filter(steps_raw.get("rename", {}), SimpleStepConfig)),
            rotate_crop=RotateCropStepConfig(**_filter(steps_raw.get("rotate_crop", {}), RotateCropStepConfig)),
            hidden_image=HiddenImageStepConfig(**_filter(steps_raw.get("hidden_image", {}), HiddenImageStepConfig)),
            live_photo=_parse_live_photo(steps_raw.get("live_photo", {})),
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


def _parse_live_photo(raw: dict[str, Any]) -> LivePhotoStepConfig:
    raw = dict(raw or {})
    local_raw = raw.get("local_motion", {}) or {}
    ai_raw = raw.get("ai_video", {}) or {}
    local = LocalMotionConfig(**{k: v for k, v in local_raw.items() if k in LocalMotionConfig.__dataclass_fields__})
    ai = AIVideoConfig(**{k: v for k, v in ai_raw.items() if k in AIVideoConfig.__dataclass_fields__})
    base = {k: v for k, v in raw.items() if k in ("enabled", "video_source")}
    cfg = LivePhotoStepConfig(**base) if base else LivePhotoStepConfig()
    if "enabled" in raw:
        cfg.enabled = bool(raw["enabled"])
    if "video_source" in raw:
        cfg.video_source = str(raw["video_source"] or "local_motion")
    cfg.local_motion = local
    cfg.ai_video = ai
    return cfg


def _filter(raw: dict[str, Any], cls: type) -> dict[str, Any]:
    return {k: v for k, v in (raw or {}).items() if k in cls.__dataclass_fields__}


def default_config() -> AppConfig:
    return AppConfig()


def migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    version = int(data.get("config_version", 1))
    if version < 1:
        data["config_version"] = 1
    steps = data.setdefault("steps", {})
    # v2: new steps default OFF so upgrades never change existing behavior.
    if version < 2:
        steps.setdefault("rotate_crop", {"enabled": False, "min_angle": -2.0, "max_angle": 2.0})
        steps.setdefault("hidden_image", {"enabled": False, "library_dir": "", "opacity": 0.02})
        steps.setdefault(
            "live_photo",
            {
                "enabled": False,
                "video_source": "local_motion",
                "local_motion": {"duration_seconds": 3.0, "fps": 30, "motion_strength": 0.06},
                "ai_video": {
                    "provider": "",
                    "model": "",
                    "endpoint": "",
                    "api_key": "",
                    "prompt": DEFAULT_AI_VIDEO_PROMPT,
                    "extra_prompt": "",
                    "duration_seconds": 3.0,
                    "timeout_seconds": 300,
                    "retry_count": 2,
                },
            },
        )
        # ensure ai prompt default exists even if live_photo block existed partially
        lp = steps.get("live_photo", {})
        if isinstance(lp, dict):
            ai = lp.setdefault("ai_video", {})
            if isinstance(ai, dict) and not ai.get("prompt"):
                ai["prompt"] = DEFAULT_AI_VIDEO_PROMPT
    data["config_version"] = max(version, CONFIG_VERSION)
    return data
