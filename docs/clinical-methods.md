# Local clinical analyses

RDE is a tool and harness layer for research agents, not a substitute for study
design or statistical review. These seven methods run locally through
`run_advanced_analysis`; separate locked survival and measurement bundles are described below.
No AutoML service, Docker, or patient-data upload is needed.
Agents remain free to propose methods outside this catalog and document additional
analyses. The catalog reduces routine coding, not scientific discretion.

## Prospective sample-size planning

The separate [planning workflow](sample-size-planning.md) requires explicit
assumptions, source references and human approval before integer sample-size
calculation. It supports two independent means with a common SD, paired mean
differences and two independent proportions using a normal approximation.
It creates no patient dataset and does not advance or certify the EDA pipeline.
Saved results provide Chinese reports and English publication figures; Nature
and PLOS editions reuse the same numerical receipt. RDE MCP verification is
complete for this development stage; Workbench and LAN acceptance are pending.
Non-significant observed results are interpreted with estimates, intervals and
clinically important differences, not observed-effect post-hoc power.

## Prediction designs and decision analysis

`run_prediction_study` requires `study_design` (observational_cohort,
diagnostic_accuracy or case_control), `sampling` (single_gate, two_gate or unknown),
`sampling_description`, `target_definition` and `prediction_time_definition`.
Case-control requires two-gate sampling; diagnostic/case-control tasks are binary.
Unknown ascertainment, blinding and sampling must remain explicit; text supplied
by a researcher is not independently certified by the pipeline.

All preprocessing and candidate selection remain inside training folds. The chosen
fixed model is scored once on the holdout. In outcome-selected/unknown samples,
AP, PPV/NPV, F1, accuracy, Brier/log loss and calibration are retained as **sample
diagnostics only**, not validated population risk. This differs from the fixed
single-marker diagnostic workflow below, which withholds predictive values under
those designs. ROC/sensitivity/specificity can also suffer spectrum/selection bias.

Optional `decision_curve` requires binary, single-gate sampling and an explicit
`independent_observations=true` declaration. Its other required fields are `action`,
`threshold_basis`, and 1–19 unique increasing `thresholds` in [0.001,0.999]. Subject
duplicates are rejected before outcome exclusions, if a subject key is supplied.
No external prevalence correction, threshold search or extra test-cost adjustment
is implemented; case-control/unknown sampling is rejected for this feature.

At each fixed threshold t, NB = TP/n − FP/n × t/(1−t), compared with treat-all and
treat-none. Model NB and model-minus-all percentile CIs use the **same paired
bootstrap draws** as validation metrics. They are pointwise intervals conditional
on the fixed fitted model, not simultaneous confidence bands or clinical-utility
certification. Enabling DCA cannot change fitting, CV, model selection or splitting.

Chinese reports include design facts, participant flow, candidate comparison,
held-out metrics/CIs, confusion denominators, calibration-bin counts, a training-only
constant baseline and limitations. CSVs retain each of these tables plus model
parameters and row dispositions. Binary studies have six required plots (seven
with DCA); regression has four. Regenerating deliverables uses persisted numbers.
Tests cover hand-computed NB, paired difference intervals, invalid designs,
source duplicates, unchanged fits/splits, complete real MCP export and recovery.
Local suite: 544 passed, five optional skipped on 2026-10-01.

Prediction figures now use a journal-neutral English publication profile with
Chinese explanations. Each figure is exported as native vector PDF (embedded
TrueType) / SVG (outlined text), 300 dpi PNG / RGB LZW TIFF, a separate caption
and plotting-data CSV. A 180 mm canvas, explicit typography, distinguishable
markers/line styles and source/font/renderer hashes are recorded. CV plots show
fold scores and their mean, not an invented confidence interval. Calibration
shows nonempty bin counts without fitting a curve; DCA uses pointwise interval
bars. All formats are included in immutable artifact-integrity gates. Tests read
actual raster dimensions/DPI/mode, SVG geometry, captions and preserved receipts.
Journal-specific requirements and semantic/visual review remain separate; this
profile has not yet been applied to the other clinical figure families.

