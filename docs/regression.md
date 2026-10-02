# Independent-case regression expansion

`inspect_clinical_study` and `run_clinical_study` accept
`clinical_options.family="regression"`. The full intake, schema, concept review,
proposal, plan lock, readiness, execution, report and audit sequence runs through
MCP. Source SHA-256, selected worksheet, dataframe and exact specification are
checked before execution. As of 2026-10-02, RDE `ed35602` and Workbench runtime
`07cb993` are deployed; all five public CSV/Excel models have completed production
browser validation, publication export and restart retrieval. Versions remain
0.5.0 and 0.1.0.

`clinical/regression_contract.py` declares one source outcome, independent rows,
an explicit study design (including cross-sectional or unspecified), source units,
and one complete-case population. A supplied subject ID must be unique and present
before missing outcomes are excluded. Invalid counts, exposure durations and
unknown labels cannot be hidden by missing values in other model fields.

Distributions are Gaussian, binomial, Poisson, NB2 and proportional-odds logistic.
Preflight prepares roles, source hashes, case ledgers and design matrices without
fitting. The separate numerical engine estimates a frozen specification. Binary levels are
explicitly negative then positive; ordinal levels are lowest to highest. Ordered
category meaning is never inferred alphabetically. Case-control sampling is limited
to binary logistic associations in this workflow.

Predictors have exact typed definitions:

- Continuous: `column`, `kind="continuous"`, `label`, original `unit`, numeric
  `reference`, positive comparison `increment`, and `knots` (empty for linear or
  3–5 ordered source-scale restricted-cubic knots).
- Categorical: `column`, `kind="categorical"`, `label`, complete `levels`, and a
  `reference` from those labels.
- Interactions: explicit pairs of declared predictor columns. Their full basis
  products retain all required main effects. Reversed duplicates are rejected.

Continuous bases are centered at the declared reference and divided by the
comparison increment. References and knots must lie in the retained source range.
Spline bases contain the linear component and K−2 nonlinear components normalized
by the squared outer-knot span; tails are linear. User column names are never
evaluated as formulas. Ordinal matrices exclude an intercept and any implicit
constant span. Complete-case rank and parameter limits include ordinal thresholds
or NB2 dispersion parameters, without presenting computational minima as power
calculations.

Synthetic edge checks cover incomplete-case row identity, invalid values before
exclusion, reversed outcome order, lost reference categories, duplicate variables,
implicit ordinal intercepts and explicit contrast units. The natural-cubic function
space is independently compared with Patsy's `cr` basis, including linear tails.
The numerical engine uses OLS with HC3 covariance and a residual-df t approximation,
binary/Poisson GLM with independent-case HC0 sandwich covariance, joint NB2 maximum
likelihood with estimated dispersion, and ordinal logistic likelihood with ordered
cutpoints. The latter two retain the full model-based covariance including nuisance
parameters. Cutpoint intervals use the transformed-threshold delta method; NB2
dispersion intervals use a log-scale delta method. Failed convergence, singular
covariance and nonfinite inference stop the study. Binary and count separation are
checked by bounded linear programs; no observations are discarded to fix separation.

Nonintercept coefficient p-values and prespecified joint main/interaction/nonlinear
tests form two explicitly separate Holm families. Confidence intervals remain
pointwise and unadjusted. All spline basis components, including the linear part,
are labeled as basis coefficients rather than per-unit clinical effects. Conditional
curves compare each observed predictor value with its declared reference, keeping
the remaining roles at their references; these are not marginal causal estimates.
Ordinal responses retain original labels and category probabilities, without numeric
residuals that would imply equal category spacing. No formal proportional-odds
assumption test is provided. Case-control probabilities refer only to the sampled
case-control mix, not population disease risks.

Focused synthetic checks cover independent HC3 equations and a two-by-two
odds calculation, a separate SciPy NB2 likelihood optimization, exposure-unit and
outcome-order invariants, cutpoint covariance, reference recentering, spline joint
tests and binary/zero-count separation boundaries, plus the source/design checks.
Workflow checks exercise all five families, reject unapproved or changed sources,
preserve saved receipts on render failure and check physical separation of wrapped
predictor labels at a journal's single-column width.

## Reports and publication figures

The immutable `rde-regression-study-v1` numerical receipt contains the full
specification, case ledger, design terms, coefficient covariance, nuisance parameters,
joint tests, per-case fitted results, conditional contrasts and library versions.
Reports explain the study design, original units, exclusions, two Holm families and
model-specific limitations in Traditional Chinese. Renderers use these saved values;
changing a journal preset does not refit or select a new model.

English figures include case inclusion, every nonintercept coefficient (separate
spline-basis panels), conditional curves and saved residuals. Gaussian models add
a residual Q–Q plot; ordinal models show original and mean fitted category
probabilities without treating ordered categories as equally spaced numbers.
Captions state the reference values, scale, covariance, pointwise interval meaning
and limits of interpretation. Each figure exports PNG, vector PDF/SVG, TIFF,
caption Markdown and exact data CSV. Journal editions retain the original figures and
source receipt; see [publication formats and presets](publication-figures.md).

