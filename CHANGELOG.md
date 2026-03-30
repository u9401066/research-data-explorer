# Changelog

All notable changes to this project will be documented in this file.

The first synchronized repository and VS Code extension release is planned as 0.1.0.

## [Unreleased]

## [0.4.0] - 2026-03-30

### 0.4.0 Added

- **Autonomous EDA Planner** (`AutonomousEDAPlanner`): greedy candidate ranking, multi-round plan enrichment, deterministic methodology review/repair, execution schedule generation, and `statsmodels`-centered baseline analysis script generation.
- **`propose_analysis_plan()` MCP tool** (Phase 3.5): generates a pre-lock blueprint with ranked candidates, coverage tags, enrichment rounds, and a reviewable statsmodels script before Phase 4 plan registration.
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
