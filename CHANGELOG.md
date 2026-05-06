# Changelog

All notable changes to this project will be documented in this file.

The first synchronized repository and VS Code extension release is planned as 0.1.0.

## [Unreleased]

## [0.4.5] - 2026-05-06

### 0.4.5 Added

- Canonical 13-phase harness alignment across MCP runtime, agent-control manifest, prompts, AGENTS/SPEC docs, memory bank, and VSIX runtime instructions.
- VSIX workspace setup now scaffolds Copilot, Codex, and Cline assets, including root `AGENTS.md`, `.codex/skills`, and `.clinerules` rules/workflows.
- VSIX release checks now include asset sync validation and bundled-tool install smoke testing.
- Value-level PII detection now flags generic columns that contain email, phone, SSN-style, or national-ID-like sample values.

### 0.4.5 Fixed

- Phase 4/5/6 planning gates now produce distinct creative-ideation, plan-completeness-review, and locked-plan artifacts before readiness/execution.
- Report readiness now reads `analysis_plan_review.json` from Phase 5, matching the canonical 13-phase artifact contract.
- Project-bound datasets can now rehydrate from Phase 1 intake artifacts after MCP session reset.
- Phase 7 readiness now checks Phase 4/5 artifacts and includes Shapiro-Wilk normality previews for continuous variables.
- Decision and deviation log entries now identify Phase 8 execution rather than legacy Phase 6 execution.

## [0.4.4] - 2026-04-14

### 0.4.4 Fixed

- Loading a persisted project now repairs stale `status`, `completed_phases`, and `plan_locked` from existing phase artifacts before rehydrating the MCP session, so legacy projects can resume from their real artifact-backed progress instead of getting stuck at an older JSON phase.
- Older projects with complete Phase 7-10 artifacts can now be reopened and extended without cloning their artifacts into a separate follow-up project just to satisfy phase gates.

## [0.4.3] - 2026-04-14

### 0.4.3 Added

- Three new SVG architecture figures under `docs/figures/` covering the overall concept, DDD system architecture, and the then-current governed workflow.
- Visual Overview sections in both `README.md` and `README.zh-TW.md` so the new diagrams are visible directly from the repository landing pages.

### 0.4.3 Fixed

- Repository-wide formatting and small lint/type cleanup needed for the CI quality gate to pass consistently after the documentation update.
- The AKI report export helper now satisfies the repository Ruff import-order rule when executed directly.

## [0.4.2] - 2026-04-14

### 0.4.2 Fixed

- AKI helper scripts now resolve `data/` and `src/` paths from the repository root instead of the caller cwd, so direct script execution behaves consistently on macOS, Linux, and Windows.
- Local runtime outputs now stay out of Git status by ignoring short-ID `data/projects/*.json` metadata files and `uv.lock`.

## [0.4.1] - 2026-04-14

### 0.4.1 Fixed

