# MCP tool-by-tool review

This inventory is generated from the live official SDK registry by
`uv run python scripts/audit_mcp_surface.py`, not inferred from function names.
All 50 tools have matching SDK/extension inventories, input and output schemas,
descriptions, explicit effect/gate contracts and annotations. Every row is covered
by the parameterized `tests/test_mcp_tool_boundaries.py` isolation/error-boundary
test; focused suites additionally exercise successful workflows.

Annotations describe effects; they are not authorization. Runtime state and human
confirmation checks remain authoritative. The tests do not validate every possible
dataset, clinical estimand or external vendor configuration.

| Tool | Phase | Runtime gate | Declared effects | Read-only |
| --- | --- | --- | --- | --- |
| `align_concept` | 3 | schema + human confirmation | concept and roles | no |
| `analyze_variable` | 8 | locked plan + readiness + sample size | decision | no |
| `apply_cleaning` | 8 | locked plan + readiness + approved actions | cleaned data and decision | no |
| `assemble_report` | 10 | readiness or explicit unaudited preview | report and provenance | no |
| `assess_quality` | 2 | dataset exists | quality artifacts | no |
| `auto_improve` | 12 | audit complete | final report | no |
| `build_artifact_index` | all | project exists | artifact index | no |
| `build_schema` | 2 | intake + dataset scope | schema and roles | no |
| `check_readiness` | 7 | locked plan + prior artifacts | readiness | no |
| `collect_results` | 9 | execution complete or explicit force | result summary | no |
| `compare_groups` | 8 | locked plan + readiness | results and decision | no |
| `correlation_matrix` | 8 | locked plan + readiness | results and decision | no |
| `create_visualization` | 8/10 | execution gate + dataset | figure and manifest | no |
| `discard_branch` | 8 | branch exists | discard event; evidence retained | no |
| `evaluate_branch` | 8 | live evidence | evaluation and review | no |
| `export_final_report` | 12 | audit + readiness | export files | no |
| `export_handoff` | 12 | audit + readiness | handoff bundle | no |
| `export_report` | 10 | report readiness | export files | no |
| `generate_table_one` | 8 | locked plan + readiness | table and decision | no |
| `get_approval_card` | all | bootstrap allowed | UX artifacts | no |
| `get_autoresearch_status` | 8 | project context | progress event | no |
| `get_blocker_playbook` | all | bootstrap allowed | UX artifacts | no |
| `get_decision_log` | all | project exists | decision log read | yes |
| `get_deviation_log` | all | project exists | deviation log read | yes |
| `get_exploration_board` | 8 | project context | board snapshot | no |
| `get_harness_dashboard` | all | project exists | UX artifacts | no |
| `get_pipeline_status` | all | project exists | status | yes |
| `get_workflow_contract` | all | server-resolved state | next legal action | yes |
| `init_project` | 0 | name + mode validation | project and UX artifacts | no |
| `load_dataset` | 1 | format/size/PII | session dataset | no |
| `log_deviation` | all | project exists | append deviation | no |
| `open_exploration_branch` | 8 | locked plan + readiness | branch event | no |
| `profile_dataset` | 2 | dataset exists | profile artifacts | no |
| `promote_branch_to_plan_amendment` | 8 | fresh audit + human confirmation | amendment, never auto-merge | no |
| `propose_analysis_plan` | 4 | confirmed concept; draft then confirm | draft plan | no |
| `register_analysis_plan` | 5-6 | review + human confirmation | locked plan | no |
| `resume_autoresearch_run` | 8 | governed project + remaining budget | resume decision | no |
| `run_advanced_analysis` | 8 | locked plan + readiness | results and decision | no |
| `run_audit` | 11 | project exists; diagnostics allowed | audit artifacts | no |
| `run_autoresearch_next_task` | 8 | governed project + lease + budget | experiment/evaluation | no |
| `run_autoresearch_queue` | 8 | governed project + lease + budget | bounded experiments | no |
| `run_branch_experiment` | 8 | governed branch | experiment ledger | no |
| `run_intake` | 1 | format/size/PII | intake and datasets | no |
| `run_repeated_measures` | 8 | locked plan + readiness | case ledger and decision | no |
| `scan_data_folder` | 1 | supported local files | file metadata | yes |
| `start_autoresearch_run` | 8 | locked plan + readiness + budget | run/queue/budget | no |
| `stop_autoresearch_run` | 8 | governed project | stop decision and queue | no |
| `suggest_branch_experiments` | 8 | project context | candidate suggestions | yes |
| `suggest_cleaning` | 8 | locked plan + readiness + quality | session cleaning proposal | no |
| `verify_audit_trail` | all | project exists | integrity result | yes |

## Focused evidence

- `test_mcp_v2.py`: v2 discovery, resources/prompts, structured failures, compatibility.
- `test_tool_edge_cases.py`: subject-aligned pairs, duplicate visits, failed
  statistical execution, required-plan coverage and artifact path boundaries.
- `test_clinical_engine.py`: clinical estimates, uncertainty and analyzed case sets.
- `test_autoresearch_contracts.py` and branch governance tests: agent proposals,
  durable baselines, design drift, recorded-only tasks, budgets and null-result review.
- Existing pipeline/report suites: stage gates, audit trail, report reconstruction,
  missing artifacts and publication readiness.
- Optional vendor integrations are separate: local test success does not assert a
  live external service is available or that a clinical model is appropriate.

See [MCP v2 design](mcp-v2.md), [clinical methods](clinical-methods.md) and
[autoresearch evidence contracts](autoresearch-design.md).
