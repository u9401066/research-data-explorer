#!/usr/bin/env bash
# validate-build.sh — Post-build validation for RDE VS Code Extension
# Checks that all required files exist in the packaged output.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== RDE VSX Build Validation ==="

ERRORS=0
WARNINGS=0

check_file() {
    local file="$1"
    local label="$2"
    if [ -f "$file" ]; then
        echo "  ✓ $label"
    else
        echo "  ✗ $label (MISSING: $file)"
        ERRORS=$((ERRORS + 1))
    fi
}

check_dir() {
    local dir="$1"
    local label="$2"
    if [ -d "$dir" ]; then
        local count
        count=$(find "$dir" -type f | wc -l | tr -d ' ')
        echo "  ✓ $label ($count files)"
    else
        echo "  ⚠ $label (directory not found)"
        WARNINGS=$((WARNINGS + 1))
    fi
}

# 1. Compiled output
echo ""
echo "--- Compiled TypeScript ---"
check_file "$EXT_DIR/out/extension.js" "out/extension.js"
check_file "$EXT_DIR/out/extensionHelpers.js" "out/extensionHelpers.js"
check_file "$EXT_DIR/out/uvManager.js" "out/uvManager.js"
check_file "$EXT_DIR/out/utils.js" "out/utils.js"

# 2. Package manifest
echo ""
echo "--- Package Manifest ---"
check_file "$EXT_DIR/package.json" "package.json"

# 3. Bundled assets (optional for marketplace mode)
echo ""
echo "--- Bundled Assets ---"
check_dir "$EXT_DIR/skills" "skills/"
check_dir "$EXT_DIR/prompts" "prompts/"
check_dir "$EXT_DIR/agents" "agents/"
check_file "$EXT_DIR/bundled/tool/pyproject.toml" "bundled/tool/pyproject.toml"
check_dir "$EXT_DIR/bundled/tool/src/rde" "bundled/tool/src/rde/"

# 4. Cross-platform scripts
echo ""
echo "--- Build Scripts ---"
check_file "$EXT_DIR/scripts/build.sh" "build.sh (Linux/macOS)"
check_file "$EXT_DIR/scripts/build.ps1" "build.ps1 (Windows)"

echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "=== VALIDATION FAILED: $ERRORS errors, $WARNINGS warnings ==="
    exit 1
else
    echo "=== VALIDATION PASSED: 0 errors, $WARNINGS warnings ==="
fi
