"""Hand the CLI to an AI Agent: where the skill is, how to install it.

Deliberately does not install anything into the agent's own configuration.
Writing into another tool's config directory is a decision the user should
make, not a side effect of opening a settings dialog -- so this module only
*describes* the one-liner, and the agent (or the user) runs it.

Two facts shape the layout:

* ``~/.agents/skills`` is where the skill ecosystem converges for global
  installs, and OpenCode reads it as well as its native
  ``~/.config/opencode/skills``. Installing there makes one copy work across
  Claude Code, Cursor, Codex and OpenCode instead of only in this one harness.
* The portable bundle ships its own installer, so the command must work from an
  unzipped directory with no repository and no Node/npx available.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SKILL_ID = "ai-image-process"

# Agent-readable locations, most preferred first. Only the first is used for
# installation; the rest are checked when reporting "already installed", since
# an earlier version of this app installed into the OpenCode-native one.
GLOBAL_SKILL_DIRS: tuple[str, ...] = (
    "~/.agents/skills",
    "~/.config/opencode/skills",
    "~/.claude/skills",
)


def app_root() -> Path:
    """Directory holding this installation (the bundle root, or the repo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def global_skills_dir() -> Path:
    """Where a global install goes. Overridable so tests never touch $HOME."""
    override = os.environ.get("AGENT_SKILLS_HOME")
    if override:
        return Path(override).expanduser()
    return Path(GLOBAL_SKILL_DIRS[0]).expanduser()


def bundled_skill_dir() -> Path | None:
    """The copy shipped inside this installation, if the build included it."""
    candidate = app_root() / ".opencode" / "skills" / SKILL_ID
    return candidate if (candidate / "SKILL.md").is_file() else None


def bundled_installer() -> Path | None:
    """The bundled install_agent_skill.sh, if the build included it."""
    candidate = app_root() / "scripts" / "install_agent_skill.sh"
    return candidate if candidate.is_file() else None


def installed_skill_path() -> Path | None:
    """First already-installed SKILL.md found in a known agent directory.

    Checks the configured install location first, so an AGENT_SKILLS_HOME
    redirect (tests, packagers) is reflected here instead of the panel claiming
    "not installed" about a directory the installer just wrote to.
    """
    seen: list[Path] = [global_skills_dir()]
    seen.extend(Path(raw).expanduser() for raw in GLOBAL_SKILL_DIRS)
    for base in seen:
        candidate = base / SKILL_ID / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


def is_installed() -> bool:
    return installed_skill_path() is not None


def cli_binary() -> Path:
    """The console entry point, which is what an agent must invoke."""
    name = "AI-Image-Process-CLI.exe" if sys.platform.startswith("win") else "AI-Image-Process-CLI"
    return app_root() / name


def cli_invocation() -> str:
    """How an agent should actually invoke this build.

    A development checkout has no console binary -- the packaged one lives
    under dist/. Telling an agent to run a path that does not exist is worse
    than saying nothing, so fall back to the source entry point.
    """
    binary = cli_binary()
    if binary.is_file():
        return str(binary)
    return "python -m app cli   # 在源码仓库里运行（便携包请改用 AI-Image-Process-CLI）"


def install_command() -> str:
    """A single copy-pasteable command that installs the skill globally.

    Falls back to copying the bundled skill directory directly when the build
    did not ship the installer script, so the button is never dead.
    """
    script = bundled_installer()
    if script is not None:
        if sys.platform.startswith("win"):
            return f'powershell -NoProfile -Command "& \'{script}\'"'
        return f'sh "{script}"'
    src = bundled_skill_dir()
    if src is None:
        return ""
    target = global_skills_dir() / SKILL_ID
    if sys.platform.startswith("win"):
        return (
            f'powershell -NoProfile -Command "Copy-Item -Recurse -Force '
            f"'{src}' '{target}'\""
        )
    return f'mkdir -p "{target}" && cp -R "{src}/." "{target}/"'


def agent_prompt() -> str:
    """Paste-into-the-chat text: ask the agent to do the install and verify it.

    Written for an agent that has never seen this app, so it states the binary
    path and asks for a verification step -- an install that silently produced
    an undiscoverable skill is the failure mode worth guarding against.
    """
    script = bundled_installer()
    src = bundled_skill_dir()
    if script is None and src is None:
        return ""

    target_dir = global_skills_dir() / SKILL_ID
    lines = [
        "请把这个应用的 Agent Skill 安装到你的 skills 目录，并确认它能被加载。",
        "",
        "1) 执行这条命令（安装 Skill 到 " + str(global_skills_dir()) + "）：",
        f"   {install_command()}",
        "",
        f"2) 确认安装结果：SKILL.md 与 references/agent-cli.md 都在 {target_dir} 下。",
        "",
        "3) 之后处理图片时使用这个命令行入口（不要用 GUI 那个，它会忽略参数）：",
        f"   {cli_invocation()}",
    ]
    if script is None and src is not None:
        lines.insert(2, f"   （或直接把这个目录整个复制到 {target_dir}：{src}）\n")
    lines += [
        "",
        f"这个应用在：{app_root()}",
        "它的完整参数见 references/agent-cli.md；批量处理前先用 --dry-run 看计划。",
    ]
    return "\n".join(lines)


def status_text() -> tuple[str, str]:
    """(headline, detail) for the settings panel."""
    found = installed_skill_path()
    if found is not None:
        return ("✓ 已安装到 Agent 的 skills 目录", str(found))
    if bundled_skill_dir() is not None:
        return ("○ 尚未全局安装", f"本机已内置：{bundled_skill_dir()}")
    return ("✗ 本次构建未包含 Skill", "重新下载便携包可获得该文件")