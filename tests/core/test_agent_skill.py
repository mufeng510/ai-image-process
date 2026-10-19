"""The agent-integration panel: describe the install, never perform it.

The asymmetry is the point. An "install" button here that wrote into the agent's
own configuration would be a settings dialog reaching into another application's
files; the contract is that this module only *produces* the command, and the
user or the agent decides to run it. These tests pin that contract as much as
they pin the strings.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.core import agent_skill

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "scripts" / "install_agent_skill.sh"


@pytest.fixture(autouse=True)
def _fake_skill_home(tmp_path, monkeypatch):
    """Redirect the global target so nothing here can touch the real $HOME.

    The directory is deliberately NOT created: several tests assert that asking
    this module for information does not bring the directory into existence.
    """
    home = tmp_path / "agent-home"
    fake_user_home = tmp_path / "user-home"
    fake_user_home.mkdir()
    monkeypatch.setenv("AGENT_SKILLS_HOME", str(home))
    monkeypatch.setenv("HOME", str(fake_user_home))
    return home


def _fake_installed(home: Path) -> Path:
    d = home / agent_skill.SKILL_ID
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("---\nname: X\ndescription: y\n---\n", encoding="utf-8")
    return d / "SKILL.md"


def test_nothing_writes_to_the_agent_directory_on_import():
    """The module exists to be *read* by the GUI. Importing it, or asking it
    for status, must not create a skills directory."""
    home = Path(__import__("os").environ["AGENT_SKILLS_HOME"])
    agent_skill.status_text()
    agent_skill.install_command()
    agent_skill.agent_prompt()
    assert not home.exists(), "describing the install must not create anything"


def test_status_is_not_installed_when_nothing_is_there(_fake_skill_home):
    assert agent_skill.is_installed() is False
    headline, _detail = agent_skill.status_text()
    assert "尚未全局安装" in headline or "未包含" in headline


def test_status_reports_an_existing_install_in_any_known_directory(tmp_path, _fake_skill_home):
    _fake_installed(_fake_skill_home)
    assert agent_skill.is_installed() is True
    headline, detail = agent_skill.status_text()
    assert "已安装" in headline
    assert detail.endswith("SKILL.md")


def test_install_command_points_at_the_bundled_script_and_is_absolute():
    """An agent runs this from an arbitrary cwd; a relative path is a coin
    flip."""
    cmd = agent_skill.install_command()
    assert cmd, "the repository ships an installer, so a command must exist"
    assert str(INSTALLER) in cmd
    assert Path(INSTALLER).is_absolute()


def test_install_command_falls_back_to_copying_the_directory(tmp_path, monkeypatch):
    """A build without the script must still yield a usable command rather than
    a disabled button."""
    monkeypatch.setattr(agent_skill, "bundled_installer", lambda: None)
    cmd = agent_skill.install_command()
    assert "cp -R" in cmd or "Copy-Item" in cmd
    assert agent_skill.SKILL_ID in cmd


def test_install_command_is_empty_when_nothing_is_shipped(monkeypatch):
    monkeypatch.setattr(agent_skill, "bundled_installer", lambda: None)
    monkeypatch.setattr(agent_skill, "bundled_skill_dir", lambda: None)
    assert agent_skill.install_command() == ""
    assert agent_skill.agent_prompt() == ""


def test_agent_prompt_carries_the_three_things_an_agent_needs():
    """Path to run, where the skill must land, and how to verify it -- an
    install that silently produced an undiscoverable skill is the failure worth
    guarding against."""
    text = agent_skill.agent_prompt()
    assert agent_skill.install_command() in text
    assert str(agent_skill.global_skills_dir() / agent_skill.SKILL_ID) in text
    assert "references/agent-cli.md" in text
    assert "--dry-run" in text


def test_cli_invocation_never_names_a_binary_that_is_missing(tmp_path, monkeypatch):
    """A development checkout has no console binary. Handing an agent a path
    that does not exist wastes a turn and teaches it to distrust the app.

    Assert on the command itself, not on the whole string: the source fallback
    mentions the packaged name in a trailing hint on purpose.
    """
    fake_root = tmp_path / "checkout"
    fake_root.mkdir()
    monkeypatch.setattr(agent_skill, "app_root", lambda: fake_root)

    missing = fake_root / "AI-Image-Process-CLI"
    assert agent_skill.cli_invocation().split()[0] != str(missing)

    missing.write_text("#!/bin/sh\n")
    assert agent_skill.cli_invocation() == str(missing)


def test_global_dir_prefers_the_cross_agent_location():
    """~/.agents/skills is the ecosystem-wide location and is read by OpenCode
    too, so one copy serves Claude Code, Cursor, Codex and OpenCode."""
    assert agent_skill.GLOBAL_SKILL_DIRS[0] == "~/.agents/skills"


def test_installer_script_actually_installs_both_files(tmp_path):
    """End to end against the real script: SKILL.md *and* the reference must
    land, or the skill points at a file the agent cannot read."""
    target = tmp_path / "dest"
    p = subprocess.run(
        ["bash", str(INSTALLER), "--target", str(target)],
        capture_output=True, text=True, timeout=120,
    )
    assert p.returncode == 0, p.stderr
    installed = target / agent_skill.SKILL_ID
    assert (installed / "SKILL.md").is_file()
    assert (installed / "references" / "agent-cli.md").is_file()


def test_installer_prefers_the_cross_agent_home_when_set(tmp_path, monkeypatch):
    """AGENT_SKILLS_HOME is how the GUI and the tests redirect the target; a
    script that ignored it would write to the developer's real home."""
    fake = tmp_path / "redirected"
    env = {**dict(__import__("os").environ), "AGENT_SKILLS_HOME": str(fake)}
    p = subprocess.run(
        ["bash", str(INSTALLER)],
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert p.returncode == 0, p.stderr
    assert (fake / agent_skill.SKILL_ID / "SKILL.md").is_file()


def test_gui_buttons_are_disabled_when_the_build_has_no_skill(monkeypatch, qapp):  # noqa
    """A button that copies an empty string is worse than a disabled one."""
    monkeypatch.setattr(agent_skill, "bundled_installer", lambda: None)
    monkeypatch.setattr(agent_skill, "bundled_skill_dir", lambda: None)
    from app.config.schema import default_config
    from app.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(default_config())
    try:
        dlg._refresh_agent_skill_status()
        assert dlg.btn_copy_install_cmd.isEnabled() is False
        assert dlg.btn_copy_agent_prompt.isEnabled() is False
    finally:
        dlg.close()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="posix shell script")
def test_installer_is_shipped_with_a_shebang_and_is_executable():
    assert INSTALLER.read_text(encoding="utf-8").startswith("#!")

@pytest.fixture(scope="module")
def qapp():
    """Qt needs one application object per process; the GUI tests share one."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
