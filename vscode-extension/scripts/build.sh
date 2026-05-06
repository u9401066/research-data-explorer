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
    "rde-13-phase"
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

# ─── 5. Prepare bundled Python project ────────────────────────────────────────
echo ""
echo "--- Preparing bundled Python project ---"
node "$EXT_DIR/scripts/prepare-bundle.mjs"

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
