<#
.SYNOPSIS
    Build the RDE VS Code Extension (Windows PowerShell)
.DESCRIPTION
    Copies skills, prompts, agents, Python source, compiles TypeScript, and packages VSIX.
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExtDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent $ExtDir

Write-Host "=== RDE VSX Build ===" -ForegroundColor Cyan
Write-Host "Extension dir: $ExtDir"
Write-Host "Repo root:     $RepoRoot"

# ─── 1. Copy Skills ────────────────────────────────────────────────────────────
$Skills = @(
    "eda-workflow"
    "data-profiling"
    "report-generator"
    "session-start"
    "session-end"
    "memory-updater"
    "memory-checkpoint"
    "git-precommit"
)

Write-Host "`n--- Copying skills ---"
foreach ($skill in $Skills) {
    $src = Join-Path $RepoRoot ".claude\skills\$skill\SKILL.md"
    $dst = Join-Path $ExtDir "skills\$skill\SKILL.md"
    if (Test-Path $src) {
        $dstDir = Split-Path -Parent $dst
        if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
        Copy-Item $src $dst -Force
        Write-Host "  ✓ $skill" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $skill (not found)" -ForegroundColor Yellow
    }
}

# ─── 2. Copy Prompts ───────────────────────────────────────────────────────────
$Prompts = @(
    "rde-13-phase"
    "rde-audit"
    "rde-code-review"
    "rde-pre-commit"
)

Write-Host "`n--- Copying prompts ---"
foreach ($prompt in $Prompts) {
    $src = Join-Path $RepoRoot ".github\prompts\$prompt.prompt.md"
    $dst = Join-Path $ExtDir "prompts\$prompt.prompt.md"
    if (Test-Path $src) {
        $dstDir = Split-Path -Parent $dst
        if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
        Copy-Item $src $dst -Force
        Write-Host "  ✓ $prompt" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $prompt (not found)" -ForegroundColor Yellow
    }
}

# ─── 3. Copy Agents ────────────────────────────────────────────────────────────
$Agents = @(
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

Write-Host "`n--- Copying agents ---"
foreach ($agent in $Agents) {
    $src = Join-Path $RepoRoot ".github\agents\$agent.agent.md"
    $dst = Join-Path $ExtDir "agents\$agent.agent.md"
    if (Test-Path $src) {
        $dstDir = Split-Path -Parent $dst
        if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
        Copy-Item $src $dst -Force
        Write-Host "  ✓ $agent" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $agent (not found)" -ForegroundColor Yellow
    }
}

# ─── 4. Copy copilot-instructions.md ───────────────────────────────────────────
Write-Host "`n--- Copying copilot-instructions ---"
$instrSrc = Join-Path $RepoRoot ".github\copilot-instructions.md"
$instrDst = Join-Path $ExtDir "copilot-instructions.md"
if (Test-Path $instrSrc) {
    Copy-Item $instrSrc $instrDst -Force
    Write-Host "  ✓ copilot-instructions.md" -ForegroundColor Green
}

# ─── 5. Prepare bundled Python project ────────────────────────────────────────
Write-Host "`n--- Preparing bundled Python project ---"
Push-Location $ExtDir
node .\scripts\prepare-bundle.mjs
Pop-Location

# ─── 6. Compile TypeScript ─────────────────────────────────────────────────────
Write-Host "`n--- Compiling TypeScript ---"
Push-Location $ExtDir
npm run compile
Pop-Location

# ─── 7. Package VSIX ───────────────────────────────────────────────────────────
Write-Host "`n--- Packaging VSIX ---"
Push-Location $ExtDir
npm run package
Pop-Location

Write-Host "`n=== Build complete ===" -ForegroundColor Cyan
Get-ChildItem (Join-Path $ExtDir "*.vsix") -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_.FullName }
