from app.config.schema import AppConfig, default_config


def test_roundtrip():
    cfg = default_config()
    data = cfg.to_dict()
    cfg2 = AppConfig.from_dict(data)
    assert cfg2.config_version == 1
    assert cfg2.steps.reencode.quality_min == 96
    assert cfg2.steps.device_metadata.software_tag == "iOS Camera"
