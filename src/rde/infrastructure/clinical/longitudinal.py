"""Prespecified CPU longitudinal estimators; plots consume this saved receipt only."""

from __future__ import annotations

import importlib.metadata
import warnings

import numpy as np
from scipy.stats import norm

from .longitudinal_contract import LongitudinalSpec, longitudinal_design, prepare_longitudinal
from .survival import digest


def run_longitudinal(df, spec: LongitudinalSpec):
    import statsmodels.api as sm
    from statsmodels.stats.multitest import multipletests

    frame, ledger, frame_hash = prepare_longitudinal(df, spec)
    # Fitting order is explicit; original data-row indices remain attached to every point.
    frame = frame.sort_values(["subject", "time"], kind="stable")
    design, terms = longitudinal_design(frame, spec)
    response = frame.outcome.astype(float)
    groups = frame.subject
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if spec.method == "gee":
            family = {
                "gaussian": sm.families.Gaussian,
                "binomial": sm.families.Binomial,
                "poisson": sm.families.Poisson,
            }[spec.distribution]()
            covariance = (
                sm.cov_struct.Exchangeable()
                if spec.correlation == "exchangeable"
                else sm.cov_struct.Independence()
            )
            offset = np.log(frame.exposure) if spec.exposure else None
            fitted = sm.GEE(
                response, design, groups=groups, family=family, cov_struct=covariance, offset=offset
            ).fit(maxiter=100, cov_type="robust")
            if any(getattr(covariance, "cov_adjust", [])):
                raise ValueError(
                    "GEE required a working-covariance positive-definite repair; review the declared correlation explicitly."
                )
            if spec.correlation == "exchangeable" and not (
                -1 / (ledger["observations_per_subject"]["max"] - 1)
                < float(covariance.dep_params)
                < 1
            ):
                raise ValueError(
                    "The estimated exchangeable correlation is not positive definite for every subject."
                )
            params = fitted.params.loc[design.columns]
            cov = fitted.cov_params().loc[design.columns, design.columns]
            means = np.asarray(fitted.fittedvalues, dtype=float)
            residual = np.asarray(fitted.resid_response, dtype=float)
            pearson = np.asarray(fitted.resid_pearson, dtype=float)
            model = dict(
                method="GEE",
                distribution=spec.distribution,
                link={"gaussian": "identity", "binomial": "logit", "poisson": "log"}[
                    spec.distribution
                ],
                working_correlation=spec.correlation,
                estimated_working_correlation=(
                    float(covariance.dep_params) if spec.correlation == "exchangeable" else None
                ),
                covariance="subject-cluster robust sandwich",
                inference="asymptotic normal Wald",
                max_iterations=100,
                offset="log(exposure)" if spec.exposure else None,
                fitted_mean="population mean given each observed row's covariates and exposure",
                working_covariance_repairs=0,
            )
            random_effects = None
        else:
            random_design = (
                design[["intercept", "time"]] if spec.random_slope else design[["intercept"]]
            )
            fitted = sm.MixedLM(response, design, groups=groups, exog_re=random_design).fit(
                reml=True, method="lbfgs", maxiter=200, disp=False
            )
            params = fitted.fe_params.loc[design.columns]
            cov = fitted.cov_params().loc[design.columns, design.columns]
            means = np.asarray(fitted.fittedvalues, dtype=float)
            residual = np.asarray(fitted.resid, dtype=float)
            if not np.isfinite(fitted.scale) or fitted.scale <= 0:
                raise ValueError("Mixed model residual variance is not finite and positive.")
            pearson = residual / np.sqrt(fitted.scale)
            random_cov = fitted.cov_re.to_numpy(dtype=float)
            if not np.isfinite(random_cov).all() or np.min(np.linalg.eigvalsh(random_cov)) <= 0:
                raise ValueError(
                    "Mixed random-effect covariance is singular; revise the prespecified model explicitly."
                )
            random_effects = {
                "terms": random_design.columns.tolist(),
                "covariance": random_cov.tolist(),
                "conditional_modes": {
                    str(key): value.to_numpy(dtype=float).tolist()
                    for key, value in fitted.random_effects.items()
                },
            }
            model = dict(
                method="Gaussian linear mixed model",
                distribution="gaussian",
                link="identity",
                estimation="REML",
                optimizer="lbfgs",
                max_iterations=200,
                random_effects="subject intercept and correlated linear time slope"
                if spec.random_slope
                else "subject intercept",
                covariance="model-based fixed-effect covariance",
                inference="asymptotic normal Wald",
                residual_variance=float(fitted.scale),
                log_likelihood=float(fitted.llf),
                fitted_mean="conditional mean including estimated subject random effects",
            )
    notes = [str(item.message) for item in caught]
    if (
        not bool(getattr(fitted, "converged", False))
        or not np.isfinite(params).all()
        or not np.isfinite(cov).all().all()
        or np.linalg.matrix_rank(cov.to_numpy()) != len(params)
        or np.min(np.linalg.eigvalsh(cov.to_numpy())) <= 0
        or not np.isfinite(means).all()
        or not np.isfinite(residual).all()
        or not np.isfinite(pearson).all()
        or any("not positive definite" in note.lower() for note in notes)
    ):
        raise ValueError(
            "The longitudinal fit did not converge with finite, nonsingular mean-parameter inference."
        )
    standard_error = np.sqrt(np.diag(cov))
    z_values = params.to_numpy() / standard_error
    pvalues = 2 * norm.sf(np.abs(z_values))
    z = norm.ppf((1 + spec.confidence_level) / 2)
    lower, upper = params.to_numpy() - z * standard_error, params.to_numpy() + z * standard_error
    adjusted = multipletests(pvalues[1:], alpha=1 - spec.confidence_level, method="holm")[1]
    ratio = spec.distribution in {"binomial", "poisson"}
    effect = (
        (
            "odds ratio"
            if spec.distribution == "binomial"
            else "rate ratio"
            if spec.exposure
            else "mean count ratio"
        )
        if ratio
        else "mean difference"
    )
    coefficients = []
    for i, metadata in enumerate(terms):
        values = np.array([params.iloc[i], lower[i], upper[i]], dtype=float)
        if ratio:
            with np.errstate(over="ignore", under="ignore"):
                values = np.exp(values)
            if not np.isfinite(values).all() or (values <= 0).any():
                raise ValueError(
                    "Exponentiated coefficient intervals are not finite and positive; review separation/model instability."
                )
        coefficients.append(
            {
                **metadata,
                "coefficient": float(params.iloc[i]),
                "standard_error": float(standard_error[i]),
                "coefficient_lower": float(lower[i]),
                "coefficient_upper": float(upper[i]),
                "effect_scale": (
                    {
                        "gaussian": "reference mean",
                        "binomial": "reference odds",
                        "poisson": "reference rate" if spec.exposure else "reference mean count",
                    }[spec.distribution]
                    if not i
                    else "ratio of "
                    + {
                        "binomial": "odds ratios",
                        "poisson": "rate ratios" if spec.exposure else "mean count ratios",
                    }[spec.distribution]
                    if metadata["role"] == "interaction" and ratio
                    else "difference in time effects"
                    if metadata["role"] == "interaction"
                    else effect
                ),
                "estimate": float(values[0]),
                "lower": float(values[1]),
                "upper": float(values[2]),
                "p_value": float(pvalues[i]),
                "p_adjusted": float(adjusted[i - 1]) if i else None,
            }
        )
    subject_codes = {subject: f"S{i + 1}" for i, subject in enumerate(sorted(groups.unique()))}
    if random_effects:
        random_effects["conditional_modes"] = [
            {"subject_code": subject_codes[subject], "values": values}
            for subject, values in random_effects["conditional_modes"].items()
        ]
    points = []
    for i, (index, row) in enumerate(frame.iterrows()):
        points.append(
            dict(
                data_row=int(index + 1),
                subject_code=subject_codes[row.subject],
                time=float(row.time),
                group=row.group,
                observed=float(response.iloc[i]),
                fitted=float(means[i]),
                residual=float(residual[i]),
                pearson_residual=float(pearson[i]),
                fixed_linear_predictor=float(design.iloc[i] @ params),
                exposure=float(row.exposure) if spec.exposure else None,
            )
        )
    observed_by_time = []
    for (group, time), subset in frame.groupby(["group", "time"], sort=True):
        total = float(subset.outcome.sum())
        exposure = float(subset.exposure.sum()) if spec.exposure else None
        observed_by_time.append(
            dict(
                group=group,
                time=float(time),
                observations=len(subset),
                subjects=int(subset.subject.nunique()),
                outcome_total=total,
                exposure_total=exposure,
                estimate=total / exposure if spec.exposure else total / len(subset),
                statistic="aggregate observed rate"
                if spec.exposure
                else "observed proportion"
                if spec.distribution == "binomial"
                else "observed mean",
            )
        )
    limitations = [
        "Subjects, not repeated rows, are the independent sampling units. The numerical minimum is not a sample-size justification.",
        "Only the declared model, reference categories, time form and interaction are fitted; no variable selection or significance-based search is performed.",
        "Missing model fields exclude individual observations, not all visits of a subject; unrecorded visits and reasons for missingness cannot be inferred.",
        "Time and outcome units retain the supplied source scale. Linear time is centered at the declared reference; categorical time is not an equal-interval linear trend.",
        "Mean-parameter intervals are individual asymptotic Wald intervals. Holm correction applies only to the prespecified family of non-intercept coefficient p-values, not to intervals, other models or unperformed omnibus tests.",
        "Covariate adjustment and model convergence do not establish causality, randomization, clinical validity or absence of residual confounding.",
    ]
    if spec.time_by_group:
        limitations.append(
            "With time-by-group interaction, each group main effect is evaluated at the declared reference time, and each time main effect applies to the reference group. Interaction coefficients represent differences in time effects (Gaussian) or ratios of odds/count/rate ratios, not standalone group effects."
        )
    if spec.method == "gee":
        limitations += [
            "GEE estimates population-average associations; robust sandwich inference relies on enough independent subjects and a correctly specified mean model.",
            "Ordinary GEE does not generally make outcome-dependent missingness ignorable. Assess missingness assumptions; no weighting or imputation for dropout is performed.",
            "Time-varying covariates require appropriate exogeneity assumptions, especially with non-independence working correlation; temporal feedback is not addressed automatically.",
        ]
        if ledger["n_subjects"] < 40:
            limitations.append(
                "Fewer than 40 subjects: asymptotic sandwich/Wald uncertainty may be unreliable; no small-sample correction has been applied."
            )
        if spec.distribution == "poisson":
            limitations.append(
                "A Poisson mean model with robust uncertainty does not prove equidispersion. Without an explicit exposure offset, exponentiated terms are mean-count ratios, not standardized incidence rates."
            )
        if spec.distribution == "binomial":
            limitations.append(
                "Exponentiated coefficients are population-average odds ratios, not risk ratios or subject-specific odds ratios."
            )
    else:
        limitations += [
            "Gaussian mixed models assume suitable conditional residuals/random effects and the specified random-effect structure; their distributions are not proven by a fit or diagnostic plot.",
            "Likelihood inference requires an ignorable missingness mechanism given the modeled information; no claim of MAR/MCAR is inferred from the observed data.",
            "Wald fixed-effect inference uses normal asymptotics, not Satterthwaite/Kenward–Roger degrees of freedom. Random-effect estimates near a boundary require separate review.",
        ]
    result = dict(
        schema="rde-longitudinal-study-v1",
        status="completed",
        spec=spec.to_dict(),
        spec_sha256=digest(spec.to_dict()),
        dataframe_sha256=frame_hash,
        n=len(frame),
        n_subjects=ledger["n_subjects"],
        case_ledger=ledger,
        model={**model, "converged": True, "parameters": len(params)},
        coefficients=coefficients,
        coefficient_covariance=cov.to_numpy().tolist(),
        random_effects=random_effects,
        points=points,
        observed_by_time=observed_by_time,
        multiplicity={
            "method": "holm",
            "family": [t["term"] for t in terms[1:]],
            "ci_adjusted": False,
        },
        warnings=notes,
        limitations=limitations,
        versions={
            key: importlib.metadata.version(key)
            for key in ["numpy", "pandas", "scipy", "statsmodels"]
        },
    )
    # Reject any hidden nonfinite diagnostic before writing an immutable receipt.
    result["receipt_sha256"] = digest(result)
    return result
