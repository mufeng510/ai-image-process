"""Settings-related logic tests that do not require a display or Qt libs."""
from __future__ import annotations

from app.gui.naming_presets import NAMING_PRESETS, template_for_preset
from app.config.schema import default_config, AppConfig


def test_naming_presets_unique_keys():
    keys = [k for k, _label, _t in NAMING_PRESETS]
    assert len(keys) == len(set(keys))
    assert "custom" in keys
    assert "original" in keys


def test_template_for_preset():
    assert template_for_preset("number") == "IMG_{number}"
    assert template_for_preset("custom", "{date}_{original_name}") == "{date}_{original_name}"
    assert template_for_preset("custom", "") == "{original_name}"


def test_default_config_matches_settings_expectations():
    cfg = default_config()
    assert cfg.output.conflict_policy == "rename"
    assert cfg.steps.reencode.quality_min <= cfg.steps.reencode.quality_max
    assert cfg.runtime.worker_count == 1
    assert cfg.config_version >= 1


def test_config_roundtrip_for_settings_fields():
    cfg = default_config()
    cfg.naming.preset = "custom"
    cfg.naming.template = "{datetime}_{original_name}"
    cfg.steps.device_metadata.selection = "fixed"
    cfg.steps.device_metadata.fixed_device_id = "apple-iphone-15"
    cfg.paths.temp_dir = "/tmp/aip-temp"
    cfg.paths.log_dir = "/tmp/aip-logs"
    cfg.input.recurse_folders = True
    data = cfg.to_dict()
    cfg2 = AppConfig.from_dict(data)
    assert cfg2.naming.template == cfg.naming.template
    assert cfg2.steps.device_metadata.fixed_device_id == "apple-iphone-15"
    assert cfg2.paths.temp_dir == "/tmp/aip-temp"
    assert cfg2.input.recurse_folders is True
