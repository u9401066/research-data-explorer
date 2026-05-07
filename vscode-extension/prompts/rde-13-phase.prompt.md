---
description: "Run the RDE 13-phase auditable EDA workflow and produce a complete statistical report."
agent: "eda"
tools: ['showMemory', 'logDecision', 'updateContext', 'updateProgress']
---

# RDE 13-Phase Full Pipeline

Use the Research Data Explorer MCP workflow for real user datasets. Do not replace tool execution with generic code inspection, workspace search, shell commands, notebooks, or ad hoc scripts.

## Required Flow

1. Use the bundled RDE instructions and current pipeline status from RDE MCP tools.
2. Phase 0-2: initialize project, run intake, and build schema artifacts.
3. Phase 3: call `align_concept(confirm=true)` for concept-schema alignment only after the user confirms concept-variable mapping.
4. Phase 4 is a two-step confirmation gate: call `propose_analysis_plan(confirm=false)` to generate greedy blueprint/review artifacts, show those artifacts to the user, then call `propose_analysis_plan(confirm=true)` only after the user confirms them.
5. Phase 5+6: after the user confirms the reviewed plan, call `register_analysis_plan(confirm=true)`; this single governed tool invocation performs plan completeness review and then locks Phase 6.
6. Phase 7: run `check_readiness()`.
7. Phase 8: execute planned analyses; any departure from the locked plan requires `log_deviation()`.
8. Phase 8 may run autonomous YOLO exploration branches with `start_autoresearch_run`, `get_autoresearch_status`, `stop_autoresearch_run`, `resume_autoresearch_run`, `run_autoresearch_next_task`, `run_autoresearch_queue`, `open_exploration_branch`, `suggest_branch_experiments`, `run_branch_experiment`, `evaluate_branch`, `discard_branch`, and `get_exploration_board`; branch outputs stay branch-scoped artifacts.
9. Branch promotion is never automatic: `promote_branch_to_plan_amendment(confirm=true)` requires an `evaluate_branch` audit gate and explicit user confirmation before any amendment can enter the locked plan or primary conclusions.
10. Phase 9-12: `collect_results()`, `assemble_report()`, `run_audit()`, `auto_improve()`, and export or handoff when requested.
11. When the user needs no-code guidance, use `get_approval_card`, `get_harness_dashboard`, `build_artifact_index`, and `get_blocker_playbook` instead of explaining from memory.
12. Quick Explore requests may stop after intake/schema/profile and call `assemble_report()` / `export_report()` as "Quick Explore -- Not Audited".

## Output Rules

- Cite concrete artifact paths in the answer.
- Explain statistical results in plain language with technical values in parentheses.
- Never silently change methods after plan lock.
- Mention remaining audit/readiness blockers before claiming completion.
