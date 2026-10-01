# Independent-case regression expansion

Status: contract and design-matrix development. This module is not yet registered
with MCP or offered as an executable Workbench workflow. Existing regression and
longitudinal methods retain their own contracts; no new method is claimed to have
completed public-source or production validation.

`clinical/regression_contract.py` declares one source outcome, independent rows,
an explicit study design (including cross-sectional or unspecified), source units,
and one complete-case population. A supplied subject ID must be unique and present
before missing outcomes are excluded. Invalid counts, exposure durations and
unknown labels cannot be hidden by missing values in other model fields.

Planned distributions are Gaussian, binomial, Poisson, NB2 and proportional-odds
logistic. The contract currently prepares roles, source hashes, case ledgers and
design matrices only; it does not fit any of these estimators. Binary levels are
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
These design checks are not a replacement for numerical estimator, report, MCP,
public-source, browser, publication-figure and restart validation still to come.

References: [Patsy natural cubic splines](https://patsy.readthedocs.io/en/latest/spline-regression.html),
[Harrell restricted-cubic normalization](https://github.com/harrelfe/Hmisc/blob/master/R/rcspline.eval.s),
[statsmodels ordinal model](https://www.statsmodels.org/stable/generated/statsmodels.miscmodels.ordinal_model.OrderedModel.html),
[statsmodels NB2](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.NegativeBinomial.html).
