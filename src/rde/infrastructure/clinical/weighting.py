"""Prespecified binary propensity weighting with joint estimating equations.

This estimates two Hájek means, not an outcome regression. The independent-case
sandwich includes estimated propensity parameters and the weight derivatives.
No clipping, trimming, variable selection or fallback estimator is applied.
"""

from __future__ import annotations

import importlib.metadata
import warnings

import numpy as np
from scipy.special import expit
from scipy.stats import norm

from .regression import _reject_binary_separation
from .regression_contract import regression_design
from .survival import digest, level
from .weighting_contract import WeightingSpec, prepare_weighting


def _weight_functions(e, estimand):
    """Return group weights and their derivatives with respect to logit(e)."""
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        if estimand == "ATE":
            w1, w0 = 1 / e, 1 / (1 - e)
            d1, d0 = -w1 * (1 - e), w0 * e
        elif estimand == "ATT":
            w1, w0 = np.ones_like(e), e / (1 - e)
            d1, d0 = np.zeros_like(e), w0
        elif estimand == "ATO":
            w1, w0 = 1 - e, e
            d1, d0 = -e * (1 - e), e * (1 - e)
        else:
            raise ValueError("Unknown prespecified weighting estimand.")
    if any(not np.isfinite(v).all() for v in [w1, w0, d1, d0]) or any(
        (v <= 0).any() for v in [w1, w0]
    ):
        raise ValueError("Nonfinite or nonpositive weights; no silent clipping is permitted.")
    return w1, w0, d1, d0


def _joint_equations(x, a, y, e, means, estimand):
    w1, w0, d1, d0 = _weight_functions(e, estimand)
    n, p = x.shape
    treated, control = a * w1, (1 - a) * w0
    residual1, residual0 = y - means[0], y - means[1]
    scores = np.column_stack([x * (a - e)[:, None], treated * residual1, control * residual0])
    bread = np.zeros((p + 2, p + 2))
    bread[:p, :p] = x.T @ ((e * (1 - e))[:, None] * x) / n
    bread[p, :p] = -np.mean((a * d1 * residual1)[:, None] * x, axis=0)
    bread[p + 1, :p] = -np.mean(((1 - a) * d0 * residual0)[:, None] * x, axis=0)
    bread[p, p], bread[p + 1, p + 1] = treated.mean(), control.mean()
    meat = scores.T @ scores / n
    if (
        not np.isfinite(bread).all()
        or not np.isfinite(meat).all()
        or np.linalg.matrix_rank(bread) != p + 2
        or np.min(np.linalg.eigvalsh(bread[:p, :p])) <= 0
    ):
        raise ValueError("The joint estimating equations have invalid or singular information.")
    inverse = np.linalg.solve(bread, np.eye(p + 2))
    covariance = inverse @ meat @ inverse.T / n
    covariance = (covariance + covariance.T) / 2
    if not np.isfinite(covariance).all():
        raise ValueError("The joint sandwich covariance is nonfinite.")
    eigenvalues = np.linalg.eigvalsh(covariance)
    if eigenvalues[0] < -1e-10 * max(np.max(np.abs(eigenvalues)), np.finfo(float).tiny):
        raise ValueError("The joint sandwich covariance is not positive semidefinite.")
    # A constant response in one group can yield a singular covariance, while
    # the difference still has valid positive variance. Do not require full rank.
    return covariance, bread, meat, scores.mean(axis=0)


def _balance(values, a, weights, estimand, *, indicator=False):
    values = np.asarray(values, dtype=float)
    group_values = [values[a == code] for code in [0, 1]]
    means = [float(v.mean()) for v in group_values]
    variances = [
        means[code] * (1 - means[code]) if indicator else float(v.var(ddof=1))
        for code, v in enumerate(group_values)
    ]
    denominator = float(
        np.sqrt(variances[1] if estimand == "ATT" else (variances[0] + variances[1]) / 2)
    )
    weighted = [
        float(np.average(v, weights=weights[a == code])) for code, v in enumerate(group_values)
    ]
    difference, weighted_difference = means[1] - means[0], weighted[1] - weighted[0]
    return {
        "control_mean": means[0],
        "treated_mean": means[1],
        "control_weighted_mean": weighted[0],
        "treated_weighted_mean": weighted[1],
        "difference": difference,
        "weighted_difference": weighted_difference,
        "standardization_sd": denominator,
        "smd": difference / denominator if denominator > 0 else None,
        "weighted_smd": weighted_difference / denominator if denominator > 0 else None,
        "undefined_reason": "Zero unweighted standardization variance"
        if denominator == 0
        else None,
        "variance_convention": "p*(1-p) for an indicator"
        if indicator
        else "sample variance, ddof=1",
    }


