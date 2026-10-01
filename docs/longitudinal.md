# Source-bound longitudinal analysis

Long-format studies use one observation per subject and time, preserving incomplete follow-up.
`inspect_clinical_study` accepts `clinical_options.family="longitudinal"` and validates identity,
the mean-model design and inclusion before estimation. `run_clinical_study` executes only the
exact locked specification. Both bind the source SHA-256, selected Excel sheet and dataframe.
Use the ordinary intake → schema → concept confirmation → proposal review → plan lock →
readiness → execution → results → report → audit flow through MCP.

## Models and interpretation

- `method="gee"`: Gaussian identity, binomial logit or Poisson log; explicitly select
  independence or exchangeable working correlation. Inference uses subject-cluster robust
  sandwich covariance and asymptotic normal Wald intervals. The subject count is the
  independent sample size; the number of observations is reported separately.
- `method="mixed"`: Gaussian only, REML with subject random intercept and optional correlated
  linear time slope. Use `correlation=null`. Conditional fitted responses include the saved
  subject effects; fixed effects and their covariance remain separate. No GLMM, alternative
  optimizer fallback, Satterthwaite or Kenward–Roger approximation is implied.
- Declare outcome, subject, time, source units, time origin, reference time and collection
  context. Linear time is centered without changing its original unit. Categorical time needs
  2–12 increasing source values and a reference among them. Negative source times are valid.
- Optional baseline group enters the model with its exact reference. Time-by-group effects
  are explicit: group main effects apply at the reference time, time main effects at the
  reference group, and interactions describe differences in time effects or ratios of ratios.
- Covariates need declared categorical references and time-varying roles. Undeclared
  time-varying values and baseline group conflicts fail before dropping missing outcomes.
- Binomial coding explicitly identifies both original labels. Exponentiated coefficients
  are odds ratios, not risk ratios. Poisson optionally uses a positive exposure column as a
  log offset; without it, exponentiated coefficients are mean-count ratios, not rate ratios.
- Holm adjustment covers every non-intercept fixed coefficient in the model; individual
  Wald intervals remain unadjusted. There is no extra omnibus interaction test. Numerical
  p-value underflow is described as below display precision, never as proof of zero probability.

The cohort filter first selects observations. Missing identities/times, duplicate subject-time
pairs and conflicting baseline roles fail before outcome exclusion. Complete observations use
all required model fields but retain other complete visits from partially observed subjects.
The ledger records source rows, exclusions, subjects with no remaining visits, singletons and
the range of retained visits. Computational minima (10 subjects and 3 with repeated visits)
are not power criteria. Small-cluster GEE, model misspecification, endogenous time-varying
covariates and informative loss to follow-up require substantive review; convergence does not
establish validity, ignorability or a causal treatment effect.

## Reports and figures

The saved receipt contains coefficients/covariance, explicit contrast metadata, observed-time
summaries, all original row locators, fitted responses and residuals. Mixed studies also retain
random-effect covariance and anonymized subject modes. Reports and CSVs use those saved values.

Figures contain observation/subject inclusion, unadjusted summaries at actual source times,
all non-intercept coefficients in panels of at most eight, response residuals and Gaussian
residual Q–Q plots. Short source visit sets retain their exact time-axis ticks, even in a
linear-time model. The Q–Q reference joins empirical/normal quartiles as plotting geometry;
it is not a new fit or normality test. Raw summaries are not adjusted trajectories. English
captions retain source units, contrasts, interval definitions and missing-data limitations;
Chinese explanations accompany six-format exports. See [immutable journal editions](publication-figures.md).

## Public-source verification

The companion Workbench acquisition script pins CRAN package bytes and converts original R
objects to CSV without fitting. Specifications are predeclared engineering examples, not
new clinical claims. All actual analyses use the real stdio MCP process and report pipeline.

| Source | Model | Observations / subjects | Numerical receipt SHA-256 |
| --- | --- | --- | --- |
| MASS 7.3-65 epil | Poisson GEE, categorical periods × treatment, lbase/lage | 236 / 59 | `b3caa25ec1aae3d4eb8f18f102c3e8181a0f901da42bf316553faad25058b4c2` |
| nlme 3.1-168 Orthodont | Gaussian GEE, age × sex | 108 / 27 | `2ae8013bad442f9a32db58cfac63619fc5c924a3532349dce0d13ca3092957ba` |
| nlme 3.1-168 Orthodont | Gaussian REML, age × sex, random intercept/slope | 108 / 27 | `0e9bd6cad6408461c3e1d7f9a357b74a6b1bce43ca116ede770a84e064726cd7` |
| geepack 1.3.11 ohio | Binomial GEE, age × baseline smoke | 2148 / 537 | `5d497ebf731e57bf3b67fc2e23c5f270afa29bdaca183ae7cc05af8cb58fad99` |

The epil source includes corrected row 31 `y=23`; old textbook data can differ. Orthodont has
27 children, not 108 independent people. Ohio age is already centered at nine: zero is age 9.
MCP restart/reuse preserved 380 original and edition artifacts across the four runs. The
Workbench browser reproduced every model/coefficient, including an explicitly selected Excel
sheet for Orthodont mixed models and an actual LLM proposal for Ohio.

`scripts/smoke_longitudinal_mcp.py --help` documents the source-hash-pinned full MCP smoke,
including immutable editions, a process restart, saved-result reuse and complete artifact hashes.
Synthetic regressions check binary label reversal, exposure unit changes, recentering of mixed
random effects, complete-observation handling and identity errors without replacing public MCP runs.

Primary references: [statsmodels GEE](https://www.statsmodels.org/stable/gee.html),
[Gaussian MixedLM](https://www.statsmodels.org/stable/mixed_linear.html),
[MASS epil](https://stat.ethz.ch/R-manual/R-devel/library/MASS/html/epil.html),
[nlme Orthodont](https://stat.ethz.ch/R-manual/R-devel/library/nlme/html/Orthodont.html),
[geepack ohio](https://search.r-project.org/CRAN/refmans/geepack/html/ohio.html).
