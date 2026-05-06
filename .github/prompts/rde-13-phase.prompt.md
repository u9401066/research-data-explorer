---
description: "Run the RDE 13-phase auditable EDA workflow and produce a complete statistical report."
agent: "eda"
tools: ['codebase', 'problems', 'runCommands', 'search']
---

# RDE 13-Phase Full Pipeline

Use the Research Data Explorer MCP workflow for real user datasets. Do not replace tool execution with generic code inspection.

## Required Flow

1. Read `AGENTS.md`, `.github/agent-control.yaml`, and the current pipeline status.
2. Phase 0-2: initialize project, run intake, and build schema artifacts.
3. Phase 3: call `align_concept(confirm=true)` only after the user confirms concept-variable mapping.
4. Phase 4: call `propose_analysis_plan()` to generate the greedy blueprint.
5. Phase 5: review plan completeness with `register_analysis_plan(confirm=true)` semantics.
6. Phase 6: lock the analysis plan with `register_analysis_plan(confirm=true)`.
7. Phase 7: run `check_readiness()`.
8. Phase 8: execute planned analyses; any departure from the locked plan requires `log_deviation()`.
9. Phase 9-12: `collect_results()`, `assemble_report()`, `run_audit()`, `auto_improve()`, and export or handoff when requested.

## Output Rules

- Cite concrete artifact paths in the answer.
- Explain statistical results in plain language with technical values in parentheses.
- Never silently change methods after plan lock.
- Mention remaining audit/readiness blockers before claiming completion.
