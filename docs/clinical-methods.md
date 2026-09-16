# Local clinical analyses

RDE is a tool and harness layer for research agents, not a substitute for study
design or statistical review. These seven methods run locally through
`run_advanced_analysis`; no AutoML service, Docker, or patient-data upload is needed.
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
