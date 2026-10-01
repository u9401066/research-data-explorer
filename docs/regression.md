# Independent-case regression expansion

Status: contract and numerical estimator development. This module is not yet registered
with MCP or offered as an executable Workbench workflow. Existing regression and
longitudinal methods retain their own contracts; no new method is claimed to have
completed public-source or production validation.

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

Thirty focused synthetic checks pass: independent HC3 equations and a two-by-two
odds calculation, a separate SciPy NB2 likelihood optimization, exposure-unit and
outcome-order invariants, cutpoint covariance, reference recentering, spline joint
tests and binary/zero-count separation boundaries, plus the source/design checks.
Reports, MCP, public-source, browser, publication-figure and restart validation are
still to come; this is not yet a deployed capability.

References: [Patsy natural cubic splines](https://patsy.readthedocs.io/en/latest/spline-regression.html),
[Harrell restricted-cubic normalization](https://github.com/harrelfe/Hmisc/blob/master/R/rcspline.eval.s),
[statsmodels ordinal model](https://www.statsmodels.org/stable/generated/statsmodels.miscmodels.ordinal_model.OrderedModel.html),
[statsmodels NB2](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.NegativeBinomial.html),
[existence of finite GLM estimates](https://arxiv.org/abs/1903.01633).
