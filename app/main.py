"""Application entrypoints."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch CLI or GUI.

    Examples:
      python -m app gui
      python -m app path/to/img -o out --no-provenance
      python -m app cli path/to/img -o out
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "gui":
        from app.gui.app import run_gui
        return run_gui([sys.argv[0], *args[1:]])
    if args and args[0] == "cli":
        from app.main_cli import main as cli_main
        return cli_main(args[1:])
    # Heuristic: if looks like processing args, use CLI; else GUI
    cli_flags = {"-h", "--help", "--version", "--list-steps"}
    if args and (args[0] in cli_flags or "-o" in args or "--output" in args or "--list-steps" in args or not args[0].startswith("-")):
        # bare path or explicit CLI flags
        if args[0] in cli_flags or "-o" in args or "--output" in args or "--list-steps" in args or PathLike(args[0]):
            from app.main_cli import main as cli_main
            return cli_main(args)
    from app.gui.app import run_gui
    return run_gui([sys.argv[0], *args])


def PathLike(value: str) -> bool:
    # treat non-flag first arg as input path for CLI
    return not value.startswith("-")


if __name__ == "__main__":
    raise SystemExit(main())