def _diagnostics(frame, design, terms, a, e, weights, spec):
    balance, basis_balance, summaries, histograms = [], [], [], []
    for i, covariate in enumerate(spec.covariates):
        values = frame[f"x{i}"]
        categories = covariate["levels"] if covariate["kind"] == "categorical" else [None]
        for category in categories:
            balance.append(
                {
                    "covariate": i,
                    "column": covariate["column"],
                    "level": category,
                    **_balance(
                        values if category is None else (values == category).astype(float),
                        a,
                        weights,
                        spec.estimand,
                        indicator=category is not None,
                    ),
                }
            )
    lookup = {term["term"]: term for term in terms}
    for term in terms[1:]:
        indicator = term["role"] == "categorical" or (
            term["role"] == "interaction"
            and all(lookup[key]["role"] == "categorical" for key in term["components"])
        )
        basis_balance.append(
            {
                **term,
                **_balance(design[term["term"]], a, weights, spec.estimand, indicator=indicator),
            }
        )
    edges = np.linspace(0, 1, 21)
    for code, label in enumerate(spec.treatment_levels):
        selected = a == code
        w, scores = weights[selected], e[selected]
        quantiles = np.quantile(w, [0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1])
        weight_sum = float(w.sum())
        summaries.append(
            {
                "treatment_code": code,
                "label": label,
                "n": int(selected.sum()),
                "weight_sum": weight_sum,
                "kish_ess": float(weight_sum**2 / (w @ w)),
                "weight_quantiles": dict(
                    zip(
                        ["min", "p01", "p05", "p25", "median", "p75", "p95", "p99", "max"],
                        map(float, quantiles),
                        strict=True,
                    )
                ),
                "propensity_min": float(scores.min()),
                "propensity_max": float(scores.max()),
            }
        )
        counts, _ = np.histogram(scores, edges)
        weighted_counts, _ = np.histogram(scores, edges, weights=w)
        histograms += [
            {
                "treatment_code": code,
                "left": float(edges[j]),
                "right": float(edges[j + 1]),
                "n": int(count),
                "proportion": float(count / len(w)),
                "weighted_proportion": float(weighted_counts[j] / weight_sum),
            }
            for j, count in enumerate(counts)
        ]
    lower = max(row["propensity_min"] for row in summaries)
    upper = min(row["propensity_max"] for row in summaries)
    return {
        "covariate_balance": balance,
        "basis_balance": basis_balance,
        "groups": summaries,
        "propensity_histogram": histograms,
        "common_score_range": {"lower": lower, "upper": upper, "overlaps": lower <= upper},
        "standardization": "Fixed unweighted treated SD"
        if spec.estimand == "ATT"
        else "Fixed square root of the mean of the two unweighted variances",
        "histogram_policy": "20 fixed bins across [0,1]; left-closed, right-open except the last bin; within-group proportions, no smoothing",
        "scope": "Descriptive observed-covariate diagnostics; no balance hypothesis tests, no automatic changes to the target or model, no proof of positivity or absence of unmeasured confounding.",
    }


