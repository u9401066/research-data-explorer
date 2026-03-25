#!/usr/bin/env bash
# build.sh — Build the RDE VS Code Extension
# Usage: ./scripts/build.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$EXT_DIR/.." && pwd)"

echo "=== RDE VSX Build ==="
echo "Extension dir: $EXT_DIR"
echo "Repo root:     $REPO_ROOT"

# ─── 1. Copy Skills ────────────────────────────────────────────────────────────
SKILLS=(
    "eda-workflow"
    "data-profiling"
    "report-generator"
    "session-start"
    "session-end"
    "memory-updater"
    "memory-checkpoint"
    "git-precommit"
)

echo ""
echo "--- Copying skills ---"
for skill in "${SKILLS[@]}"; do
    src="$REPO_ROOT/.claude/skills/$skill/SKILL.md"
    dst="$EXT_DIR/skills/$skill/SKILL.md"
    if [ -f "$src" ]; then
        mkdir -p "$(dirname "$dst")"
        cp "$src" "$dst"
        echo "  ✓ $skill"
    else
        echo "  ✗ $skill (not found at $src)"
    fi
done

# ─── 2. Copy Prompts ───────────────────────────────────────────────────────────
PROMPTS=(
    "rde-phase-0-10"
    "rde-audit"
    "rde-code-review"
    "rde-pre-commit"
)

echo ""
echo "--- Copying prompts ---"
for prompt in "${PROMPTS[@]}"; do
    src="$REPO_ROOT/.github/prompts/$prompt.prompt.md"
    dst="$EXT_DIR/prompts/$prompt.prompt.md"
    if [ -f "$src" ]; then
        mkdir -p "$(dirname "$dst")"
        cp "$src" "$dst"
        echo "  ✓ $prompt"
    else
        echo "  ✗ $prompt (not found at $src)"
    fi
done

# ─── 3. Copy Agents ────────────────────────────────────────────────────────────
AGENTS=(
    "architect"
    "ask"
    "audit"
    "code"
    "context-loader"
    "debug"
    "eda"
    "orchestrator"
    "test-runner"
)

echo ""
echo "--- Copying agents ---"
for agent in "${AGENTS[@]}"; do
    src="$REPO_ROOT/.github/agents/$agent.agent.md"
    dst="$EXT_DIR/agents/$agent.agent.md"
    if [ -f "$src" ]; then
        mkdir -p "$(dirname "$dst")"
        cp "$src" "$dst"
        echo "  ✓ $agent"
    else
        echo "  ✗ $agent (not found at $src)"
    fi
done

# ─── 4. Copy copilot-instructions.md ───────────────────────────────────────────
echo ""
echo "--- Copying copilot-instructions ---"
src="$REPO_ROOT/.github/copilot-instructions.md"
dst="$EXT_DIR/copilot-instructions.md"
if [ -f "$src" ]; then
    cp "$src" "$dst"
    echo "  ✓ copilot-instructions.md"
fi

# ─── 5. Copy bundled Python source ─────────────────────────────────────────────
echo ""
echo "--- Copying bundled Python source ---"
BUNDLED_TOOL="$EXT_DIR/bundled/tool"
mkdir -p "$BUNDLED_TOOL"

if [ -d "$REPO_ROOT/src/rde" ]; then
    # Use rsync if available, otherwise fall back to cp
    if command -v rsync &>/dev/null; then
        rsync -a --delete \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            "$REPO_ROOT/src/rde/" "$BUNDLED_TOOL/rde/"
    else
        rm -rf "$BUNDLED_TOOL/rde"
        cp -R "$REPO_ROOT/src/rde" "$BUNDLED_TOOL/rde"
        find "$BUNDLED_TOOL/rde" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
        find "$BUNDLED_TOOL/rde" -name '*.pyc' -delete 2>/dev/null || true
    fi
    echo "  ✓ rde source copied"
fi

# ─── 6. Compile TypeScript ─────────────────────────────────────────────────────
echo ""
echo "--- Compiling TypeScript ---"
cd "$EXT_DIR"
npm run compile

# ─── 7. Package VSIX ───────────────────────────────────────────────────────────
echo ""
echo "--- Packaging VSIX ---"
npm run package

echo ""
echo "=== Build complete ==="
ls -la *.vsix 2>/dev/null || echo "(no .vsix found — run 'npx @vscode/vsce package' manually)"