- VS Code extension project creation now resolves `data/projects/` from `RDE_WORKSPACE` instead of the MCP server process cwd, so `init_project()` writes new project folders into the active workspace rather than the user's home directory.
- Persisted project metadata now rehydrates back into the MCP session after a server reset, including pipeline completion state and plan-lock status, so tools like `get_pipeline_status(project_id=...)` can continue from saved workspace projects.
- Pre-commit artifact gate resolution is now repository-root relative and its path matcher accepts both `/` and `\`, so the release harness behaves consistently on macOS, Linux, and Windows checkouts.

## [0.4.0] - 2026-03-30

### 0.4.0 Added

- **Autonomous EDA Planner** (`AutonomousEDAPlanner`): greedy candidate ranking, multi-round plan enrichment, deterministic methodology review/repair, execution schedule generation, and `statsmodels`-centered baseline analysis script generation.
- **`propose_analysis_plan()` MCP tool**: generates a pre-lock blueprint with ranked candidates, coverage tags, enrichment rounds, and a reviewable statsmodels script before plan registration.
- **`statsmodels>=0.14`** added as first-class local modeling dependency for OLS, logistic, GLM, ANOVA, and multiple-testing correction.
- **Vendor integration overhaul**: `AutomlGateway` now targets the real `automl-stat-mcp` submit-based contract (`/analysis/submit`, `/propensity/submit`, `/survival/submit`, `/roc/submit`, `/power/submit`, `/train/automl`), with proper job-ID polling and fallback.
- **Phase 6 `run_advanced_analysis()`** extended with `survival_analysis`, `roc_auc`, `power_analysis`, and `automl_training` parameter mappings for vendor delegation.
- **Timestamp-prefixed project folders**: `init_project()` now creates `data/projects/YYYYMMDD_HHMMSS_<project_id>/` for human-readable chronological sorting while keeping the stable 8-char `project_id`.
- **Vendor stats-service fix**: re-exported `StatisticalTestRequest` / `StatisticalTestResponse` in vendor `domain.ports` so the Docker container starts without `ImportError`.
- Integration test for timestamp-prefixed folder naming contract.
- Planner unit tests and benchmark suite covering grouped/binary, repeated-measure, and learning-curve scenarios.
- Live vendor integration tests exercising `AutomlGateway` against the real Docker stack (stats-service + automl-api + Redis).

### 0.4.0 Fixed

- `AutomlGateway` endpoint paths aligned to vendor's actual `/analysis/submit` contract (was using legacy `/analysis/direct`).
- `_textify` test helper now correctly handles MCP tuple return shape `([TextContent(...)], metadata)`.
- Nullable-project assertions added in `get_pipeline_status`, `get_decision_log`, `get_deviation_log`, `log_deviation` to prevent unhandled `None` dereferences.

## [0.3.0] - 2026-03-28

### 0.3.0 Fixed

- Local dev MCP startup now prefers `uv --project <workspace>` or a uv-managed workspace `.venv` over an arbitrary configured Python path, avoiding missing dependency errors such as `ModuleNotFoundError: No module named 'mcp'`.
- Phase 6 analysis execution now marks `EXECUTE_EXPLORATION` complete as soon as governed analysis work is logged, so `collect_results()` no longer fails on a false missing prerequisite.
- Phase 7 results collection now counts executed analyses from both analysis results and decision logs, preventing under-reported plan coverage in real-data runs.
- Phase 9 audit completeness no longer incorrectly treats Phase 9/10 outputs as missing prerequisites during the audit itself.
- Plan-adherence auto-detection now preserves advanced-analysis variables, preventing false deviation logs for planned `run_advanced_analysis()` executions such as learning-curve CUSUM.
- Windows/macOS CJK font fallback is now configured for matplotlib export, reducing missing-glyph warnings in clinical figures.

### 0.3.0 Added

- `generate_table_one()` now persists `table_one.md` and `table_one.json` as Phase 6 artifacts.
- Local `learning_curve_cusum` support was added to `run_advanced_analysis()`, including operator-level CUSUM summaries and persisted markdown/json artifacts.
- Phase 8 report assembly now includes optional `Table 1 — Baseline Characteristics` and `Sensitivity Analysis` sections when those artifacts are present.
- Phase 8 report assembly now includes an optional `Learning Curve CUSUM` section when advanced-analysis markdown artifacts are present.
- `export_handoff()` now packages Table 1, learning-curve CUSUM, and sensitivity-analysis artifacts for downstream paper-writing workflows.

## [0.2.1] - 2026-03-28

### Fixed

- VSX extension no longer depends on publishing `research-data-explorer` to a Python package registry; packaged builds now run a bundled local Python project, and repo workspaces continue to run the local source tree directly.
- VSX extension: `setupWorkspace()` and `loadSkillContent()` were copying/reading from non-existent `vscode-extension/{skills,agents,prompts}/` directories — these resources now ship bundled inside the extension.
- `run_repeated_measures` was registered in the VSX tool policy but missing from AGENTS.md tool inventory.
- H-003 soft-constraint description was ambiguous (`≥ 10` could be read as "reject when n >= 10").

### Added

- `vscode-extension/skills/` — 8 bundled skill directories (data-profiling, eda-workflow, git-precommit, memory-checkpoint, memory-updater, report-generator, session-end, session-start)
- `vscode-extension/agents/` — 9 bundled agent definition files
- `vscode-extension/prompts/` — 4 bundled prompt templates
- `vscode-extension/copilot-instructions.md` — VSX-specific Copilot instructions

## [0.1.0] - Pending

### Planned

- VS Code extension packaging, validation, and marketplace publish workflows.
- Auditable raw-data normalization and workflow consistency checks across repo and extension.
