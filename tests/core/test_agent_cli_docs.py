"""Keep the agent-facing documentation honest.

docs/agent-cli.md is what an agent reads when the skill sends it there, and the
skill is advertised purely on its description. Both are invisible to the test
suite otherwise: a config key renamed in schema.py would leave the doc naming
a setting that quietly does nothing, and --config drops unknown keys silently,
so the user's symptom would be "that option had no effect".

The guard is deliberately narrow -- first key of each row -- because rows
legitimately abbreviate the second half (``a / b``). Invented keys in the first
position are what actually mislead.
"""
from __future__ import annotations

import dataclasses as dc
import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "agent-cli.md"
SKILL = REPO / ".opencode" / "skills" / "ai-image-process" / "SKILL.md"

# ``steps.live_photo.enabled`` — a dotted path with no spaces or wildcards.
KEY_RE = re.compile(r"^[a-z_]+(?:\.[a-z_]+)+$")


def _config_paths() -> set[str]:
    """Every dotted path reachable from a default AppConfig.

    Walks an *instance*: a field declared with ``default_factory`` is not a
    class attribute, so ``getattr(cls, name)`` finds nothing and every nested
    section would look like a leaf.
    """
    from app.config.schema import default_config

    def walk(obj, prefix="") -> set[str]:
        out: set[str] = set()
        for f in dc.fields(obj):
            value = getattr(obj, f.name)
            path = f"{prefix}{f.name}"
            if dc.is_dataclass(value):
                out |= walk(value, f"{path}.")
            else:
                out.add(path)
        return out

    return walk(default_config())


def _doc_rows() -> list[tuple[int, str]]:
    """(line number, first cell) for the config-key table."""
    rows = []
    for n, line in enumerate(DOC.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| `"):
            continue
        cell = line.split("|")[1].strip().strip("`")
        # Only the documented config table uses ``| `key` | default |`` rows.
        if not cell.startswith(("input.", "output.", "naming.", "runtime.", "paths.",
                                "steps.", "config_version", "ui_language")):
            continue
        rows.append((n, cell))
    return rows


def test_doc_exists_and_is_substantial():
    assert DOC.is_file(), "docs/agent-cli.md is referenced by the skill; it must exist"
    assert len(DOC.read_text(encoding="utf-8")) > 2000


@pytest.mark.parametrize("line_no,cell", _doc_rows())
def test_every_documented_config_key_exists(line_no, cell):
    """Unknown keys in --config are dropped silently, so a stale doc entry reads
    to the user as "that setting did nothing". Each first-position key in the
    table must resolve to a real field."""
    known = _config_paths()
    for key in (k.strip() for k in cell.split("/")):
        if not KEY_RE.match(key):
            # Rows abbreviate the tail (``a / b``); only validate full paths.
            continue
        assert key in known, (
            f"docs/agent-cli.md:{line_no} documents {key!r}, which is not a field "
            f"of AppConfig -- --config would silently ignore it"
        )


def test_doc_covers_every_top_level_section():
    """Guards the other direction: a whole section renamed or dropped from the
    schema should not silently vanish from the reference. Top-level scalars
    (``config_version``) have no dotted child, so match on prefix, not on
    ``section.`` appearing anywhere."""
    documented = {
        key
        for _n, cell in _doc_rows()
        for key in (k.strip() for k in cell.split("/"))
    }
    missing = [
        section
        for section in sorted({p.split(".")[0] for p in _config_paths()})
        if not any(d == section or d.startswith(f"{section}.") for d in documented)
    ]
    assert not missing, f"docs/agent-cli.md never documents config section(s): {missing}"


def test_skill_frontmatter_is_advertisable():
    """A skill with no description is never advertised to the model, and one
    with no name shows up as its path-derived id. Both failures are silent."""
    assert SKILL.is_file(), "the skill is referenced in README; it must exist"
    text = SKILL.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    body = m.group(1)
    assert re.search(r"^name:\s*\S", body, re.M)
    description = re.search(r"^description:\s*(.+)$", body, re.M)
    assert description, "without a description the model never sees this skill"
    # The description is the only thing the model matches on, so it has to say
    # *when* to reach for it, not just what the tool is.
    assert re.search(r"[Uu]se when", description.group(1))


def test_skill_points_at_the_doc_rather_than_duplicating_it():
    """The flag list belongs to --help, which cannot drift. If the skill ever
    starts repeating it, the two copies will disagree and the agent will trust
    the stale one."""
    text = SKILL.read_text(encoding="utf-8")
    assert "docs/agent-cli.md" in text
    assert "--help" in text
    # A handful of flag mentions is fine; a transcription is not.
    assert text.count("|--") == 0, "the skill must not contain a parameter table"