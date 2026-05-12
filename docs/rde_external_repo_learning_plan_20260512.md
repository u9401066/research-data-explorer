# RDE External Repository Learning Plan

Date: 2026-05-12

## Positioning

RDE should not copy a single EDA, validation, AutoML, or MLOps repository. Its distinctive product contract is an agent harness for non-data-scientists: intake, schema, concept alignment, reviewed planning, readiness checks, auditable execution, interpretation, report assembly, audit, and auto-improvement.

The right strategy is therefore selective adoption: learn proven patterns from adjacent repositories, but keep RDE's 13-phase research governance and artifact-first contract as the spine.

## What To Learn

| Reference | What it does well | RDE adoption target |
| --- | --- | --- |
| ydata-profiling | Low-friction automated data profiling with shareable HTML/JSON output | Improve Quick Explore profile output while keeping Quick Explore explicitly unaudited |
| Great Expectations | Executable data quality expectations, expectation suites, and human-readable validation docs | Promote Phase 2 schema/profile/quality artifacts into reusable data contracts |
| Pandera | Schema-as-code validation at DataFrame boundaries | Add optional executable schema validators for loaded tabular data |
| Evidently | Data quality, drift, and evaluation reports for production ML/AI systems | Add longitudinal/sensitivity quality checks for repeated RDE runs |
| Kedro | Modular reproducible pipelines, data catalog, pipeline visualization | Add artifact catalog and phase DAG views for user-facing traceability |
| MLflow | Run metadata, experiment tracking, artifact registry, model lifecycle UI | Add run registry/version comparison across Phase 8 analyses and report exports |
| AutoGluon / H2O AutoML | Low-code model training, leaderboard, model comparison UX | Improve local-lite/automl delegation reporting without making predictive score the primary goal |
| OHDSI HADES / ATLAS / ACHILLES | Observational health analytics, cohort design, CDM-based evidence packages | Add biomedical domain gates: cohort definition, covariate balance, empirical calibration, and reporting checklists |

## Implementation Roadmap

### Track A: Data Contract Layer

Goal: make Phase 2 more than type inference.

- Persist `profile_summary.json`, `profile_report.md`, `quality_report.json`, and `quality_report.md`.
- Require profile and quality evidence in `report_readiness.data_quality`.
- Later: add optional expectation-suite export compatible with GX/Pandera-style checks.

### Track B: Guided Agent Harness

Goal: reduce dependence on an agent remembering the workflow.

- Add a guided orchestrator such as `continue_pipeline()` or `run_guided_eda()`.
- It should compute the next legal phase, execute safe automatic steps, and stop at Phase 3/4/5/6 confirmation gates.
- The orchestrator should emit approval cards instead of silently moving past user-confirmed gates.

### Track C: Semantic Report Quality

Goal: stop accepting reports that only contain tables and figures.

- Keep `semantic_report_quality.json` as a Phase 10 artifact.
- Check for interpretation, evidence-to-result linkage, limitations/caveats, and actionable recommendations.
- Later: add claim-level contradiction checks and unsupported-claim warnings.

### Track D: Claim Provenance

Goal: make formal reports clean while keeping every claim traceable.

- Emit `claim_provenance_manifest.json` for Phase 10 formal exports.
- Emit `final_report_claim_provenance_manifest.json` for Phase 12 final exports.
- Later: add claim IDs into DOCX/PDF as hidden comments or appendix tables when requested.

### Track E: Research-Grade Biomedical Extensions

Goal: learn from OHDSI without forcing every dataset into OMOP CDM.

- Add optional cohort-definition artifact.
- Add propensity diagnostics thresholds: SMD before/after, positivity/common support, weight truncation notes.
- Add reporting checklists by study type: observational cohort, diagnostic biomarker, prediction model, repeated measures.

### Track F: Run Registry And Comparisons

Goal: make repeated RDE runs comparable.

- Create a project-scoped run registry with report version, analysis count, readiness state, audit grade, figures, and claim count.
- Add comparison summaries between Phase 10/12 exports.
- Later: add a lightweight UI/HTML dashboard inspired by Kedro/MLflow style artifact navigation.

## Non-Goals

- Do not turn RDE into a pure AutoML leaderboard tool.
- Do not replace RDE's phase gates with notebook-style free execution.
- Do not make external engines mandatory for production reports; local-lite remains the no-Docker fallback.

## Success Criteria

- A non-data-scientist can see what step is next, what is blocked, and what artifact proves completion.
- A reviewer can trace every report claim to table, figure, result, readiness, or literature-context evidence.
- A report cannot pass production readiness by merely containing enough files; it must contain interpretable, limitations-aware narrative.
- Biomedical projects get stronger causal/observational safeguards without sacrificing general CSV/Excel usability.
