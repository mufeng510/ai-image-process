from app.config.schema import CONFIG_VERSION, AppConfig, default_config


def test_roundtrip():
    cfg = default_config()
    data = cfg.to_dict()
    cfg2 = AppConfig.from_dict(data)
    assert cfg2.config_version == CONFIG_VERSION
    assert cfg2.steps.reencode.quality_min == 96
    assert cfg2.steps.device_metadata.software_tag == "iOS Camera"
    # every step defaults ON except visible_watermark (needs the optional extra)
    assert cfg2.steps.rotate_crop.enabled is True
    assert cfg2.steps.hidden_image.enabled is True
    assert cfg2.steps.live_photo.enabled is True
    assert cfg2.steps.visible_watermark.enabled is False


def test_migrate_v1_adds_new_steps_off():
    cfg = AppConfig.from_dict({"config_version": 1, "steps": {}})
    assert cfg.steps.rotate_crop.enabled is False
    assert cfg.steps.hidden_image.enabled is False
    assert cfg.steps.live_photo.enabled is False
    assert "Live Photo" in (cfg.steps.live_photo.ai_video.prompt or "Live Photo")
