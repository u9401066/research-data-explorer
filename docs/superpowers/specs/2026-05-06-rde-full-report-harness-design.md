# RDE Full Report Harness Design

**Goal:** make the VSIX-installed Research Data Explorer reliably guide Copilot, Codex, and Cline through a complete auditable analysis report for each new real dataset.

**Decision:** keep the public workflow as 13 main phases. The 13-phase grain is enough for agent orchestration because each phase has a clear user-facing purpose, but each phase needs stricter sub-artifact gates. Adding more main phases would make agent prompts harder to follow; quality should be enforced by contracts inside the phases.

## Canonical 13-Phase Contract

The implementation enum in `src/rde/application/pipeline/__init__.py` is the source of truth:

| Phase | Directory | Tool Family | Required Gate |
|---|---|---|---|
| 0 | `phase_00_project_setup` | `init_project` | `project.yaml` |
| 1 | `phase_01_data_intake` | `scan_data_folder`, `run_intake`, `load_dataset` | intake report, PII result, source dataset selection |
| 2 | `phase_02_schema_registry` | `build_schema`, `profile_dataset`, `assess_quality` | schema, quality/profile artifacts |
| 3 | `phase_03_concept_alignment` | `align_concept(confirm=true)` | research question, role mapping, user confirmation |
| 4 | `phase_04_creative_ideation` | `propose_analysis_plan` | greedy candidates, visualization bundle, execution schedule draft |
| 5 | `phase_05_plan_completeness_review` | methodology review inside `register_analysis_plan` pre-lock flow | analysis plan review, coverage floor, user confirmation |
| 6 | `phase_06_plan_registration` | `register_analysis_plan(confirm=true)` | locked `analysis_plan.yaml`, execution schedule |
| 7 | `phase_07_pre_explore_check` | `check_readiness` | readiness checklist |
| 8 | `phase_08_execute_exploration` | analysis, cleaning, visualization tools | decision log, deviation log, execution artifacts |
| 9 | `phase_09_collect_results` | `collect_results` | results summary and plan coverage |
| 10 | `phase_10_report_assembly` | `assemble_report`, `export_report` | complete EDA report |
| 11 | `phase_11_audit_review` | `run_audit` | audit report |
| 12 | `phase_12_auto_improve` | `auto_improve`, `export_final_report`, `export_handoff`, `verify_audit_trail` | final report, handoff package, audit trail verification |

All docs, prompts, VSIX runtime strings, tests, memory-bank entries, and release audit scripts must use these names. The old `phase_04_plan_registration`, `phase_06_execute_exploration`, `Phase 3.5`, and "11-Phase / Phase 0-10" language is legacy compatibility text only and must not guide agent execution.

## Is 13 Phases Enough?

Yes, as the public workflow. The missing design piece is not more phases; it is phase-local completeness:

- Phase 1 must record source selection, loadability, format, size, PII evidence, and override status.
- Phase 2 must persist enough schema and loader metadata to survive MCP restarts.
- Phase 3 must reject unknown variables and unconfirmed role mappings in full-audit mode.
- Phase 4 must finish as a formal creative ideation artifact, not an informal Phase 3.5.
- Phase 5 must be a real review gate, even if implemented inside `register_analysis_plan` for the first release.
- Phase 8 must count only successful planned executions toward coverage.
- Phase 10-12 must produce report, audit, final report, and handoff as connected artifacts.

## Report Production Contract

Every full-audit run must have a report chain:

1. `phase_09_collect_results/results_summary.json`
2. `phase_10_report_assembly/eda_report.md`
3. `phase_11_audit_review/audit_report.json`
4. `phase_12_auto_improve/final_report.md`
5. optional DOCX/PDF exports from `export_report` or `export_final_report`
6. handoff package with decision/deviation logs from `export_handoff`

The report is not complete if it only has headings. It must cite artifact paths, include Table 1 when cohort/group analysis exists, include planned-analysis coverage, include decision/deviation appendices, and label quick explore reports as not audited.

## Analysis Sufficiency Contract

Analysis sufficiency is enforced by a rubric, not by a fixed number:

- Minimum families for full audit: descriptive overview, Table 1 when a group exists, group comparison when group/outcome exists, association/collinearity screening when multiple continuous variables exist, adjusted model when outcome and covariates support it, visualizations for descriptive and analytical findings.
- Planner output must include a coverage tag set and a schedule.
- `register_analysis_plan` must block under-scoped plans unless `allow_methodology_override=true` is explicit and recorded.
- `collect_results` must report planned versus successful execution coverage.
- `run_audit` must grade plan coverage, method suitability, effect sizes, multiple-comparison handling, report integrity, PII safety, and reproducibility.

## Harness Design

The VSIX should support three agent families:

- Copilot: VS Code MCP provider, `@rde` chat participant, `.github/agents`, `.github/prompts`, `.github/copilot-instructions.md`.
- Codex: `.codex/skills`, AGENTS.md-compatible instructions, and optional MCP config instructions that do not overwrite user settings.
- Cline: `.cline/skills`, `.clinerules`, and Cline MCP settings merge behavior.

Workspace setup must be idempotent and non-destructive. Existing user files are not overwritten without a backup or explicit user action. Setup should use a manifest/hash so stale bundled assets can be detected.

## Cross-Platform Design

Supported release path must be verified on Windows, macOS, and Linux:

- `uv` discovery returns an executable path or provides an environment with enriched `PATH`.
- MCP launch works from GUI VS Code where shell startup files may not run.
- VSIX package excludes `.venv`, `node_modules`, prior `.vsix`, caches, and test outputs.
- Install smoke tests run at least package/contents checks everywhere; activation smoke is required where CI display support exists.

## Subagent and Rule Usage

The harness should use subagents in two places:

- Development workflow: independent implementation/review tasks can be delegated with disjoint write sets.
- Product workflow: generated agent instructions should encourage specialist review roles after report assembly: statistics reviewer, privacy/audit reviewer, report completeness reviewer, and reproducibility reviewer. These reviewers inspect artifacts; they do not bypass MCP tools or edit analysis logs.

Rules, hooks, and workflows should become executable checks:

- `agent-control.yaml` must be machine-checked against `PipelinePhase`.
- VSIX tool allowlist must match registered MCP tools.
- release scripts must exist before release docs reference them.
- hooks for PII, artifact gates, report sanitization, and append-only logs must have tests.

## Implementation Phases

Phase 1 fixes the canonical contract and Python pipeline so full MCP flow can progress.

Phase 2 fixes VSIX runtime, bundle hygiene, setup scripts, and agent-family coverage.

Phase 3 synchronizes memory/docs/release harness, then verifies, commits, pushes, and tags `v0.4.5`.
