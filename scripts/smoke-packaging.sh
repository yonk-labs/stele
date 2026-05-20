#!/usr/bin/env bash
# Auto-smoke for stele packaging: install all 7 platforms into a fake HOME
# with realistic pre-existing files (so the mcp.json merge gets exercised
# with non-stele content), verify files land where expected, uninstall, and
# verify everything not pre-existing is gone.
#
# Run: bash scripts/smoke-packaging.sh
# Exit 0 = pass; non-zero = a check failed.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/fake-home"
mkdir -p "$HOME"

# Use the project's stele binary
STELE="$ROOT/.venv/bin/stele"

cd "$TMP"
echo "=== Smoke environment ==="
echo "HOME=$HOME"
echo "PWD=$TMP"
echo

# Seed realistic pre-existing state to prove the merge logic
mkdir -p "$HOME/.claude"
cat > "$HOME/.claude/mcp.json" <<'JSON'
{
  "mcpServers": {
    "imaginary-tool-1": {
      "command": "imaginary-cmd",
      "args": ["--port", "9000"]
    },
    "imaginary-tool-2": {
      "command": "another-cmd"
    }
  },
  "globalEnv": {
    "FOO": "bar"
  }
}
JSON

cat > "$HOME/.claude/CLAUDE.md" <<'MD'
# My existing CLAUDE.md

User-authored content that must survive install/uninstall.

## another-tool

This other tool also wrote a section here. It should not be touched.
MD

echo "=== Pre-install state ==="
ls -la "$HOME/.claude/"
echo

echo "=== stele init ==="
"$STELE" init --backend memory

echo
echo "=== stele install --all ==="
"$STELE" install --all

echo
echo "=== Per-platform file checks ==="
declare -A EXPECTED_SKILLS=(
  ["claude-code"]="$HOME/.claude/skills/stele/SKILL.md"
  ["codex"]="$HOME/.agents/skills/stele/SKILL.md"
  ["opencode"]="$HOME/.config/opencode/skills/stele/SKILL.md"
  ["cursor"]="$HOME/.cursor/skills/stele/SKILL.md"
  ["gemini-cli"]="$HOME/.gemini/skills/stele/SKILL.md"
  ["copilot"]="$HOME/.copilot/skills/stele/SKILL.md"
  ["aider"]="$HOME/.aider/skills/stele/SKILL.md"
)
for name in "${!EXPECTED_SKILLS[@]}"; do
  path="${EXPECTED_SKILLS[$name]}"
  if [ -f "$path" ]; then
    echo "  ✓ $name skill at $path"
  else
    echo "  ✗ MISSING: $name skill at $path"
    exit 1
  fi
done

echo
echo "=== mcp.json merge check (Claude Code) ==="
python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["HOME"], ".claude", "mcp.json")
with open(path) as f:
    data = json.load(f)
servers = data.get("mcpServers", {})
required = {"imaginary-tool-1", "imaginary-tool-2", "stele"}
missing = required - set(servers)
if missing:
    print(f"  ✗ MISSING from mcpServers: {missing}", file=sys.stderr)
    sys.exit(1)
if servers["stele"]["command"] != "stele-mcp":
    print(f"  ✗ stele.command wrong: {servers['stele']}", file=sys.stderr)
    sys.exit(1)
if data.get("globalEnv", {}).get("FOO") != "bar":
    print("  ✗ globalEnv.FOO not preserved", file=sys.stderr)
    sys.exit(1)
print("  ✓ all three servers present (imaginary-tool-1, imaginary-tool-2, stele)")
print("  ✓ unrelated top-level keys (globalEnv) preserved")
PY

echo
echo "=== CLAUDE.md section check ==="
python3 - <<'PY'
import os, sys
path = os.path.join(os.environ["HOME"], ".claude", "CLAUDE.md")
with open(path) as f:
    text = f.read()
checks = [
    ("user-authored intro preserved", "User-authored content that must survive" in text),
    ("another-tool section preserved", "## another-tool" in text and "should not be touched" in text),
    ("stele section added", "## stele" in text),
    ("stele section contains tool-routing rules", "stele_memory_search" in text),
]
ok = True
for label, passed in checks:
    print(f"  {'✓' if passed else '✗'} {label}")
    if not passed:
        ok = False
if not ok:
    sys.exit(1)
PY

echo
echo "=== Hooks check ==="
for hook in \
    "$HOME/.claude/hooks/stele-large-output.sh" \
    "$HOME/.config/opencode/plugins/stele.js" \
    "$HOME/.gemini/settings.json"
do
  if [ -f "$hook" ]; then
    echo "  ✓ $hook"
  else
    echo "  ✗ MISSING: $hook"
    exit 1
  fi
done

# Cursor hook lives in project dir, not home
if [ -f "$TMP/.cursor/rules/stele.mdc" ]; then
  echo "  ✓ $TMP/.cursor/rules/stele.mdc"
else
  echo "  ✗ MISSING: $TMP/.cursor/rules/stele.mdc"
  exit 1
fi

echo
echo "=== stele status (sanity) ==="
"$STELE" status

echo
echo "=== stele uninstall --all ==="
"$STELE" uninstall --all

echo
echo "=== Post-uninstall checks ==="
# Skills all gone
for path in "${EXPECTED_SKILLS[@]}"; do
  if [ -f "$path" ]; then
    echo "  ✗ NOT REMOVED: $path"
    exit 1
  fi
done
echo "  ✓ all platform skills removed"

# Pre-existing mcp.json content survives
python3 - <<'PY'
import json, os, sys
path = os.path.join(os.environ["HOME"], ".claude", "mcp.json")
if not os.path.exists(path):
    print(f"  ✗ mcp.json was deleted (should be preserved)", file=sys.stderr)
    sys.exit(1)
with open(path) as f:
    data = json.load(f)
servers = data.get("mcpServers", {})
if "stele" in servers:
    print(f"  ✗ stele still in mcpServers after uninstall", file=sys.stderr)
    sys.exit(1)
if "imaginary-tool-1" not in servers or "imaginary-tool-2" not in servers:
    print(f"  ✗ pre-existing servers lost", file=sys.stderr)
    sys.exit(1)
if data.get("globalEnv", {}).get("FOO") != "bar":
    print("  ✗ globalEnv.FOO lost", file=sys.stderr)
    sys.exit(1)
print("  ✓ mcp.json: stele removed, others preserved, globalEnv intact")
PY

# Pre-existing CLAUDE.md content survives
python3 - <<'PY'
import os, sys
path = os.path.join(os.environ["HOME"], ".claude", "CLAUDE.md")
with open(path) as f:
    text = f.read()
checks = [
    ("user intro still present", "User-authored content that must survive" in text),
    ("another-tool section still present", "## another-tool" in text),
    ("stele section removed", "## stele" not in text),
]
ok = True
for label, passed in checks:
    print(f"  {'✓' if passed else '✗'} {label}")
    if not passed:
        ok = False
if not ok:
    sys.exit(1)
PY

echo
echo "=== Smoke complete: all checks passed ==="
