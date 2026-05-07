# RDE Core Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RDE enforce its non-data-scientist, no-code, reproducible-analysis, complete-report core contract through runtime gates, report readiness, Phase 8 artifacts, and VSIX harness prompts.

**Architecture:** Keep the existing 13-phase DDD architecture. Tighten behavior at phase boundaries and readiness helpers instead of adding new phases or broad refactors. Preserve local-lite as the no-Docker execution path and make every claim auditable through artifacts and tests.

**Tech Stack:** Python 3.14, pytest, pandas, scipy/statsmodels, TypeScript/Vitest for VSIX policy tests.

---

## File Map

- `src/rde/interface/mcp/tools/plan_tools.py`: Phase 4/5/6 confirmation and dataset/review lock behavior.
- `src/rde/interface/mcp/tools/discovery_tools.py`: Phase 2 schema gate must honor Phase 1 artifact prerequisite.
- `src/rde/interface/mcp/tools/_shared/project_context.py`: plan adherence and Phase 8 progress must be plan-item aware.
- `src/rde/interface/mcp/tools/analysis_tools.py`: Phase 8 decision logging, advanced artifacts, full config logging.
- `src/rde/infrastructure/adapters/analysis_delegator.py`: local-lite ROC, propensity, Kaplan-Meier reportability.
- `src/rde/interface/mcp/tools/report_tools.py`: `collect_results` readiness payload and core goal checks.
- `src/rde/interface/mcp/tools/audit_tools.py`: recompute readiness during audit.
- `vscode-extension/src/toolPolicy.ts`: no-code command groups and confirmation prompt.
- `vscode-extension/agents/eda.agent.md`, `vscode-extension/skills/report-generator/SKILL.md`, `vscode-extension/prompts/rde-13-phase.prompt.md`: phase drift and generic-tool restriction.
- Tests: `tests/test_pipeline_enforcement.py`, `tests/test_plan_adherence.py`, `tests/test_report_contract.py`, `tests/test_analysis_delegation.py`, `tests/test_advanced_analysis_formatting.py`, `tests/test_docs_and_tool_sync.py`, `vscode-extension/test/toolPolicy.test.ts`.

## Task 1: Pipeline Gates And Plan Adherence

- [ ] Write failing tests for Phase 4 not auto-confirming, schema gate requiring Phase 1 artifacts, stricter group/time/score plan adherence, and matched Phase 8 coverage.
- [ ] Run targeted tests and confirm RED failures.
- [ ] Update `plan_tools.py`, `discovery_tools.py`, and `_shared/project_context.py` minimally.
- [ ] Run targeted tests and confirm GREEN.

## Task 2: Report Readiness And Audit

- [ ] Write failing tests for full readiness payload, no unconditional no-code/harness pass, report artifact requirement, and audit recomputation.
- [ ] Run targeted tests and confirm RED failures.
- [ ] Update `report_tools.py` and `audit_tools.py` minimally.
- [ ] Run targeted tests and confirm GREEN.

## Task 3: Phase 8 Reproducible Local-Lite

- [ ] Write failing tests for unique advanced artifacts, full config decision summaries, propensity score summaries, ROC score fallback, and grouped Kaplan-Meier summaries.
- [ ] Run targeted tests and confirm RED failures.
- [ ] Update `analysis_tools.py` and `analysis_delegator.py` minimally.
- [ ] Run targeted tests and confirm GREEN.

## Task 4: VSIX Agent Harness

- [ ] Write failing tests for command group bootstrap tools, full prompt confirmation wording, VSIX phase sync, and prompt forbidden generic tools.
- [ ] Run targeted Python/VSIX tests and confirm RED failures.
- [ ] Update `toolPolicy.ts` and bundled prompt/agent/skill docs minimally.
- [ ] Run targeted Python/VSIX tests and confirm GREEN.

## Task 5: Verification

- [ ] Run `python3 -m pytest -q`.
- [ ] Run VSIX test command from package scripts.
- [ ] Inspect `git diff --stat` and changed files.
- [ ] Report verified status and any remaining risks without overstating production readiness.

## Self-Review

- Spec coverage: tasks cover phase gates, planning lock, readiness, audit, Phase 8 reproducibility, local-lite reportability, no-code harness, and VSIX drift.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: all referenced files and test commands exist in the repository.
