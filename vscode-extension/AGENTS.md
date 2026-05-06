# Research Data Explorer Agent Guide

Use RDE as a 13-phase auditable EDA harness, not as an ad hoc notebook.

## Operating Contract

- The VSIX path is local-first for non-data-scientists: a user should not need Docker or analysis code to complete the core report flow.
- Treat automl-stat-mcp as optional. Use local-lite fallbacks for adjusted models, ROC/AUC, basic power, Kaplan-Meier, and lightweight propensity scoring when Docker is unavailable.
- Check `report_readiness.core_goal_audit`; `core_goal:*` gaps mean the run is not production-ready.
- Follow `.github/agent-control.yaml` when it is present in the workspace.
- Use the RDE MCP tools for dataset intake, schema, planning, execution, reporting, audit, and handoff.
- Treat Phase 3 concept alignment, Phase 5 plan completeness review, and Phase 6 plan lock as explicit confirmation gates.
- After Phase 6, any execution change outside the locked plan requires `log_deviation()`.
- Decision and deviation logs live under `artifacts/phase_08_execute_exploration/`.
- Reports should cite artifact paths and explain statistical findings in plain language with technical values in parentheses.

## Full Report Flow

`init_project` -> `run_intake` -> `build_schema` -> `align_concept` -> `propose_analysis_plan` -> `register_analysis_plan` -> `check_readiness` -> execute planned analyses -> `collect_results` -> `assemble_report` -> `run_audit` -> `auto_improve` -> optional `export_final_report` / `export_handoff`.

## Agent Coverage

- Copilot: `.github/copilot-instructions.md`, `.github/agents`, `.github/prompts`.
- Codex: this `AGENTS.md` plus `.codex/skills`.
- Cline: `.clinerules` and `.clinerules/workflows`.
