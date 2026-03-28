<#
.SYNOPSIS
    Post-build validation for RDE VS Code Extension (Windows)
.DESCRIPTION
    Checks that all required files exist in the packaged output.
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExtDir = Split-Path -Parent $ScriptDir

Write-Host "=== RDE VSX Build Validation ===" -ForegroundColor Cyan

$Errors = 0
$Warnings = 0

function Check-File {
    param([string]$Path, [string]$Label)
    if (Test-Path $Path) {
        Write-Host "  ✓ $Label" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $Label (MISSING)" -ForegroundColor Red
        $script:Errors++
    }
}

function Check-Dir {
    param([string]$Path, [string]$Label)
    if (Test-Path $Path) {
        $count = (Get-ChildItem $Path -Recurse -File).Count
        Write-Host "  ✓ $Label ($count files)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ $Label (directory not found)" -ForegroundColor Yellow
        $script:Warnings++
    }
}

# 1. Compiled output
Write-Host "`n--- Compiled TypeScript ---"
Check-File (Join-Path $ExtDir "out\extension.js") "out/extension.js"
Check-File (Join-Path $ExtDir "out\extensionHelpers.js") "out/extensionHelpers.js"
Check-File (Join-Path $ExtDir "out\uvManager.js") "out/uvManager.js"
Check-File (Join-Path $ExtDir "out\utils.js") "out/utils.js"

# 2. Package manifest
Write-Host "`n--- Package Manifest ---"
Check-File (Join-Path $ExtDir "package.json") "package.json"

# 3. Bundled assets
Write-Host "`n--- Bundled Assets ---"
Check-Dir (Join-Path $ExtDir "skills") "skills/"
Check-Dir (Join-Path $ExtDir "prompts") "prompts/"
Check-Dir (Join-Path $ExtDir "agents") "agents/"
Check-File (Join-Path $ExtDir "bundled\tool\pyproject.toml") "bundled/tool/pyproject.toml"
Check-Dir (Join-Path $ExtDir "bundled\tool\src\rde") "bundled/tool/src/rde/"

# 4. Cross-platform scripts
Write-Host "`n--- Build Scripts ---"
Check-File (Join-Path $ExtDir "scripts\build.sh") "build.sh (Linux/macOS)"
Check-File (Join-Path $ExtDir "scripts\build.ps1") "build.ps1 (Windows)"

Write-Host ""
if ($Errors -gt 0) {
    Write-Host "=== VALIDATION FAILED: $Errors errors, $Warnings warnings ===" -ForegroundColor Red
    exit 1
} else {
    Write-Host "=== VALIDATION PASSED: 0 errors, $Warnings warnings ===" -ForegroundColor Green
}
