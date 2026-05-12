# RDE Maintenance Record - KMU SPARK AKI Report

- Date: 2026-05-12
- Project ID: `19515b47`
- Project directory: `data/projects/20260512_090653_kmu_spark_aki_cr_eda_19515b47`
- Request: run RDE MCP, PubMed MCP, and asset-aware related MCPs to produce a full RDE report from the supplied KMU SPARK AKI files.

## MCP Availability

- RDE MCP was available and used for Phase 0 through Phase 12.
- PubMed Search MCP was available and used through `unified_search` and `prepare_export`.
- Asset-Aware MCP tools were not registered in the current MCP registry. No callable `asset-aware-mcp/*` namespace was available.

Blocker text:

```text
BLOCKER: Asset-Aware MCP tools are not registered in the current MCP registry. No `asset-aware-mcp/*` namespace/tools are callable. This repo snapshot only exposes the RDE MCP server (`research-data-explorer`); asset-aware references appear to be stale assistant/rule assets and point to missing runtime files (`src.presentation.server`, `scripts/install_cline_mcp.py`). Reload/restart the MCP host after installing/registering the Asset-Aware MCP server; do not proceed with DOCX/DFM asset workflows using shell substitutes.
```

## Issues Found And Actions Taken

1. RDE Phase 3 rejected custom role keys `ids` and `dates`.
   - Action: reran `align_concept` using accepted keys: `outcome`, `group`, and `covariates`.
   - Impact: no data loss; ID/date fields remained unassigned and excluded from primary modeling.

2. Multi-dataset state polluted Phase 7 readiness.
   - Cause: after loading the supplementary specimen-record Excel, `check_readiness` used the last loaded n=6 dataset rather than the locked primary n=51 dataset.
   - Action: reloaded the primary AKI results Excel, rebuilt schema, and reran readiness so H-003 passed with n=51.
   - Impact: supplementary specimen dataset was treated as context only; primary analysis remained on the 51-row results dataset.

3. `compare_groups` failed on Windows with long artifact paths.
   - Symptom: `No such file or directory` for a generated filename containing the long Chinese group variable and multiple outcome names.
   - Code fix: updated `src/rde/interface/mcp/tools/analysis_tools.py`.
   - Change: `_unique_phase_artifact_filename()` now calls `_shorten_artifact_filename()`, which truncates long leaf filenames and appends a stable SHA-1 hash before checking uniqueness.
   - Impact: new RDE MCP subprocess loaded the patched code and successfully wrote compare-group artifacts.

4. Main MCP server did not hot-reload patched code.
   - Action: launched a new RDE MCP subprocess via `uv run --directory <repo> python -m rde` and called RDE tools through MCP stdio to complete the affected `compare_groups` step.
   - Impact: same project artifact store and decision log were used.

5. RDE cleaning suggestions proposed median-fill for ID/date/text columns.
   - Action: did not approve those suggestions; called `apply_cleaning` with an empty approval list.
   - Impact: no raw values were altered; missing data was handled by the registered pairwise strategy.

6. Numeric-coded categorical variables were not consistently protected from continuous summaries.
   - Symptom: `schema.json` labeled `Sex_1_2` as `binary`, and Table 1/compare-groups treated it as categorical, but `analyze_variable` prioritized pandas numeric dtype and emitted mean/std plus Shapiro-Wilk normality output.
   - Related symptom: `降血壓用藥_1_NTG_2_Trandate_3_1_2` is a coded grouping variable, but the Phase 7 normality preview listed it because its Phase 2 inferred type was `continuous`.
   - Code fix: updated `src/rde/application/use_cases/analyze_variable.py` so semantic categorical types (`binary`, `categorical`, `ordinal`, `datetime`, `text`, `id`) and role-based categorical fields (`group`, `id`) are handled before numeric dtype checks.
   - Guard fix: updated `src/rde/interface/mcp/tools/discovery_tools.py` and `src/rde/interface/mcp/tools/profiling_tools.py` so numeric stats are only attached to `continuous`/`biomarker` variables.
   - Guard fix: updated `src/rde/interface/mcp/tools/analysis_tools.py` so `correlation_matrix` only includes `continuous`/`biomarker` numeric variables whose role is not `group`/`id`.
   - Guard fix: updated `src/rde/interface/mcp/tools/plan_tools.py` so Phase 7 normality previews exclude variables whose role is `group`/`id`.
   - Artifact fix: removed obsolete continuous `stats` from `artifacts/phase_02_schema_registry/schema.json` for `Sex_1_2`; corrected `降血壓用藥_1_NTG_2_Trandate_3_1_2` to `categorical` / `group`.
   - Report fix: added a variable-type correction note to `eda_report.md` and `final_report.md`, then re-exported DOCX/PDF.
   - Audit note: recorded deviation #2 documenting that old numeric-coded categorical mean/std/Shapiro output should be ignored.
   - Verification: a fresh RDE MCP subprocess now returns `Sex_1_2: binary` with category counts (`2.0: 33`, `1.0: 15`) and no descriptive mean/std or Shapiro-Wilk section.

7. Durable autoresearch was not actually running during the original report generation.
   - Symptom: `get_autoresearch_status(project_id="19515b47")` returned "No autoresearch run has been started"; the report had the governed Phase 8 analyses plus one planned advanced model, but no durable autonomous branch queue.
   - Action: started corrective autoresearch runs and inspected the branch board, work queue, experiment ledger, and branch result artifacts.
   - Finding: the original branch runner created auditable branch/experiment ledgers, but `analysis_contract` entries such as `run_advanced_analysis` were not executed. This made autonomous branches look active while not producing live advanced-model evidence.
   - Code fix: updated `src/rde/interface/mcp/tools/branch_tools.py` so `_execute_autoresearch_next_task()` executes supported live `analysis_contract` payloads through the RDE analysis delegator, writes branch-scoped JSON/MD result artifacts, and marks failed contracts as failed work items instead of silently recording placeholder evidence.
   - Evidence policy fix: removed fake runner p-values/effect sizes from ledger-only branches. Ledger-only branches now explicitly say `contract_executed=false`; live advanced branches say `contract_executed=true` and include source, metrics, and analysis artifacts.
   - Verification test: added `test_autoresearch_executes_live_advanced_analysis_contract` in `tests/test_exploration_branch_loop.py`.

8. Corrective autoresearch initially exposed two additional harness problems.
   - Run `ar_c95a12db9d` was stopped after a shell timeout while testing live branch execution.
   - Run `ar_1d8253869d` confirmed live advanced execution (`br_93b1c983dd`, `exp_3b4f33a223_multiple_regression.*`) but showed a slow statsmodels branch path and an invalid logistic target for the 7-level coded drug variable.
   - Code fix: branch live contracts now default to a fast local-lite backend for autonomous exploration unless a contract explicitly requests another backend. Branch figure generation is opt-in via `analysis_contract.create_figures=true`, so the autonomous queue cannot be blocked by branch-specific figure rendering.
   - Code fix: branch suggestions now require logistic-regression targets to be truly binary and outcome-like; binary demographic covariates such as `Sex_1_2` and multi-level coded categories such as `降血壓用藥_1_NTG_2_Trandate_3_1_2` are not promoted as logistic clinical endpoints.
   - Code fix: `src/rde/domain/services/variable_classifier.py` now treats low-cardinality numeric coded-category names as categorical before continuous heuristics. A fresh `load_dataset` MCP call now reports `降血壓用藥_1_NTG_2_Trandate_3_1_2` as `categorical` and `Sex_1_2` as `binary`.
   - Corrective run: `ar_09e5a5b3d5` completed 8/8 tasks with 0 failures. It produced live advanced branch artifacts:
     - `artifacts/phase_08_execute_exploration/branch_results/br_4fd540fc3a/experiments/exp_0e8c8ed6a7_multiple_regression.json`
     - `artifacts/phase_08_execute_exploration/branch_results/br_4fd540fc3a/experiments/exp_0e8c8ed6a7_multiple_regression.md`
     - `artifacts/phase_08_execute_exploration/branch_results/br_3e9a44deec/experiments/exp_734c9598db_multiple_regression.json`
     - `artifacts/phase_08_execute_exploration/branch_results/br_3e9a44deec/experiments/exp_734c9598db_multiple_regression.md`
   - Corrective run metrics: local-lite adjusted regression for `Creatinine_normalized` completed with `nobs=47`, `r_squared=0.2594`, `contract_executed=true`, source `local-lite (numpy)`.
   - Report refresh: reran `collect_results`, `assemble_report`, `export_report(formats="docx,pdf")`, and `run_audit` after the corrective run. `results_summary.json` now reports 33 exploratory branches and 31 branch experiments; the report appendix includes the corrective live multiple-regression branch decisions. Historical failed/stopped attempts remain visible by design because RDE decision/deviation logs are append-only.
   - Verification tests:
     - `uv run ruff check src/rde/interface/mcp/tools/branch_tools.py tests/test_exploration_branch_loop.py`
     - `uv run python -m pytest tests/test_exploration_branch_loop.py::test_branch_suggestions_cover_common_medical_eda_patterns tests/test_exploration_branch_loop.py::test_branch_suggestions_do_not_use_nonbinary_categorical_logistic_target tests/test_exploration_branch_loop.py::test_branch_suggestions_do_not_treat_baseline_binary_covariate_as_outcome tests/test_exploration_branch_loop.py::test_autoresearch_executes_live_advanced_analysis_contract -q`
     - `uv run ruff check src/rde/domain/services/variable_classifier.py tests/test_heuristic_policy.py`
     - `uv run python -m pytest tests/test_heuristic_policy.py::test_variable_classifier_treats_numeric_coded_drug_column_as_categorical tests/test_heuristic_policy.py::test_variable_classifier_keeps_low_cardinality_plain_numeric_as_ordinal -q`

9. Autoresearch branch outputs did not materially refresh report figures or derive exposure contrasts.
   - Symptom: after the corrective autoresearch run, exported DOCX/PDF still showed the same old visualization set because most new branch evidence was saved as branch JSON/MD only; no new branch-specific figures were registered in `figures/visualization_manifest.json`.
   - Related gap: the multi-level treatment/group variable was correctly protected from invalid logistic regression, but autonomous RDE did not create a branch-local binary contrast for common observational analyses such as propensity scoring.
   - Code fix: updated `src/rde/interface/mcp/tools/branch_tools.py` so branch `analysis_contract` payloads may declare `derived_variables`; the runner can now build a dominant-level-vs-other binary exposure before running live advanced analyses.
   - Code fix: branch suggestions now prefer role-confirmed outcomes over raw plan variable lists, queue adjusted models for multiple continuous outcomes, set `create_figures=true` for live adjusted/logistic/propensity branches, and add a derived binary propensity-score branch for multi-level exposure variables.
   - Code fix: updated `src/rde/infrastructure/adapters/analysis_delegator.py` and `src/rde/interface/mcp/tools/analysis_tools.py` so local-lite propensity scoring returns scored rows and automatically creates a propensity-score overlap histogram.
   - Verification tests added/updated:
     - `tests/test_exploration_branch_loop.py::test_branch_suggestions_create_derived_propensity_for_multilevel_group`
     - `tests/test_exploration_branch_loop.py::test_autoresearch_derived_dominant_binary_contrast`
     - `tests/test_analysis_delegation.py::test_delegator_propensity_score_local_lite_returns_score_diagnostics`

10. Phase 12 final-report export dropped all figures when manifest paths were project-relative.
   - Symptom: `export_report` embedded 22 figures, but `export_final_report` reported `圖表總數: 0` even though `artifacts/phase_08_execute_exploration/visualization_manifest.json` existed and the figure files were present.
   - Cause: Phase 12 export checked manifest `output_path` values with `Path(...).exists()` relative to the current process directory. RDE manifests commonly store paths such as `figures/example.png`, which should be resolved relative to the project output directory.
   - Code fix: updated `src/rde/interface/mcp/tools/audit_tools.py` so `_load_visualization_entries()` resolves relative figure paths against `project.output_dir`, deduplicates repeated manifest paths, and preserves figure category metadata for the final gallery.
   - Verification test: updated `tests/test_report_contract.py::test_build_phase10_export_report_includes_table_and_figures` to cover project-relative manifest paths.

11. Product-level RDE harness gaps remained after the project-specific report refresh.
   - Gap: common medical EDA patterns were embedded in MCP branch-tool logic instead of a reusable/testable planner.
   - Code fix: added `src/rde/domain/services/common_medical_eda_pack.py`; branch suggestions now call the domain service and include formal univariate, bivariate, adjusted-model, logistic, propensity, survival, ROC, repeated-measures, missingness, subgroup, and visualization candidates. Executable adjusted/propensity contracts are kept early in the queue so durable autoresearch actually runs live analyses.
   - Gap: branch-local derived variables were only stored inside individual branch result JSON files.
   - Code fix: added `src/rde/domain/services/derived_variable_registry.py`; autoresearch now writes `artifacts/phase_08_execute_exploration/derived_variable_registry.json` with branch ID, experiment ID, source variable, operation, positive class, counts, and analysis type.
   - Gap: local-lite propensity scoring was only a score/overlap preview.
   - Code fix: expanded `src/rde/infrastructure/adapters/analysis_delegator.py` so propensity scoring now returns stabilized IPTW weights, weighted balance diagnostics, nearest-neighbor matched pairs, matched balance diagnostics, matching summaries, and full scored-row output up to the safety cap.
   - Figure fix: updated `src/rde/interface/mcp/tools/analysis_tools.py` so propensity branches can register both overlap histograms and Love plots.
   - Gap: Phase 10 and Phase 12 had separate visualization path-resolution behavior.
   - Code fix: added `src/rde/domain/services/report_asset_contract.py`; report and audit export paths now use the same project-scoped manifest resolver.
   - Gap: production readiness could still pass without a method-depth contract.
   - Code fix: updated `src/rde/interface/mcp/tools/report_tools.py` and `src/rde/interface/mcp/tools/audit_tools.py`; readiness/audit now include an `analysis_depth` gate for applicable univariate, bivariate, multivariable, propensity/balance, derived-variable provenance, and sensitivity/branch-review requirements.
   - Gap: autoresearch branches required a manual `evaluate_branch()` call before any plan-amendment candidate artifact existed.
   - Code fix: `_execute_autoresearch_next_task()` now auto-evaluates completed branch evidence, writes promotion review/gate artifacts, and writes `plan_amendments/candidates/<branch_id>.json|md` when evidence meets the gate. It still does not append `plan_amendments.jsonl` or mark the branch promoted until `promote_branch_to_plan_amendment(confirm=True)` is explicitly called.
   - Cleanup: removed an unused `ProjectStatus` import in `src/rde/application/session.py` so full-repo ruff passes.
   - Verification tests added/updated:
     - `tests/test_exploration_branch_loop.py::test_common_medical_eda_pack_is_domain_service`
     - `tests/test_exploration_branch_loop.py::test_autoresearch_derived_variables_write_registry`
     - `tests/test_exploration_branch_loop.py::test_autoresearch_auto_evaluation_writes_candidate_without_confirmed_promotion`
     - `tests/test_analysis_delegation.py::test_delegator_propensity_score_local_lite_returns_score_diagnostics`
     - `tests/test_report_contract.py::test_report_readiness_flags_missing_medical_analysis_depth`
     - `tests/test_report_contract.py::test_report_readiness_accepts_completed_medical_analysis_depth`

12. Fresh MCP refresh exposed stale dataset-id recovery and role-parser edge cases.
   - Symptom: a newly launched RDE MCP subprocess loaded the project artifacts but branch live contracts tried to rehydrate `schema.json.dataset_id` while `intake_report.json.dataset_id` still pointed at an older dataset id. The old recovery path could report the schema id as available but fail to reload the dataframe for that id.
   - Code fix: updated `src/rde/interface/mcp/tools/_shared/project_context.py` so project dataset recovery merges project, intake, schema, and concept-alignment dataset ids; `ensure_dataset(project=...)` now tries session entries and artifact-backed rehydration in reverse priority order instead of blindly selecting one stale id.
   - Symptom: `research_question` text could be interpreted as a covariate when it happened to contain words such as baseline.
   - Code fix: tightened role extraction in `common_medical_eda_pack.py` and report readiness so long narrative fields are not treated as variables, while nested `variable_roles` maps (`variable -> role`) are still supported.
   - Corrective run: launched a fresh RDE MCP subprocess after the code fixes and ran `ar_ab652571c4`. It completed 11/11 tasks, failed 0, and produced a derived propensity contrast registry at `artifacts/phase_08_execute_exploration/derived_variable_registry.json`.
   - Corrective run outputs: refreshed `eda_report.docx/pdf` and `final_report.docx/pdf`; `export_report` embedded 23 figures and `export_final_report` included 23 figures.
   - Corrective audit: `run_audit` returned A, 145/145. `final_report_export_manifest.json` shows `analysis_depth.ready=true` and all 6 required checks passed.
   - Verification tests added/updated:
     - `tests/test_pipeline_integration.py::test_project_bound_dataset_rehydrates_when_schema_dataset_id_changed`
     - `tests/test_exploration_branch_loop.py::test_common_medical_eda_pack_is_domain_service`

13. Phase 10 exported DOCX/PDF did not match `phase_10_report_assembly/eda_report.md`.
   - Symptom: the canonical markdown report contained `Advanced Analyses`, `Figure Gallery`, and Appendix A-D, but `artifacts/exports/eda_report.docx` was generated from a second, partially rebuilt `EDAReport` object and omitted those sections.
   - Cause: `export_report()` regenerated report sections from upstream artifacts instead of treating `phase_10_report_assembly/eda_report.md` as the single source of truth. The regenerated path also did not include the advanced-analysis markdown bundle, figure gallery, or appendices added by `assemble_report()`.
   - Code fix: updated `src/rde/interface/mcp/tools/report_tools.py` so `export_report()` builds its export object directly from the assembled markdown, preserving Phase 10 sections, figure gallery, appendices, title, dataset id, and generated timestamp.
   - Code fix: updated `src/rde/infrastructure/adapters/docx_exporter.py` and `src/rde/application/use_cases/export_report.py` so standard markdown image links (`![...](...png)`) are embedded inline in DOCX/PDF and are not auto-attached a second time.
   - Corrective run: re-ran RDE MCP `export_report(project_id="19515b47", formats="docx,pdf", allow_incomplete=True)`. The refreshed Phase 10 export reports 23 embedded figures.
   - Verification tests added/updated:
     - `tests/test_report_contract.py::test_build_report_from_assembled_markdown_preserves_phase10_source_sections`
     - `tests/test_report_contract.py::test_export_report_attach_figures_respects_markdown_image_references`

14. Figure evidence entries disappeared from Phase 10 exports when multiple analyses reused the same image file.
   - Symptom: `visualization_manifest.json` contained 41 figure evidence entries, but the regenerated `eda_report.md`/DOCX displayed only 23 Figure Gallery entries. The omitted entries were not missing files; they reused an existing PNG path for a different analysis/caption.
   - Cause: Phase 10 `_format_figure_gallery()` and the shared `report_asset_contract.resolve_visualization_manifest_entries()` deduplicated by resolved image path. That behavior is acceptable for file inventory but incorrect for report evidence, because each manifest row is a distinct analytical deliverable.
   - Code fix: updated `src/rde/domain/services/report_asset_contract.py` to preserve one resolved entry per manifest row while still tagging duplicate image paths with `duplicate_of`.
   - Code fix: updated `src/rde/interface/mcp/tools/report_tools.py` so Figure Gallery numbering is sequential over included manifest entries and does not skip repeated image paths.
   - Corrective run: re-ran RDE MCP `assemble_report(project_id="19515b47", title="KMU SPARK AKI EDA Report", allow_incomplete=True)` and `export_report(project_id="19515b47", formats="docx,pdf", title="KMU SPARK AKI EDA Report", allow_incomplete=True)`. The refreshed Phase 10 export reports 41 embedded figure placements.
   - Corrective run: re-ran `export_final_report(project_id="19515b47", formats="docx,pdf", title="KMU SPARK AKI Final Report", allow_incomplete=True)`. The refreshed final export manifest reports 41 figures.
   - Verification tests added/updated:
     - `tests/test_report_contract.py::test_format_figure_gallery_preserves_manifest_entries_that_reuse_image_file`
     - `tests/test_report_contract.py::test_build_phase10_export_report_includes_table_and_figures`

15. Phase 10 reports could still be too artifact-heavy, with tables/figures but insufficient interpretation.
   - Symptom: the report met table/figure deliverable checks, but the main narrative still read like an artifact bundle: Table 1, model outputs, and Figure Gallery were present without a required figure/table interpretation layer or PubMed-context discussion.
   - Product gap: RDE is an agent harness for non-data-scientists, so Phase 10 must require the agent to convert artifacts into interpretable scientific prose, not only export tables and images.
   - Code fix: added `interpretation_discussion` to the required report sections in `src/rde/domain/models/report.py` and the generated report section list in `src/rde/application/use_cases/generate_report.py`.
   - Code fix: added `src/rde/interface/mcp/tools/report_tools.py::_build_interpretation_discussion()`, which builds Table 1 interpretation, 1 paragraph per figure/evidence entry with suggested action, advanced-model interpretation, PubMed-literature discussion, and study-level recommendations.
   - Code fix: Phase 10 `assemble_report()` now loads `phase_10_report_assembly/pubmed_literature_context.md` when present and injects it into `Interpretation and Literature Context`.
   - Code fix: Phase 12 final DOCX/PDF export now also includes the required interpretation/literature section by reusing the same builder in `src/rde/interface/mcp/tools/audit_tools.py`.
   - Corrective run: re-ran `assemble_report`, `export_report`, and `export_final_report` for project `19515b47`. The refreshed `eda_report.md` increased to 10,478 words and includes 41 figure-interpretation subsections plus PubMed-context discussion.
   - Verification tests added/updated:
     - `tests/test_report_contract.py::test_build_interpretation_discussion_links_figures_table_and_pubmed_context`

16. Formal DOCX/PDF exports still looked like internal RDE reports and Word figure rendering remained unstable.
   - Symptom: `artifacts/exports/eda_report.docx` contained valid image relationships, but Word display could still be abnormal because the embedded PNGs preserved RGBA transparency. The DOCX body also still exposed internal report elements such as project metadata, appendix/decision-log style material, artifact paths, and pipeline identifiers.
   - Code fix: updated `src/rde/infrastructure/adapters/docx_exporter.py` so every DOCX figure is normalized through a Word-safe RGB PNG stream with a white background before insertion. Captions are centered and the original audit image files are left unchanged.
   - Code fix: added a formal research export profile in `src/rde/interface/mcp/tools/report_tools.py`. `export_report()` now builds a publication-facing `EDAReport` for DOCX/PDF and writes `artifacts/exports/eda_report_formal_source.md` as the comparable formal source. The Phase 10 audit markdown remains available separately at `phase_10_report_assembly/eda_report.md`.
   - Code fix: updated `src/rde/infrastructure/adapters/markdown_renderer.py` and `docx_exporter.py` so formal exports suppress Dataset/Project/Generated title metadata and private metadata footers.
   - Corrective run: re-ran RDE MCP `export_report(project_id="19515b47", formats="docx,pdf", title="KMU SPARK AKI EDA Report", allow_incomplete=True)`.
   - Verification: extracted the regenerated DOCX and confirmed 41 image placements, 23 unique media files, all inspected media are RGB, and the formal DOCX/source no longer contain `Decision Log`, `phase_08_execute_exploration`, `Artifact:`, `Dataset:`, `Project:`, `Generated:`, or `Metadata`.
   - Verification tests added/updated:
     - `tests/test_report_contract.py::test_build_formal_research_report_excludes_internal_audit_dump`
     - `tests/test_report_contract.py::test_docx_exporter_normalizes_rgba_images_to_rgb_stream`

17. Harness self-review found remaining production-readiness gaps in phase labels, data-quality evidence, auto-improve depth, semantic report quality, formal narrative generality, and claim provenance.
   - Product question: agent harness should guide user intent, but durable guarantees must live in MCP/runtime code so they can be tested and audited.
   - Code fix: corrected user-facing Phase 11/12 audit/auto-improve labels and Phase 9 collect-results labels.
   - Code fix: `profile_dataset()` and `assess_quality()` now persist Phase 2 profile/quality artifacts when an active project is available.
   - Code fix: `report_readiness` now includes `data_quality` and `semantic_report_quality` gates; `run_audit()` scores both as explicit audit categories.
   - Code fix: `auto_improve()` now repairs missing Phase 2 profile/quality summaries from schema evidence when full profiling artifacts are absent, refreshes readiness, emits `semantic_report_quality.json`, and writes claim provenance.
   - Code fix: formal report abstract/variable summary/conclusions no longer hard-code AKI biomarker language; they derive focus from concept alignment, variable roles, schema, and collected results.
   - Code fix: Phase 10 and Phase 12 exports now include claim provenance manifests so formal reports can stay clean without losing claim-level traceability.
   - Planning doc added: `docs/rde_external_repo_learning_plan_20260512.md`.
   - Verification tests added/updated:
     - `tests/test_report_contract.py::test_report_readiness_requires_phase2_profile_and_quality_artifacts`
     - `tests/test_report_contract.py::test_report_readiness_requires_semantic_report_quality`
     - `tests/test_report_contract.py::test_build_formal_research_report_uses_generic_study_narrative`
     - `tests/test_report_contract.py::test_build_claim_provenance_manifest_links_tables_figures_results_and_literature`
     - `tests/test_report_contract.py::test_auto_improve_repairs_profile_quality_semantic_and_claim_artifacts`

18. Figure captions and interpretation could still become narrative-only "storytelling" without a structured evidence harness.
   - Symptom: formal report sections had `圖說與解讀`, but each figure only carried a free-text interpretation and suggested action, so the output could read like a repetitive caption gallery.
   - Product gap: RDE should force agents to evaluate each figure as evidence, not merely describe the visible pattern.
   - Code fix: added a structured figure interpretation harness with required fields for evidence role, visual read, statistical support, validity caveat, reportable claim, and next analysis.
   - Code fix: Phase 10 `assemble_report()` now writes `phase_10_report_assembly/figure_interpretation_harness.json` whenever figures are available.
   - Code fix: `semantic_report_quality` now requires `structured_figure_interpretation` when a visualization manifest exists.
   - Code fix: Phase 12 `auto_improve()` can regenerate the figure interpretation harness before recomputing readiness.
   - Verification tests added/updated:
     - `tests/test_report_contract.py::test_build_interpretation_discussion_links_figures_table_and_pubmed_context`
     - `tests/test_report_contract.py::test_semantic_report_quality_requires_structured_figure_harness`

19. Multi-workbook/multi-sheet raw data coverage was not enforced.
   - Symptom: the raw directory contained 2 Excel workbooks and 19 total worksheets, but Phase 1 legacy intake loaded only `AKI_results-Cr_1-50_20250516(norm)_20250601.xlsx` / `raw-4hr` into the canonical 51-row, 18-column analysis table.
   - Finding: the existing analysis/report therefore covers the selected canonical table, not every raw workbook or every data-like worksheet.
   - Code fix: `run_intake()` now writes `phase_01_data_intake/raw_data_coverage.json|md` with loaded files, unloaded loadable files, selected sheets, unselected data-candidate sheets, and recommendations.
   - Code fix: `report_readiness` now includes `raw_file_coverage` and `raw_sheet_coverage` under the data-quality contract, so production readiness cannot silently pass when multi-file or multi-sheet raw coverage is unresolved.
   - Report fix: Phase 10 data overview and formal DOCX/PDF exports now explicitly state that raw coverage is unresolved and that the report must not be interpreted as complete analysis of all original Excel sheets.
   - Current project artifact repair: wrote `raw_workbook_inventory.json|md` and `raw_data_coverage.json|md`; the repair records 1 unloaded workbook and 18 unselected/unloaded data-like sheets.
   - Verification tests added:
     - `tests/test_report_contract.py::test_report_readiness_flags_unresolved_raw_workbook_sheet_coverage`
     - `tests/test_report_contract.py::test_format_data_overview_surfaces_partial_raw_coverage`

20. Phase 7 readiness was too broad for multi-sheet derived tables.
   - Symptom: the 50-row x 118-column multi-sheet derived master could make `check_readiness()` scan broad derived/QC columns instead of the variables that were actually locked in Phase 6.
   - Product gap: Phase 7 should validate the registered analysis plan, not every possible worksheet-derived column.
   - Code fix: `check_readiness()` now builds a `locked_plan_and_concept_roles` scope from `analysis_plan.yaml` and `variable_roles.json`, then limits normality, missingness, and collinearity prechecks to scoped analysis variables.
   - Artifact fix: `readiness_checklist.json` now stores the scoped variable set, counts, missing-from-dataset list, and scoped continuous/collinearity/missingness variables.
   - Verification tests added:
     - `tests/test_pipeline_integration.py::test_check_readiness_scopes_prechecks_to_locked_plan_variables`

21. Phase 8 plan-adherence checks ignored the locked execution schedule.
   - Symptom: `apply_cleaning(approved_indices=[])` was present in the Phase 6 `execution_schedule`, but S-011 still logged it as off-plan because adherence only checked `analyses`.
   - Product gap: RDE should treat scheduled preparatory steps as part of the locked plan contract.
   - Code fix: `check_plan_adherence()` now checks both `analyses` and `execution_schedule`, using the same tool-name synonym map and variable/name matching rules.
   - Verification tests added:
     - `tests/test_plan_adherence.py::TestCheckPlanAdherence::test_tool_matches_locked_execution_schedule`

## Outputs Produced

- RDE report Markdown: `artifacts/phase_10_report_assembly/eda_report.md`
- Final report Markdown: `artifacts/phase_12_auto_improve/final_report.md`
- Exported report DOCX/PDF: `artifacts/exports/eda_report.docx`, `artifacts/exports/eda_report.pdf`
- Exported final DOCX/PDF: `artifacts/phase_12_auto_improve/exports/final_report.docx`, `artifacts/phase_12_auto_improve/exports/final_report.pdf`
- Handoff package: `artifacts/handoff_package`
- PubMed context: `artifacts/phase_10_report_assembly/pubmed_literature_context.md`
- Raw workbook inventory: `artifacts/phase_01_data_intake/raw_workbook_inventory.json`, `artifacts/phase_01_data_intake/raw_workbook_inventory.md`
- Raw data coverage manifest: `artifacts/phase_01_data_intake/raw_data_coverage.json`, `artifacts/phase_01_data_intake/raw_data_coverage.md`
- Corrective autoresearch run: `ar_09e5a5b3d5`
- Final corrective six-fix autoresearch run: `ar_ab652571c4`
- Autoresearch board: `artifacts/phase_08_execute_exploration/exploration_board.json`
- Refreshed branch-aware results summary: `artifacts/phase_09_collect_results/results_summary.json`

## Verification

- RDE audit grade: A, 130/130.
- Audit trail: H-008, H-009, and H-010 passed.
- Phase 8 coverage: exceeded locked-plan threshold.
- Regression tests after the numeric-coded categorical semantic-type fix: `uv run python -m pytest -q` → 224 passed, 5 skipped.
- Targeted autoresearch harness tests after live-contract fix: passed.
- Corrective autoresearch queue after harness fix: `ar_09e5a5b3d5` completed 8/8 tasks, failed 0, queue depth 0.
- Refreshed RDE audit after report regeneration: A, 130/130.
- Deep-refresh autoresearch queue after derived-variable/figure fix: `ar_aa463c3d75` completed 9/9 tasks, failed 0, queue depth 0.
- Refreshed EDA export after deep run: `export_report(formats="docx,pdf")` embedded 22 figures.
- Refreshed Phase 12 final export after relative-path/dedup fix: `export_final_report(formats="docx,pdf")` embedded 22 deduplicated figures.
- Final full regression suite after all harness fixes: `uv run python -m pytest -q` → 232 passed, 5 skipped.
- Product-level six-fix regression suite: `.venv\Scripts\python.exe -m pytest -q` → 238 passed, 5 skipped.
- Product-level lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
- Phase 10 markdown-to-DOCX export fix: `.venv\Scripts\python.exe -m pytest -q` → 240 passed, 5 skipped.
- Phase 10 markdown-to-DOCX export lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
- Figure evidence preservation fix: `.venv\Scripts\python.exe -m pytest -q` → 241 passed, 5 skipped.
- Figure evidence preservation lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
- Interpretation/literature harness fix: `.venv\Scripts\python.exe -m pytest -q` → 242 passed, 5 skipped.
- Interpretation/literature harness lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
- Formal export / Word-safe image fix: `.venv\Scripts\python.exe -m pytest -q` → 244 passed, 5 skipped.
- Formal export / Word-safe image lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
- Harness self-review 2-7 fix full regression: `.venv\Scripts\python.exe -m pytest -q` → 249 passed, 5 skipped.
- Harness self-review 2-7 lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
- Structured figure interpretation harness full regression: `.venv\Scripts\python.exe -m pytest -q` → 250 passed, 5 skipped.
- Structured figure interpretation harness lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
- Raw workbook/sheet coverage gate full regression: `.venv\Scripts\python.exe -m pytest -q` → 252 passed, 5 skipped.
- Raw workbook/sheet coverage gate lint: `.venv\Scripts\python.exe -m ruff check .` → All checks passed.
