# Pipeline Workflow Bylaw

> Version: 1.1.0 | Canonical RDE 13-phase artifact contract.

## Artifact Gate (H-008)

Before entering a phase, the prior required artifacts must exist unless the selected flow is explicitly marked as Quick Explore.

| Phase | Required artifact |
|-------|-------------------|
| 0 | `artifacts/phase_00_project_setup/project.yaml` |
| 1 | `artifacts/phase_01_data_intake/intake_report.json` |
| 2 | `artifacts/phase_02_schema_registry/schema.json` |
| 3 | `artifacts/phase_03_concept_alignment/concept_alignment.md` |
| 4 | `artifacts/phase_04_creative_ideation/greedy_analysis_candidates.json` |
| 5 | `artifacts/phase_05_plan_completeness_review/analysis_plan_review.json` |
| 6 | `artifacts/phase_06_plan_registration/analysis_plan.yaml` |
| 7 | `artifacts/phase_07_pre_explore_check/readiness_checklist.json` |
| 8 | `artifacts/phase_08_execute_exploration/decision_log.jsonl` |
| 9 | `artifacts/phase_09_collect_results/results_summary.json` |
| 10 | `artifacts/phase_10_report_assembly/eda_report.md` |
| 11 | `artifacts/phase_11_audit_review/audit_report.json` |
| 12 | `artifacts/phase_12_auto_improve/final_report.md` |

## Confirmation Gates

- Phase 3: concept-schema alignment requires user confirmation.
- Phase 5: plan completeness review requires user confirmation.
- Phase 6: plan registration locks the analysis plan.

## Plan Lock (H-007)

- Phase 8+ analysis requires a locked Phase 6 plan.
- Any execution departure from the locked plan must call `log_deviation()`.
- Decision and deviation logs are append-only under `artifacts/phase_08_execute_exploration/`.

## Quick Explore

Quick Explore may skip Phase 3-7 and Phase 9/11/12 only when the final report is clearly labeled `Quick Explore -- Not Audited`.

## automl-stat-mcp Delegation

Use automl-stat-mcp for advanced analyses such as PSM, survival analysis, ROC/AUC, advanced power analysis, regression/GLM, and machine learning. If the service is unavailable, fall back to local analysis only when the report and decision log state the limitation.