## Public-source verification

The Workbench acquisition catalog pins the original CRAN packages and R objects.
CSV conversion preserves original rows, labels and units; every actual model is
run by the stdio MCP server. `scripts/fixtures/public-regression-studies.json`
contains the five explicit engineering specifications and source hashes.

| Source | Model | Retained cases | Numerical receipt SHA-256 |
| --- | --- | --- | --- |
| AER 1.2-17 DoctorVisits | Poisson, five declared factors | 5190 | `7e2188550d99a682f547b6db159cef4b71f72a1d102a5bc3ef4cd081d4804935` |
| AER 1.2-17 DoctorVisits | NB2 with estimated dispersion, same factors | 5190 | `7ba2fbc07a8a81e5bdb7650473d91a9c69a0c7173d84c0881a77227301000b26` |
| vcd 1.4-14 Arthritis | Ordinal logistic, treatment/age/sex | 84 | `5cf66e64b51773df3b494fc184870ef8c9064bdb89f21d45f16d89a1323cc09f` |
| MASS 7.3-65 birthwt | Gaussian HC3, weight spline × smoking, age/race | 189 | `8b59b9705e7e00272085fab5293169ada27b3582ab2539f158253a853b0f4652` |
| MASS 7.3-65 birthwt | Binary logistic, weight spline, age/smoking/hypertension | 189 | `175bcdcbffd78cb15cab38947af525a95d9a8f48afeefdbe2da9627c8babbe8f` |

DoctorVisits age is years divided by 100: a 0.1 increment means ten years. No
survey weights or person-time offset are invented. Arthritis retains the ordered
labels `None < Some < Marked`, with original counts 42/14/28; literal `None` is not
missing. Its dictionary does not establish randomization or an explicit age unit,
so the specimen says unspecified design and source age units. Birthwt retains
pounds and grams; the binary model excludes `bwt`, which defines its outcome.
Spline knots are specified for engineering validation, without claiming clinical
optimality or selecting them from the observed results.

Together, the five workflows produced 29 distinct figures, each in five presets. Final layout
review examined all 145 PNGs, 25 rendered PDF pages and 29 English captions.
Embedded PDF fonts and identical figure data were checked for every export.
MCP restart reused all 25 new layout editions without refitting; 1859 original
and new immutable files were verified unchanged. Earlier overlapping single-column
labels remain in their historical editions; new editions increase physical row
spacing. Local evidence from `/tmp/rde-regression-layout-review/` and
`/tmp/rde-regression-layout-visual-review/`, including earlier failures, is retained
in the verified milestone archive described below.

Use `scripts/smoke_clinical_mcp.py --help` for the source-pinned workflow,
optional journal editions, process restart and artifact verification. These runs
validate software behavior and interpretation boundaries, not new clinical findings.
The local non-vendor release suite passed 664 checks with the configured CJK and
authorized local Arial fixtures; five optional vendor checks were deselected.

Production verification matched all 29 original figure PNGs/data tables to the
reviewed MCP output, then exported five new journal editions with 29 figures and
174 format downloads. All 29 PDFs embed their fonts; five actual PDF pages and
desktop/mobile editors and reports were inspected. Journal editions were retrieved
after a service restart without changing their source analyses. The full Workbench
audit checked 45 projects and 6390 artifacts, with zero download/hash/index/ownership
errors. All 39 pre-existing projects remained unchanged.

Actual LLM tests retained failures and targeted corrections, including omitted case
IDs, repeated report pages, unavailable approved alpha in scoped discussion, Holm
family interpretation and misuse of the necessarily positive NB2 log-scale interval.
The Workbench fixes do not change numerical results or guarantee every model answer.
Complete QA, including the stopped development workspace, is archived at
`$XDG_DATA_HOME/research-workbench-qa/regression-20261002T004443Z/qa-evidence.tar.gz`
(the default data home is `~/.local/share`):
7,893 files, 479,887,430 bytes, SHA-256
`0977aae5246985f8613967c8b960e0c04cc72ed61bbe088179ebb2651d88f689`.
Every archive payload was read and matched to its recorded hash.
[RDE CI](https://github.com/u9401066/research-data-explorer/actions/runs/36885761255)
passed 623 checks with 41 optional font-fixture skips and five vendor deselections,
plus pre-commit, extension checks and four-platform smoke.

References: [Patsy natural cubic splines](https://patsy.readthedocs.io/en/latest/spline-regression.html),
[Harrell restricted-cubic normalization](https://github.com/harrelfe/Hmisc/blob/master/R/rcspline.eval.s),
[statsmodels ordinal model](https://www.statsmodels.org/stable/generated/statsmodels.miscmodels.ordinal_model.OrderedModel.html),
[statsmodels NB2](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.NegativeBinomial.html),
[existence of finite GLM estimates](https://arxiv.org/abs/1903.01633).
