# Changelog

All notable changes to this project will be documented in this file.

The first synchronized repository and VS Code extension release is planned as 0.1.0.

## [Unreleased]

## [0.2.0] - 2026-03-28

### Fixed

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