def run_weighting(df, spec: WeightingSpec):
    import statsmodels.api as sm

    frame, ledger, source_hash = prepare_weighting(df, spec)
    design, terms, groups = regression_design(frame, spec.propensity_spec())
    x = design.to_numpy(dtype=float)
    n, p = x.shape
    if p + 2 >= n:
        raise ValueError("The joint parameter count must be below case count; not a power rule.")
    a, y = frame.treatment.to_numpy(dtype=float), frame.response.to_numpy(dtype=float)
    _reject_binary_separation(x, a)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fit = sm.GLM(a, x, family=sm.families.Binomial()).fit(maxiter=200, tol=1e-12)
    notes = [str(item.message) for item in caught]
    beta = np.asarray(fit.params, dtype=float)
    e = expit(x @ beta)
    if (
        not fit.converged
        or not np.isfinite(beta).all()
        or not np.isfinite(e).all()
        or (e <= 0).any()
        or (e >= 1).any()
        or any("separation" in note.lower() for note in notes)
        or np.max(np.abs(np.mean(x * (a - e)[:, None], axis=0)) / np.max(np.abs(x), axis=0)) > 1e-8
    ):
        raise ValueError(
            "Propensity estimation did not yield a finite converged nonseparated fit with scores strictly inside (0,1)."
        )
    w1, w0, _, _ = _weight_functions(e, spec.estimand)
    weights = a * w1 + (1 - a) * w0
    means = [float(np.average(y[a == code], weights=weights[a == code])) for code in [1, 0]]
    covariance, bread, meat, score_means = _joint_equations(x, a, y, e, means, spec.estimand)
    contrast = np.r_[np.zeros(p), 1, -1]
    variance = float(contrast @ covariance @ contrast)
    if not np.isfinite(variance) or variance <= 0:
        raise ValueError(
            "The primary contrast has no finite positive sandwich variance; boundary inference is unsupported."
        )
    estimate, se = means[0] - means[1], float(np.sqrt(variance))
    critical = float(norm.ppf((1 + spec.confidence_level) / 2))
    selected = {int(index + 1): row for row, index in enumerate(frame.index)}
    filtered = set(ledger["filter_excluded_data_rows"])
    weight_sums = {code: float(weights[a == code].sum()) for code in [0, 1]}
    points = []
    for index in range(len(df)):
        row = selected.get(index + 1)
        included = row is not None
        code = int(a[row]) if included else None
        points.append(
            {
                "data_row": index + 1,
                "source_identity": level(df.iloc[index][spec.subject]) if spec.subject else None,
                "status": "included"
                if included
                else "outside_cohort"
                if index + 1 in filtered
                else "missing_required",
                "treatment_code": code,
                "response": float(y[row]) if included else None,
                "propensity": float(e[row]) if included else None,
                "weight": float(weights[row]) if included else None,
                "normalized_weight": float(weights[row] / weight_sums[code]) if included else None,
            }
        )
    result = {
        "schema": "rde-weighting-study-v1",
        "status": "completed",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "design_sha256": digest({"columns": design.columns.tolist(), "values": x.tolist()}),
        "n": n,
        "case_ledger": ledger,
        "model": {
            "propensity": "Unpenalized binary logistic maximum likelihood; all declared basis terms and interactions retained",
            "outcome": "Two separately normalized Hájek weighted means; no outcome regression",
            "covariance": "Independent-case joint estimating-equation sandwich including propensity estimation and weight derivatives; no finite-sample correction",
            "inference": "Single prespecified treated-minus-control contrast; asymptotic normal two-sided Wald inference; no interval clipping or multiplicity adjustment",
            "weight_formula": {
                "ATE": ["1/e", "1/(1-e)"],
                "ATT": ["1", "e/(1-e)"],
                "ATO": ["1-e", "e"],
            }[spec.estimand],
            "weight_formula_order": ["treated", "control"],
            "converged": True,
            "iterations": int(fit.fit_history["iteration"]),
        },
        "propensity_terms": terms,
        "term_groups": groups,
        "joint_estimation": {
            "parameter_order": [*design.columns, "mean_treated", "mean_control"],
            "parameters": [*map(float, beta), *means],
            "bread": bread.tolist(),
            "meat": meat.tolist(),
            "covariance": covariance.tolist(),
            "mean_equations": score_means.tolist(),
            "equations": "psi_beta=X(A-e); psi_1=A*w1*(Y-mu1); psi_0=(1-A)*w0*(Y-mu0); J=-mean(dpsi/dtheta); S=mean(psi*psi'); Cov=inv(J)*S*inv(J)'/n",
        },
        "effect": {
            "estimand": spec.estimand,
            "scale": "probability difference"
            if spec.outcome_type == "binary"
            else "mean difference",
            "unit": "proportion" if spec.outcome_type == "binary" else spec.outcome_unit,
            "treated_mean": means[0],
            "control_mean": means[1],
            "estimate": estimate,
            "standard_error": se,
            "lower": estimate - critical * se,
            "upper": estimate + critical * se,
            "statistic": estimate / se,
            "p_value": float(2 * norm.sf(abs(estimate / se))),
            "confidence_level": spec.confidence_level,
            "ci_adjusted": False,
        },
        "diagnostics": _diagnostics(frame, design, terms, a, e, weights, spec),
        "points": points,
        "warnings": notes,
        "limitations": [
            "Declared observational cohort, independent cases and one common complete-case population. No clustered, survey or time-varying treatment inference; no imputation or automatic model selection.",
            "Causal interpretation requires consistency, appropriate treatment and covariate timing, conditional exchangeability, positivity and suitable sampling. These assumptions are not established by balance, overlap, convergence or a significant contrast.",
            "The propensity model and estimand were prespecified. ATE, ATT and ATO concern different target populations; selecting a target using outcome significance is unsupported.",
            "Complete-case selection can introduce bias; this analysis does not establish an ignorable missingness mechanism or complete outcome ascertainment.",
            "Estimated propensity uncertainty is included in the joint sandwich. This is an asymptotic independent-case approximation, not a small-sample guarantee, bootstrap or power analysis.",
            "The binary contrast is an absolute probability difference, not an odds or risk ratio. Unclipped normal Wald limits may exceed [-1,1].",
            "Kish effective sample sizes are descriptive weight-concentration summaries, not counts of additional patients or proof of sufficient precision.",
            "Raw and model-basis balance uses a fixed unweighted standardization denominator before and after weighting. Overlap weighting's fitted basis balance does not establish balance of unmeasured covariates.",
        ],
        "versions": {
            key: importlib.metadata.version(key)
            for key in ["numpy", "pandas", "scipy", "statsmodels"]
        },
    }
    result["receipt_sha256"] = digest(result)
    return result
