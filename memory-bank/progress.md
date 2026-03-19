# Progress (Updated: 2026-03-19)

## Done

- Compared RDE against template-is-all-you-need and identified missing editor/agent/prompt/CI scaffolding.
- Added RDE-specific VS Code settings, agents, prompts, CI workflow, and contributor docs.
- Validated the repo with pytest after scaffolding and after pre-commit autofixes.
- Cleared repository-owned Ruff and pre-commit debt, excluding vendor code from repo quality gates.
- Restored the main CI quality job to blocking for Ruff, formatting, pytest, and pre-commit.

## Doing

- Preparing the scaffolding and quality-gate changes for commit/push without bundling local dry-run data artifacts.

## Next

- Optionally decide whether dry-run project summaries under data/projects/ should be versioned separately.
