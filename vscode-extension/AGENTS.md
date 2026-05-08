# Research Data Explorer Agent Guide

Use RDE as a 13-phase auditable EDA harness, not as an ad hoc notebook.

## Operating Contract

- The VSIX path is local-first for non-data-scientists: a user should not need Docker or analysis code to complete the core report flow.
- Treat automl-stat-mcp as optional. Use local-lite fallbacks for adjusted models, ROC/AUC, basic power, Kaplan-Meier, and lightweight propensity scoring when Docker is unavailable.
- Check `report_readiness.core_goal_audit`; `core_goal:*` gaps mean the run is not production-ready.
- Follow `.github/agent-control.yaml` when it is present in the workspace.
- Use the RDE MCP tools for dataset intake, schema, planning, execution, reporting, audit, and handoff.
- Treat Phase 3 concept alignment, Phase 4 creative ideation, and the combined Phase 5+6 review/plan lock as explicit confirmation gates.
- After Phase 6, any execution change outside the locked plan requires `log_deviation()`.
- Decision and deviation logs live under `artifacts/phase_08_execute_exploration/`.
- Reports should cite artifact paths and explain statistical findings in plain language with technical values in parentheses.

## Full Report Flow

`init_project` -> `run_intake` -> `build_schema` -> `align_concept(confirm=true)` -> `propose_analysis_plan(confirm=false)` -> review Phase 4 artifacts -> `propose_analysis_plan(confirm=true)` -> `register_analysis_plan(confirm=true)` -> `check_readiness` -> execute planned analyses -> `collect_results` -> `assemble_report` -> `run_audit` -> `auto_improve` -> optional `export_final_report` / `export_handoff`.

## Codex Support

Codex should use the RDE MCP server directly. The VSIX auto-upserts `~/.codex/config.toml` on activation and via the `RDE: Configure Codex MCP` command when a workspace is open. Repo developers can also run `python scripts/configure_codex_mcp.py --apply`. Verify with `python scripts/codex_rde_smoke.py --list-tools-only` and `python scripts/codex_rde_smoke.py`; use `--data-file <path> --full-yolo` for a governed real-file smoke. If `init_project` or other RDE tools are missing from the MCP registry, reload/restart the MCP host instead of replacing RDE with shell-based analysis.

## Agent Coverage

- Copilot: `.github/copilot-instructions.md`, `.github/agents`, `.github/prompts`.
- Codex: this `AGENTS.md` plus `.codex/skills`.
- Cline: `.clinerules` and `.clinerules/workflows`.
