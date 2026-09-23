"""Tests for the in-app dependency installer (no network access needed)."""
import builtins
import sys
from unittest.mock import patch

import pytest

from app.core import dependency_installer as di
from app.core.wheel_installer import WheelInstallError


def test_feature_specs_cover_both_features():
    """Both remove-ai-watermarks-backed features have an install method."""
    assert "provenance" in di.FEATURE_SPECS
    assert "visible" in di.FEATURE_SPECS
    assert di.FEATURE_SPECS["provenance"].startswith("remove-ai-watermarks")
    assert "[visible]" in di.FEATURE_SPECS["visible"]


def test_feature_spec_unknown_raises():
    with pytest.raises(ValueError):
        di.feature_spec("nope")


def test_ensure_runtime_site_prepends_once(tmp_path, monkeypatch):
    monkeypatch.setattr(di, "user_data_dir", lambda portable_mode=False: tmp_path)
    site = di.ensure_runtime_site()
    try:
        assert site.name == di.SITE_DIR_NAME
        assert site.exists()
        assert sys.path[0] == str(site)
        di.ensure_runtime_site()
        assert sys.path.count(str(site)) == 1
    finally:
        if str(site) in sys.path:
            sys.path.remove(str(site))


def test_install_specs_dev_uses_running_interpreter(monkeypatch):
    recorded = {}

    def fake_run(base, specs, target, log):
        recorded.update(base=list(base), specs=list(specs), target=target)

    monkeypatch.setattr(di, "is_frozen", lambda: False)
    monkeypatch.setattr(di, "_run_pip_subprocess", fake_run)
    di.install_specs(["some-pkg>=1.0"])
    assert recorded["base"] == [sys.executable]
    assert recorded["specs"] == ["some-pkg>=1.0"]
    assert recorded["target"] is None


def test_install_feature_frozen_uses_wheel_installer(monkeypatch, tmp_path):
    calls = {}
    site = tmp_path / "site"
    monkeypatch.setattr(di, "is_frozen", lambda: True)
    monkeypatch.setattr(di, "ensure_runtime_site", lambda portable_mode=False: site)

    def fake_wheel_install(specs, target, log):
        calls["specs"] = list(specs)
        calls["target"] = target

    monkeypatch.setattr(di, "install_specs_to_target", fake_wheel_install)
    di.install_feature("visible", portable_mode=False)
    assert calls["specs"] == [di.FEATURE_SPECS["visible"]]
    assert calls["target"] == site


def test_install_feature_frozen_falls_back_to_system_python(monkeypatch, tmp_path):
    recorded = {}
    site = tmp_path / "site"
    monkeypatch.setattr(di, "is_frozen", lambda: True)
    monkeypatch.setattr(di, "ensure_runtime_site", lambda portable_mode=False: site)

    def raise_wheel_error(specs, target, log):
        raise WheelInstallError("boom")

    monkeypatch.setattr(di, "install_specs_to_target", raise_wheel_error)
    monkeypatch.setattr(di, "_find_system_python", lambda: ["py", "-3.12"])
    monkeypatch.setattr(
        di,
        "_run_pip_subprocess",
        lambda base, specs, target, log: recorded.update(
            base=list(base), specs=list(specs), target=target
        ),
    )
    di.install_specs(["some-pkg>=1.0"])
    assert recorded["base"] == ["py", "-3.12"]
    assert recorded["specs"] == ["some-pkg>=1.0"]
    assert recorded["target"] == site


def test_install_specs_frozen_without_python_has_clear_error(monkeypatch, tmp_path):
    site = tmp_path / "site"
    monkeypatch.setattr(di, "is_frozen", lambda: True)
    monkeypatch.setattr(di, "ensure_runtime_site", lambda portable_mode=False: site)

    def raise_wheel_error(specs, target, log):
        raise WheelInstallError("wheel installer failed")

    monkeypatch.setattr(di, "install_specs_to_target", raise_wheel_error)
    monkeypatch.setattr(di, "_find_system_python", lambda: None)
    with pytest.raises(RuntimeError) as excinfo:
        di.install_specs(["some-pkg>=1.0"])
    assert "手动安装" in str(excinfo.value)
    assert "some-pkg>=1.0" in str(excinfo.value)


def test_install_specs_frozen_subprocess_fallback_failure_appends_manual_cmd(monkeypatch, tmp_path):
    """System python found but _run_pip_subprocess fails; final error includes manual command."""
    site = tmp_path / "site"
    monkeypatch.setattr(di, "is_frozen", lambda: True)
    monkeypatch.setattr(di, "ensure_runtime_site", lambda portable_mode=False: site)

    def raise_wheel_error(specs, target, log):
        raise WheelInstallError("wheel installer failed")

    monkeypatch.setattr(di, "install_specs_to_target", raise_wheel_error)
    monkeypatch.setattr(di, "_find_system_python", lambda: ["py", "-3.12"])

    def raise_subprocess_error(base, specs, target, log):
        raise RuntimeError("sub fail")

    monkeypatch.setattr(di, "_run_pip_subprocess", raise_subprocess_error)

    with pytest.raises(RuntimeError) as excinfo:
        di.install_specs(["some-pkg>=1.0"])
    msg = str(excinfo.value)
    assert "手动安装" in msg
    assert "pip install" in msg
    assert "some-pkg>=1.0" in msg


def test_target_args_force_wheels_and_target(tmp_path):
    args = di._target_args(tmp_path / "site")
    assert "--only-binary=:all:" in args
    assert "--target" in args
    assert "--upgrade" in args


def test_find_system_python_takes_first_match(monkeypatch):
    monkeypatch.setattr(
        di, "_system_python_candidates", lambda: [["python3.12"], ["python3"]]
    )
    monkeypatch.setattr(
        di, "_check_system_python", lambda cand: cand == ["python3.12"]
    )
    assert di._find_system_python() == ["python3.12"]


def test_find_system_python_none_when_no_match(monkeypatch):
    monkeypatch.setattr(di, "_check_system_python", lambda cand: False)
    assert di._find_system_python() is None


def test_check_system_python_rejects_version_mismatch(monkeypatch):
    class Proc:
        returncode = 0
        stdout = "3.99.0\n"

    monkeypatch.setattr(di.subprocess, "run", lambda *a, **k: Proc())
    assert di._check_system_python(["python3"]) is False


def test_check_system_python_accepts_matching_version(monkeypatch):
    class Proc:
        returncode = 0
        stdout = f"{sys.version_info.major}.{sys.version_info.minor}\n"

    monkeypatch.setattr(di.subprocess, "run", lambda *a, **k: Proc())
    assert di._check_system_python(["python3"]) is True


def test_install_feature_logs_progress():
    lines: list[str] = []
    with patch.object(di, "is_frozen", lambda: False), patch.object(
        di, "_run_pip_subprocess"
    ):
        di.install_feature("provenance", log=lines.append)
    assert any("remove-ai-watermarks" in line for line in lines)
    assert any("完成" in line for line in lines)