"""Independent two-group NI with a matching one-sided confidence bound.

Welch shifted-null inference is delegated to SciPy with a matching one-sided
bound. Binary noninferiority is explicitly unsupported; no replacement score,
Wald, pseudo-count or local binary estimator is maintained here.
"""

import importlib.metadata
import math

from scipy.stats import t, ttest_ind_from_stats

from .noninferiority_contract import (
    NoninferioritySpec,
    noninferiority_groups,
    prepare_noninferiority,
)
from .survival import digest


def _welch(first, second, spec):
    means = [float(first.mean()), float(second.mean())]
    variances = [float(first.var(ddof=1)), float(second.var(ddof=1))]
    n1, n2 = len(first), len(second)
    components = [variances[0] / n1, variances[1] / n2]
    total = sum(components)
    if not all(math.isfinite(v) for v in [*means, *variances, total]) or total <= 0:
        raise ValueError(
            "Welch noninferiority requires finite means and a positive finite standard error."
        )
    se = math.sqrt(total)
    df = 1 / ((components[0] / total) ** 2 / (n1 - 1) + (components[1] / total) ** 2 / (n2 - 1))
    # Center the two means before shifting the null. Adding a tiny margin to a
    # large raw mean can otherwise lose it to floating-point cancellation.
    observed = means[0] - means[1]
    fitted = ttest_ind_from_stats(
        observed + spec.margin,
        math.sqrt(variances[0]),
        n1,
        0.0,
        math.sqrt(variances[1]),
        n2,
        equal_var=False,
        alternative="greater",
    )
    statistic, p_value = float(fitted.statistic), float(fitted.pvalue)
    critical = float(t.isf(spec.one_sided_alpha, df))
    bound = observed - critical * se
    if not all(math.isfinite(v) for v in [statistic, p_value, observed, df, critical, bound]):
        raise ValueError(
            "Welch noninferiority produced nonfinite inference; no replacement method is used."
        )
    return {
        "benefit_difference": observed,
        "statistic": statistic,
        "p_value": p_value,
        "standard_error": se,
        "degrees_of_freedom": df,
        "reference_distribution": "Welch-Satterthwaite t",
        "critical_statistic": critical,
        "lower_confidence_bound": bound,
        "upper_confidence_bound": None,
        "upper_bound_kind": "unbounded",
        "test_method": "One-sided Welch t at shifted null difference -margin",
        "ci_method": "One-sided Welch bound with the identical standard error and Satterthwaite degrees of freedom",
        "warnings": [],
    }


def run_noninferiority(df, spec: NoninferioritySpec):
    frame, ledger, source_hash = prepare_noninferiority(df, spec)
    groups, blockers = noninferiority_groups(frame, spec)
    if len(frame) < 10 or blockers:
        raise ValueError(
            f"Noninferiority estimator boundary or insufficient complete cases: {blockers}; "
            "inspect preflight. No variance correction or alternate estimator is applied."
        )
    control = frame.loc[frame.treatment == spec.treatment_levels[0], "response"]
    treatment = frame.loc[frame.treatment == spec.treatment_levels[1], "response"]
    sign = 1 if spec.direction == "higher_is_better" else -1
    first, second = (treatment, control) if sign == 1 else (control, treatment)
    inference = _welch(first, second, spec)
    boundary = math.isclose(
        inference["statistic"], inference["critical_statistic"], rel_tol=1e-10, abs_tol=1e-12
    )
    test_passes = inference["p_value"] < spec.one_sided_alpha
    interval_passes = inference["lower_confidence_bound"] > -spec.margin
    if not boundary and test_passes != interval_passes:
        raise ValueError(
            "NI test and its matching confidence-bound decision disagree; no success is reported."
        )
    passed = bool(not boundary and test_passes and interval_passes)
    inference.update(
        raw_treatment_minus_control=sign * inference["benefit_difference"],
        direction=spec.direction,
        benefit_sign=sign,
        margin=spec.margin,
        margin_scale=spec.margin_scale,
        null_boundary=-spec.margin,
        null="benefit_difference <= -margin",
        alternative="benefit_difference > -margin",
        one_sided_alpha=spec.one_sided_alpha,
        confidence_level=spec.confidence_level,
        confidence_sidedness="one_sided_lower",
        passed=passed,
        decision="boundary_not_demonstrated"
        if boundary
        else "noninferiority_demonstrated"
        if passed
        else "noninferiority_not_demonstrated",
        numerical_boundary={
            "at_boundary": boundary,
            "statistic_relative_tolerance": 1e-10,
            "statistic_absolute_tolerance": 1e-12,
            "equality_passes": False,
        },
    )
    for summary, values in zip(groups, [control, treatment], strict=True):
        summary["mean"] = float(values.mean())
    result = {
        "schema": "clinical-result-v1",
        "method_schema": "independent-noninferiority-v1",
        "family": "noninferiority",
        "status": "completed",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "n": len(frame),
        "case_ledger": ledger,
        "groups": groups,
        "noninferiority": inference,
        "hypotheses": [
            {
                "id": "prespecified_noninferiority",
                "statistic": inference["statistic"],
                "p_value": inference["p_value"],
                "alpha": spec.one_sided_alpha,
                "reject_null": passed,
                "alternative": "benefit_difference > -margin",
            }
        ],
        "observations": [
            {"data_row": int(index) + 1, "treatment": row.treatment, "value": float(row.response)}
            for index, row in frame.iterrows()
        ],
        "multiplicity": {
            "method": "single_prespecified_noninferiority_hypothesis",
            "size": 1,
            "members": ["prespecified_noninferiority"],
            "scope": "One direction and margin only; no equivalence, superiority switch, interim look or endpoint family.",
        },
        "warnings": [
            "Noninferiority requires a prespecified clinically justified margin; the supplied basis, assay sensitivity and constancy assumptions are not verified by this calculation.",
            "Failure to demonstrate superiority is not evidence of noninferiority. Failure of this NI test does not by itself establish inferiority.",
            "The confidence level is one-sided: confidence_level=1-one_sided_alpha, not a two-sided interval at the same numeric level.",
            "Complete-case results do not verify ITT or per-protocol membership and may be sensitive to informative missingness. Population labels are supplied definitions, not certified facts.",
            "Independent subjects and one fixed analysis are required; no strata, clustering, crossover, multiple imputation or repeated looks are modeled.",
            "Observational or cross-sectional comparisons do not establish causal treatment noninferiority.",
            "Binary risk-difference noninferiority is not supported; Welch cannot be substituted for a binary NI request.",
        ]
        + inference["warnings"],
        "versions": {
            name: importlib.metadata.version(name) for name in ["numpy", "pandas", "scipy"]
        },
    }
    result["receipt_sha256"] = digest(result)
    return result
