#!/usr/bin/env bash
# Install the AI Image Process agent skill so an agent can drive the CLI.
#
# The skill lives in this repo at .opencode/skills/ai-image-process/. Working
# *inside* this checkout needs no install: OpenCode discovers project skills by
# walking up from the working directory. This script is for the other case --
# driving the packaged CLI from an unrelated project, where the agent has never
# seen this repository.
#
# Usage:
#   scripts/install_agent_skill.sh              # install (or refresh) globally
#   scripts/install_agent_skill.sh --uninstall  # remove it again
#   scripts/install_agent_skill.sh --print      # show the SKILL.md, nothing else
#   scripts/install_agent_skill.sh --target DIR # install somewhere else
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_ID="ai-image-process"
SRC="$ROOT/.opencode/skills/$SKILL_ID"

# Global location OpenCode reads for every project. Overridable for testing.
DEST_BASE="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills"
TARGET_DIR=""
MODE="install"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall) MODE="uninstall" ;;
    --print)     MODE="print" ;;
    --target)    shift; TARGET_DIR="$1" ;;
    -h|--help)   sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ "$MODE" == "print" ]]; then
  cat "$SRC/SKILL.md"
  exit 0
fi

[[ -f "$SRC/SKILL.md" ]] || {
  echo "[skill] missing $SRC/SKILL.md — run from a checkout of the project" >&2
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

# The description is what an agent matches on; an empty or missing one means the
# skill exists but is never advertised. Fail loudly rather than shipping a
# silently dead install.
if ! .venv/bin/python - "$DEST/SKILL.md" <<'PY' 2>/dev/null
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
  · 只在本仓库工作时无需安装，项目内 .opencode/skills 会被自动发现。

先确认打包版的 CLI 入口存在（便携包里应当有两个可执行文件）：
  ls AI-Image-Process-CLI
EOF