# Local clinical analyses

RDE is a tool and harness layer for research agents, not a substitute for study
design or statistical review. These seven methods run locally through
`run_advanced_analysis`; a separate prespecified survival bundle is described below.
No AutoML service, Docker, or patient-data upload is needed.
Agents remain free to propose methods outside this catalog and document additional
analyses. The catalog reduces routine coding, not scientific discretion.

## Parameters and estimands

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

### Chinese plot font configuration

Set `RDE_PLOT_FONT` to an absolute path to a local CJK font file when column
names, group labels or time units contain Chinese. The renderer registers that
file directly, including on servers with an older matplotlib font cache. It does
not download fonts at analysis time. An invalid configured path fails explicitly;
without this setting, available installed CJK fonts are preferred.

Every survival figure receipt includes the configured font filename and SHA256
plus the selected sans-serif fallback list. Re-rendering requires the original
numerical receipt; it does not refit models or alter old artifact snapshots.
`tests/test_plot_fonts.py` covers missing files, registration outside the font
cache, and Chinese survival labels when `RDE_CJK_TEST_FONT` points to a local test
font. The optional label test is skipped when that fixture is unavailable.
