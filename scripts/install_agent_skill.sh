#!/usr/bin/env bash
# Install the AI Image Process agent skill so an agent can drive the CLI.
#
# The skill lives in this repo at .opencode/skills/ai-image-process/. Working
# *inside* this checkout needs no install: OpenCode discovers project skills by
# walking up from the working directory. This script is for every other case --
# driving the packaged CLI from an unrelated project, or driving it from the
# portable build, which ships this same script alongside its own copy of the
# skill (see scripts/build_portable.sh).
#
# Usage:
#   scripts/install_agent_skill.sh              # install (or refresh) globally
#   scripts/install_agent_skill.sh --uninstall  # remove it again
#   scripts/install_agent_skill.sh --print      # show the SKILL.md, nothing else
#   scripts/install_agent_skill.sh --target DIR # install somewhere else
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ID="ai-image-process"
# Where a global install lands. ~/.agents/skills is where the skill ecosystem
# converges, and it is read by OpenCode, Claude Code, Cursor and Codex alike --
# one copy works everywhere instead of only inside one harness. Overridable so
# tests (and packagers) can redirect it.
DEST_BASE="${AGENT_SKILLS_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills}"
# With no AGENT_SKILLS_HOME, prefer the cross-agent location when its parent
# already exists, else the OpenCode-native one.
if [[ -z "${AGENT_SKILLS_HOME:-}" && -d "$HOME/.agents/skills" ]]; then
  DEST_BASE="$HOME/.agents/skills"
fi
TARGET_DIR=""
MODE="install"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall) MODE="uninstall" ;;
    --print)     MODE="print" ;;
    --target)    shift; TARGET_DIR="$1" ;;
    -h|--help)   sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# Works from the repo (scripts/ -> repo root) and from the portable bundle,
# which uses the same layout. Searching beats assuming.
SRC=""
DOC_SRC=""
for d in "$SCRIPT_DIR" "$SCRIPT_DIR/.." "$SCRIPT_DIR/../.."; do
  [[ -n "$SRC" ]] && break
  if [[ -f "$d/.opencode/skills/$SKILL_ID/SKILL.md" ]]; then
    SRC="$d/.opencode/skills/$SKILL_ID"
    [[ -f "$d/docs/agent-cli.md" ]] && DOC_SRC="$d/docs/agent-cli.md"
  fi
done

if [[ "$MODE" == "print" ]]; then
  [[ -n "$SRC" ]] || { echo "[skill] cannot find $SKILL_ID/SKILL.md near $SCRIPT_DIR" >&2; exit 1; }
  cat "$SRC/SKILL.md"
  exit 0
fi

[[ -n "$SRC" ]] || {
  echo "[skill] missing .opencode/skills/$SKILL_ID/SKILL.md near $SCRIPT_DIR" >&2
  exit 1
}

DEST="${TARGET_DIR:-$DEST_BASE}/$SKILL_ID"

if [[ "$MODE" == "uninstall" ]]; then
  if [[ -d "$DEST" ]]; then
    rm -rf "$DEST"
    echo "[skill] removed $DEST"
  else
    echo "[skill] nothing to remove at $DEST"
  fi
  exit 0
fi

if [[ -e "$DEST" ]] && ! diff -rq "$SRC" "$DEST" >/dev/null 2>&1; then
  echo "[skill] refreshing existing install at $DEST"
fi

mkdir -p "$(dirname "$DEST")"
# Replace rather than merge: a stale supporting file is worse than none.
rm -rf "$DEST"
cp -R "$SRC" "$DEST"

# The reference travels with the skill. An installed skill lives in
# ~/.config/opencode/skills/, where a repo-relative "docs/agent-cli.md" resolves
# to nothing -- the agent would be told to read a file that is not there.
if [[ -n "$DOC_SRC" ]]; then
  mkdir -p "$DEST/references"
  cp "$DOC_SRC" "$DEST/references/agent-cli.md"
else
  echo "[skill] warning: docs/agent-cli.md not found; the skill will have no reference" >&2
fi

# The description is what an agent matches on; an empty or missing one means the
# skill exists but is never advertised. Fail loudly rather than shipping a
# silently dead install.
if ! python3 - "$DEST/SKILL.md" <<'PY' 2>/dev/null
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
if not m:
    sys.exit(1)
for field in ("name:", "description:"):
    if field not in m.group(1):
        sys.exit(1)
PY
then
  echo "[skill] installed, but SKILL.md frontmatter looks wrong (need name + description)" >&2
  exit 1
fi

echo "[skill] installed to $DEST"
cat <<EOF

下一步：
  · 在 OpenCode 里直接问「用 AI Image Process 处理 ./photos」，描述匹配时会自动加载；
  · 或显式引用：@$SKILL_ID
  · 完整参考随 Skill 一起安装在 references/agent-cli.md。

先确认打包版的 CLI 入口存在（便携包里应当有两个可执行文件）：
  ls AI-Image-Process-CLI
EOF