Method sources: [TRIPOD+AI](https://www.tripod-statement.org/),
[DCA methods](https://www.mskcc.org/departments/epidemiology-biostatistics/biostatistics/decision-curve-analysis),
[dcurves sampling and probability guidance](https://www.danieldsjoberg.com/dcurves/reference/dca.html).

## Locked diagnostic and measurement studies

`inspect_clinical_study` and `run_clinical_study` also accept `family` values
`diagnostic_accuracy`, `bland_altman`, and `cohens_kappa`. They use the same single
locked-plan, source/sheet/frame, immutable numerical receipt and artifact-hash
guards as survival. Each study requires distinct `first`, `second` and optional
`subject` columns, a factual `context`, and `independent_rows=true`. Subject IDs,
when supplied, must be present and unique before complete-case exclusion.

- Diagnostic `first` is the reference, `second` the index test. The nested
  `diagnostic` contract requires original positive/negative codes, reference
  description and independence, sampling (`single_gate`, `two_gate`, `unknown`),
  score threshold/direction or binary test codes, rule provenance/status, and
  explicit reference/test indeterminate labels. Unknown codes and invalid numbers
  stop execution. Missing and indeterminate exclusions have exclusive flow counts;
  all original indeterminate row positions remain separately available.
- Sensitivity/specificity and, only for declared single-gate sampling, PPV/NPV
  and accuracy use Wilson intervals with individual denominators. No hidden
  prevalence correction or continuity correction is applied. Zero denominators
  remain not estimable. Selected/unknown sampling records
  `status=withheld_by_sampling_design` for PPV/NPV/accuracy: sample fractions can
  be calculated, but this workflow withholds them to avoid implying population
  performance. Reports distinguish this policy from undefined ratios.
  A numeric score adds directional ROC/AUC and stratified
  subject percentile bootstrap CI (1,000 iterations, seed 20261001). Fewer than
  two subjects in either class yields no AUC CI; one class yields no ROC/AUC.
  Perfect separation may produce a degenerate interval, not certain clinical
  performance. No cutoff optimization or external-validation claim is made.
- Bland–Altman `agreement` explicitly separates `coverage` from
  `confidence_level`. Difference is first minus second in the shared declared
  `unit`. Bias CI uses t; limits use normal quantiles with approximate t-based
  uncertainty. Optional `acceptable_lower`, `acceptable_upper`, `margin_basis`
  compare point limits and outer CI bounds descriptively, never declare formal
  equivalence. No unit conversion, log transformation or repeated-pair extension
  is silently applied. Saved paired points feed difference, Q–Q and identity plots.
- Kappa requires a complete shared `categories` list. It is unweighted, with
  asymptotic CI, observed agreement and rater cross-tabulation; ordinal weights,
  multiple raters and clustered ratings require another method.

Every report includes factual design context, original coding, participant flow,
uncertainty, interpretation limits, CSVs, native PNGs and a numerical SHA receipt.
The report/readiness layer checks family-specific counts and required figures;
it does not insert survival claims into diagnostic/measurement reports. Rendering
retries use saved numbers, and tampered artifacts are refused. Individual CIs are
pointwise and unadjusted; the pipeline's required Holm plan setting is not a claim
that these intervals have been adjusted. Cox autoresearch rejects non-survival
primary studies; a changed threshold/margin requires a separately reviewed plan.

`tests/test_clinical_measurement.py` exercises manual Wilson calculations,
pairwise-tie AUC, reverse direction, selected sampling, single-class and tiny-class
limits, invalid/indeterminate/missing codes, incomplete and duplicate pairs,
separate agreement coverage/confidence, hand-calculated kappa, all three real MCP
report workflows, tampering, and render recovery without re-estimation. Local
full suite: 529 passed, 5 optional skipped (2026-10-01).

Public-data integration (2026-10-01) also exercised the TypeScript workbench,
actual MCP server and browser reports. WDBC's 569 rows at the illustrative
radius_mean >= 15 rule yielded TP=161, FN=51, TN=344, FP=13 and AUC=0.937517;
sampling remained unknown, with PPV/NPV/accuracy withheld. Bland's original
17-subject PEFR first readings yielded Wright-minus-mini bias=-2.117647 L/min
and 95% normal-quantile limits [-78.095905, 73.860611]. These are demonstrations,
not validated clinical cutoffs or evidence of interchangeable instruments.
A synthetic 24-row Excel rater fixture retained 22 pairs (kappa=0.032).
All ten plots matched the reviewed development PNG hashes, and saved numbers
survived restart without refitting. Human review corrected an LLM draft that
omitted the explicitly supplied subject ID; the original draft was retained.
The workbench's complete HTTP artifact audit covered 3,195 files with no errors.

Primary method references: [STARD](https://www.equator-network.org/reporting-guidelines/stard/),
[Wilson intervals](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html),
[Bland and Altman original paper](https://www-users.york.ac.uk/~mb55/meas/ba.htm),
[statsmodels kappa](https://www.statsmodels.org/stable/generated/statsmodels.stats.inter_rater.cohens_kappa.html).

## General advanced-analysis parameters and estimands

All methods accept `confidence_level` (default 0.95). Binary outcomes must be
explicitly coded 0/1; categorical reference choices must not be guessed.

| analysis_type | Required tool arguments | Output and uncertainty |
| --- | --- | --- |
| `risk_estimates` | target_variable = binary event; group_variable = exposure (1 versus 0) | Cohort risk ratio and odds ratio with log-Wald CIs; absolute risk difference with Newcombe-Wilson CI; Fisher exact test |
| `diagnostic_accuracy` | target_variable = binary reference standard; score_variable = binary test or score | Sensitivity, specificity, PPV, NPV, accuracy with Wilson CIs and their individual denominators |
| `mcnemar` | target_variable = binary before; score_variable = binary after | Exact discordant-pair test, matched odds ratio with exact conditional CI, paired risk difference (point estimate only) |
| `bland_altman` | target_variable = first measurement; score_variable = second | First-minus-second bias with t CI, normal-theory limits of agreement with approximate CIs |
| `cohens_kappa` | target_variable = first rater; score_variable = second rater | Unweighted Cohen kappa with asymptotic CI and observed agreement |
| `gee` | target_variable; subject_variable; covariates | Exchangeable GEE, robust sandwich Wald inference; Gaussian, binomial, or Poisson family |
| `mixed_effects` | target_variable; subject_variable; covariates | Gaussian random-intercept model, REML fit, fixed-effect Wald inference |

`clinical_options` accepts only `threshold`, `positive_direction` (greater_equal
or less_equal), and `family` (gaussian, binomial, poisson). Diagnostic thresholds
must be prespecified or validated independently; optimizing a cutoff on this
same sample is not supported by this endpoint. GEE defaults to Gaussian. Mixed
effects supports Gaussian responses only.

```json
{
  "dataset_id": "<loaded-dataset-id>",
  "analysis_type": "gee",
  "target_variable": "pain_score",
  "subject_variable": "case_id",
  "covariates": ["visit", "treatment"],
  "clinical_options": {"family": "gaussian"},
  "confidence_level": 0.95
}
```

Covariates are explicitly selected; numeric coding is interpreted numerically,
and categorical columns use treatment contrasts. Review those encodings before
execution. No formula strings or arbitrary code are evaluated.

## Case identity and reproducibility

For long-form two-occasion numeric or ordinal outcomes, use
`compare_groups(is_paired=true, subject_variable="case_id", group_variable="visit",
outcome_variables=["score"])`. It joins by the supplied subject key, rejects
duplicate subject/occasion records, excludes incomplete pairs, and persists the
two source-row positions for each retained pair. Calling the paired flag without
a key is an error, not permission to pair by incidental row order. Wide-form
columns continue to use `run_repeated_measures`.

Each method creates a complete-case mask over exactly its required columns,
retaining row alignment. Paired columns must occupy the same subject's row;
long-form repeated data require `subject_variable` in GEE/mixed models instead.
The durable JSON records input/analyzed/excluded counts, missing/invalid numeric
counts, zero-based included row positions, confidence level, CI method, and
warnings. Pairing correctness depends on the supplied dataset alignment; a row
position is provenance within that dataset, not a stable cross-dataset identity.

GEE/mixed models additionally report the number of subjects. A minimum of three
clusters is an execution check, **not** evidence that asymptotic inference is
reliable with so few clusters. Failed or nonconvergent estimates are retained as
failure artifacts and do not count as successful plan coverage. Markdown results
are included by the report assembler. Missing p-values never imply a null finding.

## Interpretation limits

- No hidden 0.5 correction for empty risk-table cells. Unavailable log CIs are
  explicitly not estimable; a zero denominator is not perfect performance.
- Cohort risks are not identifiable from arbitrary case-control samples. None of
  these tools establishes causality, diagnostic transportability, or equivalence.
- Repeated-measure covariance, small-cluster corrections, residual distributions,
  confounding, missing-not-at-random sensitivity, and multiplicity require a
  study-specific analysis plan. Current CIs are pointwise and unadjusted.
- Agreement limits require approximately normal, homoscedastic differences and
  independent pairs; clinically acceptable margins must be supplied by the team.
- Kappa is unweighted and prevalence-sensitive. Diagnostic accuracy assumes a
  credible reference standard; predictive values depend on prevalence.
- Publication readiness requires clinical interpretation, design-appropriate
  reporting, sensitivity analyses, and investigator review—not just tool success.

## Implementation references

- [statsmodels Table2x2](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.Table2x2.html)
- [Difference-of-proportions intervals](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html)
- [Binomial proportion intervals](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html)
- [Exact McNemar test](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.mcnemar.html)
- [Cohen kappa](https://www.statsmodels.org/stable/generated/statsmodels.stats.inter_rater.cohens_kappa.html)
- [GEE](https://www.statsmodels.org/stable/gee.html)
- [Mixed linear models](https://www.statsmodels.org/stable/mixed_linear.html)

Regression tests use synthetic data and independently specified numerical
expectations, including asymmetric missingness, empty cells, nonconvergence,
denominator preservation, report integration, and failed-execution accounting.

## Prespecified survival and competing-event studies

`inspect_clinical_study(dataset_id, clinical_options)` checks the full source before
plan review: event labels, cohort eligibility, participant identity, missingness,
common analyzed counts and each stratum. It does not fit models or calculate p-values.
`run_clinical_study` executes one exact locked `family: survival` bundle; the options
must match the sole plan entry's `execution_arguments.clinical_options`.

Required options: `time`, `event`, `event_value`, `censor_value`, `time_origin`,
`time_unit`, `independent_rows: true`. Optional choices are `group`, `subject`,
`covariates`, `categorical_covariates`, exact `references`, `competing_values`,
`risk_times`, `confidence_level`, and `cohort_filter: {column, values}`. No category
meaning is inferred from order. All curves, models and risk tables share complete
cases across the selected columns. Unknown codes and malformed numeric values
stop execution; they are not silently discarded or treated as censoring.

| Output | Estimator and interpretation |
| --- | --- |
| Survival without competing events | Kaplan–Meier, Greenwood log–log pointwise CI, median only if reached, overall log-rank comparison |
| Competing events | Aalen–Johansen cumulative incidence for every declared cause; original ties retained, no random jitter; pointwise normal CI bounded to [0, 1] |
| Adjusted association | Unpenalized Cox model, Efron ties, Breslow baseline; exact categorical reference, HR and Wald CI |
| Competing-event association | Cause-specific Cox HR; competing causes leave the risk set at their observed times; not a subdistribution HR |
| Assumption checks | Scaled Schoenfeld residuals; rank and KM time transforms, Holm correction across all term × transform checks |
| Follow-up counts | Participants at risk immediately **before** each requested time; target, competing and censored counts retain distinct meanings |

The competing-risk variance uses statsmodels' estimate. At an exhausted terminal
risk set its expanded formula can be singular; only non-finite standard errors are
recomputed using the algebraically equivalent difference form with its zero-limit
term. The receipt records those adjustments. A hand-computed multinomial boundary
test and a censored-package comparison cover this case. A group with no events has
no estimated uncertainty, not a fabricated zero-risk confidence interval.

Outputs include a Chinese methods/results/limitations report, participant ledger,
curve and coefficient CSVs, risk table, forest plot and one residual figure per
encoded parameter. A numerical receipt is written before rendering; renderer retry
reuses that receipt. Successful records are reused only after source, specification,
numerical and file hash checks. Changed plans/sources or corrupted evidence require
an explicit new study, not overwriting the old result.

No left truncation, recurrent events, time-dependent covariates, RMST, Gray test or
Fine–Gray regression is implemented in this bundle. Proportional-hazards tests do
not certify assumptions. Complete cases and a nominal CI do not establish clinical
representativeness, causality or adequate power. Readiness checks cover recorded
evidence and cannot replace study-specific scientific review.

Implementation sources: [lifelines CoxPHFitter](https://lifelines.readthedocs.io/en/latest/fitters/regression/CoxPHFitter.html),
[lifelines proportional-hazards diagnostics](https://lifelines.readthedocs.io/en/latest/Statistics.html#lifelines.statistics.proportional_hazard_test),
[statsmodels cumulative incidence](https://www.statsmodels.org/stable/generated/statsmodels.duration.survfunc.CumIncidenceRight.html).
Tests: `tests/test_clinical_survival.py` includes manually specified KM intervals,
independent statsmodels Cox/log-rank comparisons, case flow, strict coding, failed
fits, actual MCP/report gates, retry without refitting and artifact tampering.

### Bounded survival adjustment branches

The autoresearch queue also executes `tool: run_clinical_study` with
`analysis_type: survival_sensitivity`. Its exact contract contains `covariates`,
`focus_variable`, `required_covariates`, `primary_receipt_sha256`,
`primary_record_sha256` (original record bytes), and `case_set_sha256` (canonical
JSON digest of primary one-based complete-case source positions). Extra keys fail.

The focus must be required, all required factors must remain, and covariates must
be a nonempty proper subset in primary order. The sole locked primary survival
specification supplies all other roles and encodings. The runner verifies the
primary record, source file/sheet, loaded frame, case ledger and every primary
report/plot hash before fitting. It never runs a binary logistic model on a
time-to-event endpoint.

Cases are prepared with the **full primary specification**, then selected model
columns are remapped on those same rows. Dropping an incomplete predictor cannot
add participants. Receipts include both model and population specifications,
the original full-role data hash and an explicit primary binding. Cause-specific
Cox preserves competing-event coding, category references and risk sets.

Each branch has its own numerical receipt, Chinese comparison/full report, CSVs
and figures. Numbers are persisted before rendering; a rendering failure remains
failed with its numerical evidence retained. The returned artifact SHA256 and
file manifest support checked recovery. The primary report/visualization manifest
is not rewritten. Branch rendering does not currently auto-retry without refitting.

This is exploratory adjustment sensitivity, with pointwise intervals and no
cross-model multiplicity correction or automatic primary promotion. HR changes
are not a formal between-model difference test. Holm applies only to PH tests
within a model. Independent PHReg comparisons, asymmetric missingness, competing
events, real MCP queue execution, artifact tampering and retained renderer failure
evidence are covered in `tests/test_survival_autoresearch.py`.

Workbench validation on 2026-10-01 exercised the real MCP queue and official
Harness/LLM on public UCI heart-failure and PBC data, two branches per source.
Heart failure kept 299 participants/96 deaths; PBC kept the prespecified 312
participants/125 deaths/19 transplants/168 right-censored observations. All four
branch case ledgers, curves and risk sets matched their primary study exactly.
The Workbench deployment reproduced all coefficients/uncertainty/PH checks and
the 24 reviewed branch PNGs byte-for-byte. Complete branch reports are readable
in the web report selector and retain their own figure ownership after restart.
The Workbench QA ledger records source attribution, run IDs and numerical values;
these are engineering validation cases, not confirmatory clinical findings.

Local regression: 512 passed/5 skipped including the configured CJK fixture.
[CI for the executor commit](https://github.com/u9401066/research-data-explorer/actions/runs/36824397029)
passed Python quality (511 passed/1 font-fixture skipped/5 vendor deselected),
extension quality and all four VSIX platform smoke jobs. The optional vendor job
remained skipped. Model wording required human corrections during development;
stored numerical evidence and investigator review remain separate.

### English publication graphics and source labels

New survival graphics use the shared [publication exporter](publication-figures.md), with
English captions, Chinese explanations, PDF/SVG/PNG/TIFF, plot CSVs and font hashes.
Each group and coefficient panel has its own report identity. Raw Chinese group/column labels
remain explicit in caption mappings; common time-unit names receive display-only English
translations without changing numerical values. Other unit names are preserved as U1 mappings.
The exporter never infers a covariate's unit from the follow-up unit.

`RDE_PUBLICATION_FONT_DIR` supplies exact local fonts for journal presets. General plotting
can still use `RDE_PLOT_FONT` for CJK labels; legacy rendered files and their original font
receipts remain unchanged. Font registration and missing-file checks remain in
`tests/test_plot_fonts.py`, together with an English-rendering check that preserves Chinese
source identity without silent substitution.
