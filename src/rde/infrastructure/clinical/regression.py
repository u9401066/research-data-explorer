"""Independent-case estimators and immutable inference, without variable search."""

from __future__ import annotations

import importlib.metadata
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.stats import chi2, f, norm, t

from .regression_contract import RegressionSpec, prepare_regression, regression_design
from .survival import digest


def _reject_binary_separation(matrix, response):
    """A nonzero improving nonnegative margin identifies a separating direction.

    Split a bounded coefficient direction into positive/negative parts. This also
    catches quasi-complete separation with some zero margins; no fitted p-values
    or outcome-driven variable selection are involved.
    """
    x = np.asarray(matrix, dtype=float)
    x = x / np.max(np.abs(x), axis=0)
    signed = (2 * np.asarray(response) - 1)[:, None] * x
    width = x.shape[1]
    result = linprog(
        np.r_[-signed.mean(axis=0), signed.mean(axis=0)],
        A_ub=np.vstack([np.column_stack([-signed, signed]), np.ones(2 * width)]),
        b_ub=np.r_[np.zeros(len(x)), 1.0],
        bounds=(0, None),
        method="highs",
    )
    if not result.success:
        raise ValueError(
            "The binary separation check could not be resolved; review the model explicitly."
        )
    if result.fun < -1e-9:
        raise ValueError(
            "Complete or quasi-complete binary separation prevents ordinary finite logistic inference."
        )


def _positive_covariance(covariance, name):
    if (
        not np.isfinite(covariance).all()
        or np.linalg.matrix_rank(covariance) != len(covariance)
        or np.min(np.linalg.eigvalsh(covariance)) <= 0
    ):
        raise ValueError(f"{name} is not finite, full-rank and positive definite.")


def _reject_count_separation(matrix, response):
    """Reject a direction that lowers zero-count means without changing positive ones.

    See Correia, Guimaraes and Zylkin, arXiv:1903.01633. For NB2, the same
    direction improves zero-count likelihood at any fixed positive dispersion.
    No rows, predictors or offsets are silently removed to obtain a finite fit.
    """
    y = np.asarray(response)
    if not (y == 0).any():
        return
    x = np.asarray(matrix, dtype=float)
    x = x / np.max(np.abs(x), axis=0)
    zero, positive = x[y == 0], x[y > 0]
    width = x.shape[1]
    result = linprog(
        np.r_[zero.mean(axis=0), -zero.mean(axis=0)],
        A_ub=np.vstack([np.column_stack([zero, -zero]), np.ones(2 * width)]),
        b_ub=np.r_[np.zeros(len(zero)), 1.0],
        A_eq=np.column_stack([positive, -positive]),
        b_eq=np.zeros(len(positive)),
        bounds=(0, None),
        method="highs",
    )
    if not result.success:
        raise ValueError(
            "The count separation check could not be resolved; review the model explicitly."
        )
    if result.fun < -1e-9:
        raise ValueError(
            "Count separation prevents ordinary finite log-mean inference; no source rows were dropped."
        )


def _finite_exponential(values):
    with np.errstate(over="ignore", under="ignore"):
        result = np.exp(values)
    if not np.isfinite(result).all() or (result <= 0).any():
        raise ValueError(
            "Exponentiated estimates or intervals are outside the finite positive range."
        )
    return result


