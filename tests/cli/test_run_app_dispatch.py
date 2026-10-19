"""The packaged dispatcher picks a personality from argv[0].

Both executables boot the same compiled entry (PyInstaller hands every EXE
the same ``a.scripts``), so this decision is the only thing standing between
a user and a GUI window when they asked for automation. Getting it wrong is
silent: the GUI just opens, or the CLI prints nothing.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_app_under_test", Path(__file__).resolve().parents[2] / "scripts" / "run_app.py"
)
run_app = importlib.util.module_from_spec(_SPEC)
sys.modules["run_app_under_test"] = run_app
_SPEC.loader.exec_module(run_app)


@pytest.mark.parametrize(
    "argv0, expected",
    [
        ("AI-Image-Process-CLI", True),      # the console sibling
        ("/opt/app/AI-Image-Process-CLI", True),
        ("ai-image-process-cli", True),       # case-insensitive
        ("AI-Image-Process", False),          # GUI: name must not contain "cli"
        ("/home/u/app/AI-Image-Process", False),
        ("AI-Image-Process-CLI.exe", True),   # the Windows name
    ],
)
def test_personality_follows_the_executable_name(monkeypatch, argv0, expected):
    """The GUI name contains no "cli", so the substring test cannot misfire on
    it -- that is the whole reason the sibling is spelled with a dash."""
    monkeypatch.setattr(sys, "argv", [argv0])
    monkeypatch.delenv("AI_IMAGE_PROCESS_ENTRY", raising=False)
    assert run_app._wants_cli() is expected


def test_env_var_overrides_the_name(monkeypatch):
    """Running from source the script is called run_app.py, which says neither
    personality; the env var is how a developer chooses."""
    monkeypatch.setattr(sys, "argv", ["scripts/run_app.py"])
    monkeypatch.setenv("AI_IMAGE_PROCESS_ENTRY", "cli")
    assert run_app._wants_cli() is True
    monkeypatch.setenv("AI_IMAGE_PROCESS_ENTRY", "gui")
    assert run_app._wants_cli() is False


def test_unrelated_env_value_falls_back_to_the_name(monkeypatch):
    """A typo in the override must not silently pick a personality."""
    monkeypatch.setattr(sys, "argv", ["AI-Image-Process-CLI"])
    monkeypatch.setenv("AI_IMAGE_PROCESS_ENTRY", "yes")
    assert run_app._wants_cli() is True


def test_dispatch_sends_cli_args_to_the_cli(monkeypatch):
    """End of the chain: the CLI must receive argv *minus* the program name,
    otherwise every run would parse the exe path as an input path."""
    seen: list[list[str]] = []

    import app.main_cli as cli_mod

    monkeypatch.setattr(sys, "argv", ["/app/AI-Image-Process-CLI", "./in", "-o", "./out"])
    monkeypatch.setattr(cli_mod, "main", lambda argv: seen.append(list(argv)) or 0)
    assert run_app.main() == 0
    assert seen == [["./in", "-o", "./out"]]


def test_dispatch_keeps_argv_untouched_for_the_gui(monkeypatch):
    """The GUI entry has always received sys.argv *including* argv[0]; changing
    that would alter what the window manager sees."""
    seen: list[list[str]] = []

    import app.gui.app as gui_mod

    monkeypatch.setattr(sys, "argv", ["/app/AI-Image-Process", "extra"])
    monkeypatch.setattr(gui_mod, "run_gui", lambda argv: seen.append(list(argv)) or 0)
    assert run_app.main() == 0
    assert seen == [["/app/AI-Image-Process", "extra"]]