def run_regression(df, spec: RegressionSpec):
    import statsmodels.api as sm
    from statsmodels.miscmodels.ordinal_model import OrderedModel
    from statsmodels.stats.multitest import multipletests

    frame, ledger, source_hash = prepare_regression(df, spec)
    design, terms, groups = regression_design(frame, spec)
    y = frame.outcome.to_numpy(dtype=float)
    p = len(design.columns)
    offset = np.log(frame.exposure.to_numpy()) if spec.exposure else None
    if spec.distribution == "binomial":
        _reject_binary_separation(design, y)
    elif spec.distribution in {"poisson", "negative_binomial"}:
        _reject_count_separation(design, y)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if spec.distribution == "gaussian":
            fit = sm.OLS(y, design).fit(cov_type="HC3", use_t=True)
            converged = True
            covariance = "HC3 heteroskedasticity-robust"
            inference = "t approximation with n minus mean-parameter-count degrees of freedom"
        elif spec.distribution in {"binomial", "poisson"}:
            family = (
                sm.families.Binomial() if spec.distribution == "binomial" else sm.families.Poisson()
            )
            fit = sm.GLM(y, design, family=family, offset=offset).fit(
                maxiter=200, cov_type="HC0", use_t=False
            )
            converged = bool(fit.converged)
            covariance = "HC0 independent-case sandwich"
            inference = "asymptotic normal Wald"
        elif spec.distribution == "negative_binomial":
            fit = sm.NegativeBinomial(y, design, loglike_method="nb2", offset=offset).fit(
                method="bfgs", maxiter=300, gtol=1e-8, disp=False
            )
            converged = bool(fit.mle_retvals.get("converged"))
            covariance = "joint model-based observed-information covariance, including estimated NB2 dispersion"
            inference = "asymptotic normal Wald"
        else:
            fit = OrderedModel(y.astype(int), design, distr="logit").fit(
                method="bfgs", maxiter=500, gtol=1e-8, disp=False
            )
            converged = bool(fit.mle_retvals.get("converged"))
            covariance = (
                "joint model-based observed-information covariance, including ordinal thresholds"
            )
            inference = "asymptotic normal Wald"
    notes = [str(item.message) for item in caught]
    parameters = np.asarray(fit.params, dtype=float)
    full_covariance = np.asarray(fit.cov_params(), dtype=float)
    if (
        not converged
        or not np.isfinite(parameters).all()
        or any("separation" in note.lower() for note in notes)
    ):
        raise ValueError(
            "The prespecified model did not converge to finite, nonseparated parameter estimates."
        )
    _positive_covariance(full_covariance, "Regression parameter covariance")
    beta = parameters[:p]
    cov = full_covariance[:p, :p]
    df_resid = len(frame) - p
    gaussian = spec.distribution == "gaussian"
    critical = float(
        t.ppf((1 + spec.confidence_level) / 2, df_resid)
        if gaussian
        else norm.ppf((1 + spec.confidence_level) / 2)
    )
    standard_error = np.sqrt(np.diag(cov))
    statistics = beta / standard_error
    pvalues = 2 * (t.sf(np.abs(statistics), df_resid) if gaussian else norm.sf(np.abs(statistics)))
    intervals = np.column_stack(
        [beta - critical * standard_error, beta + critical * standard_error]
    )
    tested = [i for i, term in enumerate(terms) if term["role"] != "intercept"]
    adjusted = dict(zip(tested, multipletests(pvalues[tested], method="holm")[1]))
    effect_scale = {
        "gaussian": "mean difference",
        "binomial": "odds ratio",
        "ordinal": "common cumulative odds ratio for higher outcome categories",
        "poisson": "rate ratio" if spec.exposure else "mean count ratio",
        "negative_binomial": "rate ratio" if spec.exposure else "mean count ratio",
    }[spec.distribution]
    spline_terms = {term["term"] for term in terms if term["role"] == "spline_basis"}
    coefficients = []
    for i, term in enumerate(terms):
        spline_component = term["term"] in spline_terms or bool(
            set(term.get("components", [])) & spline_terms
        )
        exponentiated = not gaussian and not spline_component
        values = np.r_[beta[i], intervals[i]]
        if exponentiated:
            values = _finite_exponential(values)
        scale = (
            "spline basis coefficient on the linear-predictor scale"
            if spline_component
            else "reference mean"
            if gaussian and term["role"] == "intercept"
            else "reference odds"
            if spec.distribution == "binomial" and term["role"] == "intercept"
            else "reference rate"
            if spec.exposure and term["role"] == "intercept"
            else "reference mean count"
            if term["role"] == "intercept"
            else "difference in conditional effects"
            if gaussian and term["role"] == "interaction"
            else f"ratio of {effect_scale}s"
            if term["role"] == "interaction"
            else effect_scale
        )
        coefficients.append(
            {
                **term,
                "coefficient": float(beta[i]),
                "standard_error": float(standard_error[i]),
                "coefficient_lower": float(intervals[i, 0]),
                "coefficient_upper": float(intervals[i, 1]),
                "estimate": float(values[0]),
                "lower": float(values[1]),
                "upper": float(values[2]),
                "effect_scale": scale,
                "exponentiated": exponentiated,
                "p_value": float(pvalues[i]),
                "p_adjusted": float(adjusted[i]) if i in adjusted else None,
            }
        )

    # Prespecified joint term tests form a separate, explicitly named Holm family.
    tests = list(groups)
    for i, predictor in enumerate(spec.predictors):
        if not predictor.get("knots"):
            continue
        nonlinear = {
            term["term"]
            for term in terms
            if term.get("predictor") == i and term.get("basis", 0) > 0
        }
        related = [
            term["term"]
            for term in terms
            if term["term"] in nonlinear or set(term.get("components", [])) & nonlinear
        ]
        tests.append({"role": "nonlinearity", "predictors": [i], "terms": related})
    joint_tests = []
    for test in tests:
        indices = [design.columns.get_loc(name) for name in test["terms"]]
        sub_cov = cov[np.ix_(indices, indices)]
        _positive_covariance(sub_cov, "Joint-test covariance")
        value = float(beta[indices] @ np.linalg.solve(sub_cov, beta[indices]))
        dimension = len(indices)
        statistic = value / dimension if gaussian else value
        probability = float(
            f.sf(statistic, dimension, df_resid) if gaussian else chi2.sf(statistic, dimension)
        )
        joint_tests.append(
            {
                **test,
                "statistic": statistic,
                "distribution": "F approximation" if gaussian else "chi-square approximation",
                "df": dimension,
                "denominator_df": df_resid if gaussian else None,
                "p_value": probability,
            }
        )
    for entry, probability in zip(
        joint_tests, multipletests([item["p_value"] for item in joint_tests], method="holm")[1]
    ):
        entry["p_adjusted"] = float(probability)

    nuisance, points, outcome_summary = [], [], []
    linear = design.to_numpy() @ beta
    if offset is not None:
        linear += offset
    model = {
        "distribution": spec.distribution,
        "link": "identity"
        if gaussian
        else "cumulative logit"
        if spec.distribution == "ordinal"
        else "logit"
        if spec.distribution == "binomial"
        else "log",
        "estimation": "ordinary least squares" if gaussian else "maximum likelihood",
        "covariance": covariance,
        "inference": inference,
        "mean_parameters": p,
        "total_parameters": len(parameters),
        "degrees_of_freedom": df_resid if gaussian else None,
        "offset": "log(exposure)" if spec.exposure else None,
        "converged": True,
        "log_likelihood": float(fit.llf),
        "sampling_design": spec.study_design,
    }
    if spec.distribution == "ordinal":
        thresholds = fit.model.transform_threshold_params(parameters)[1:-1]
        if not np.isfinite(thresholds).all() or not (np.diff(thresholds) > 0).all():
            raise ValueError("Ordinal thresholds are not finite and strictly ordered.")
        for i, threshold in enumerate(thresholds):
            derivative = np.zeros(len(parameters))
            derivative[p] = 1.0
            if i:
                derivative[p + 1 : p + i + 1] = np.exp(parameters[p + 1 : p + i + 1])
            se = float(np.sqrt(derivative @ full_covariance @ derivative))
            nuisance.append(
                {
                    "kind": "ordinal threshold",
                    "between": spec.outcome_levels[i : i + 2],
                    "estimate": float(threshold),
                    "standard_error": se,
                    "lower": float(threshold - critical * se),
                    "upper": float(threshold + critical * se),
                    "inference": "delta-method pointwise normal interval; not an exposure effect",
                }
            )
        probabilities = np.asarray(fit.model.predict(parameters, exog=design), dtype=float)
        if (
            not np.isfinite(probabilities).all()
            or (probabilities < 0).any()
            or (probabilities > 1).any()
            or not np.allclose(probabilities.sum(axis=1), 1, atol=1e-10, rtol=0)
        ):
            raise ValueError("Ordinal fitted category probabilities are invalid.")
        for row, index in enumerate(frame.index):
            points.append(
                {
                    "data_row": int(index + 1),
                    "observed_code": int(y[row]),
                    "observed_label": spec.outcome_levels[int(y[row])],
                    "linear_predictor": float(linear[row]),
                    "category_probabilities": probabilities[row].tolist(),
                }
            )
        for i, label in enumerate(spec.outcome_levels):
            outcome_summary.append(
                {
                    "label": label,
                    "code": i,
                    "n": int((y == i).sum()),
                    "observed_proportion": float((y == i).mean()),
                    "mean_fitted_probability": float(probabilities[:, i].mean()),
                }
            )
        model["threshold_parameterization"] = (
            "first cutpoint followed by log positive increments; reported thresholds transformed with delta-method covariance"
        )
    else:
        means = np.asarray(fit.predict(), dtype=float)
        residuals = y - means
        if gaussian:
            variance = np.full(len(frame), float(fit.scale))
            model["residual_variance"] = float(fit.scale)
        elif spec.distribution == "binomial":
            variance = means * (1 - means)
            model["separation_check"] = (
                "bounded linear-program separating-direction check, normalized mean-margin tolerance 1e-9"
            )
        elif spec.distribution == "poisson":
            variance = means
        else:
            alpha = float(parameters[-1])
            if alpha <= 1e-8:
                raise ValueError(
                    "NB2 dispersion is at the zero boundary; review the prespecified model explicitly."
                )
            alpha_se = float(np.sqrt(full_covariance[-1, -1]))
            limits = _finite_exponential(
                np.log(alpha) + np.array([-1, 1]) * critical * alpha_se / alpha
            )
            nuisance.append(
                {
                    "kind": "NB2 dispersion",
                    "estimate": alpha,
                    "standard_error": alpha_se,
                    "lower": float(limits[0]),
                    "upper": float(limits[1]),
                    "inference": "delta-method pointwise log-scale normal interval",
                }
            )
            variance = means + alpha * means**2
            model["variance_function"] = "mu + alpha * mu^2, with alpha estimated jointly"
        if not np.isfinite(means).all() or not np.isfinite(variance).all() or (variance <= 0).any():
            raise ValueError("Regression fitted values or conditional variances are invalid.")
        pearson = residuals / np.sqrt(variance)
        model["pearson_sum_squares_per_residual_df"] = float(pearson @ pearson / df_resid)
        if spec.distribution in {"poisson", "negative_binomial"}:
            model["separation_check"] = (
                "bounded linear-program zero-count direction check with positive-count equality constraints; normalized mean-margin tolerance 1e-9"
            )
        for row, index in enumerate(frame.index):
            points.append(
                {
                    "data_row": int(index + 1),
                    "observed": float(y[row]),
                    "fitted": float(means[row]),
                    "residual": float(residuals[row]),
                    "pearson_residual": float(pearson[row]),
                    "linear_predictor": float(linear[row]),
                    "exposure": float(frame.exposure.iloc[row]) if spec.exposure else None,
                }
            )

    # Conditional comparisons are frozen now; publication rendering never refits.
    curves = []
    for i, predictor in enumerate(spec.predictors):
        if predictor["kind"] != "continuous":
            continue
        values = np.unique(
            np.r_[
                np.linspace(frame[f"x{i}"].min(), frame[f"x{i}"].max(), 101), predictor["reference"]
            ]
        )
        grid = pd.DataFrame(
            {f"x{j}": [p["reference"]] * len(values) for j, p in enumerate(spec.predictors)}
        )
        grid[f"x{i}"] = values
        reference = pd.DataFrame({f"x{j}": [p["reference"]] for j, p in enumerate(spec.predictors)})
        matrix, _, _ = regression_design(grid, spec, check_rank=False)
        anchor, _, _ = regression_design(reference, spec, check_rank=False)
        difference = matrix.to_numpy() - anchor.to_numpy()
        contrast = difference @ beta
        variance = np.einsum("ij,jk,ik->i", difference, cov, difference)
        if not np.isfinite(variance).all() or (variance < -1e-10).any():
            raise ValueError("Conditional contrast variance is invalid.")
        se = np.sqrt(np.maximum(variance, 0))
        estimates = np.column_stack([contrast, contrast - critical * se, contrast + critical * se])
        if not gaussian:
            estimates = _finite_exponential(estimates)
        curves.append(
            {
                "predictor": i,
                "column": predictor["column"],
                "unit": predictor["unit"],
                "reference": predictor["reference"],
                "profile": {
                    p["column"]: p["reference"]
                    for p in spec.predictors
                    if p["column"] != predictor["column"]
                },
                "effect_scale": effect_scale,
                "scope": "Conditional model contrast with all other predictors at their declared references; not an average treatment effect or external validation; pointwise unadjusted intervals.",
                "points": [
                    {
                        "value": float(value),
                        "estimate": float(row[0]),
                        "lower": float(row[1]),
                        "upper": float(row[2]),
                    }
                    for value, row in zip(values, estimates)
                ],
            }
        )

    limitations = [
        "Independent cases, declared roles and one common complete-case population; no imputation, survey weighting, automatic variable selection or causal identification.",
        "Use the declared study design; fitting a regression does not change a randomized design into an observational one or verify randomization execution, ITT completeness or causal efficacy.",
        "Coefficient and joint-term p-values have separate declared Holm families. Pointwise intervals are unadjusted; there is no familywise claim across both families or different models.",
        "Main terms and conditional curves apply at the other predictors' declared references. Interaction terms are differences or ratios of conditional effects; spline basis coefficients are not per-unit clinical effects.",
        "Complete-case inclusion does not establish MCAR/MAR or absence of selection bias. Convergence, full design rank and positive covariance do not prove model assumptions or adequate power.",
        "Curves remain within each predictor's observed marginal range; their reference profiles can still be sparsely supported joint combinations. They are model contrasts, not new patient validation.",
    ]
    if spec.distribution == "ordinal":
        limitations += [
            "Proportional odds uses one slope vector at every cumulative threshold. No formal proportional-odds assumption test is performed; ordered categories are not equally spaced measurements.",
            "Threshold estimates are transformed cutpoints, not exposure odds ratios. Observed and mean fitted category proportions are in-sample diagnostics, not validated predictive performance.",
        ]
    if spec.distribution in {"poisson", "negative_binomial"}:
        limitations.append(
            "Without an explicit duration offset, exponentiated effects compare mean counts, not person-time rates. Pearson dispersion is a diagnostic summary, not a test establishing the variance model."
        )
    if spec.study_design in {"observational_cohort", "cross_sectional", "case_control"}:
        limitations.append(
            "The declared design is observational; adjustment cannot by itself remove unmeasured confounding or establish causal treatment effects."
        )
    if spec.study_design == "case_control":
        limitations.append(
            "Case-control fitted probabilities and the intercept describe the sampled case-control mix; they are not population disease risks or prevalence. Odds ratios are not automatically risk ratios."
        )
    result = {
        "schema": "rde-regression-study-v1",
        "status": "completed",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "n": len(frame),
        "case_ledger": ledger,
        "model": model,
        "coefficients": coefficients,
        "coefficient_covariance": cov.tolist(),
        "optimization_parameters": parameters.tolist(),
        "optimization_covariance": full_covariance.tolist(),
        "nuisance_parameters": nuisance,
        "joint_tests": joint_tests,
        "points": points,
        "outcome_summary": outcome_summary,
        "conditional_curves": curves,
        "multiplicity": {
            "method": "holm",
            "coefficient_family": [terms[i]["term"] for i in tested],
            "joint_family": [
                {"role": item["role"], "predictors": item["predictors"]} for item in joint_tests
            ],
            "ci_adjusted": False,
            "families_separate": True,
        },
        "warnings": notes,
        "limitations": limitations,
        "versions": {
            key: importlib.metadata.version(key)
            for key in ["numpy", "pandas", "scipy", "statsmodels"]
        },
    }
    result["receipt_sha256"] = digest(result)
    return result
