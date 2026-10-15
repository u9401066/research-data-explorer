"""Binary CMH and Mantel-Haenszel OR with unmodified, source-bound strata."""

import importlib.metadata
import math
import warnings

import numpy as np
from scipy.stats import chi2
from statsmodels.stats.contingency_tables import StratifiedTable

from .stratified_contract import StratifiedSpec, prepare_stratified, stratified_tables
from .survival import digest


def _equal_odds(fitted, count, pooled_or):
    result = {
        "method": "Breslow-Day with Tarone adjustment",
        "degrees_of_freedom": count - 1,
        "role": "diagnostic_only",
        "status": "not_estimable",
        "statistic": None,
        "p_value": None,
        "warnings": [],
    }
    if pooled_or is None or pooled_or <= 0:
        result["reason"] = (
            "A finite positive common odds ratio is required for equal-odds diagnostics."
        )
        return result
    if pooled_or == 1:
        result["reason"] = (
            "The installed statsmodels Breslow-Day formula is singular at pooled OR=1; "
            "this diagnostic is unavailable, not evidence of homogeneous effects."
        )
        return result
    with warnings.catch_warnings(record=True) as caught, np.errstate(all="ignore"):
        warnings.simplefilter("always")
        fit = fitted.test_equal_odds(adjust=True)
    result["warnings"] = [str(item.message) for item in caught]
    value = float(fit.statistic)
    if not math.isfinite(value) or value < 0:
        result["reason"] = (
            "The equal-odds diagnostic was nonfinite or negative; no repaired p-value is substituted."
        )
        return result
    result.update(status="estimated", statistic=value, p_value=float(chi2.sf(value, count - 1)))
    return result


def run_stratified(df, spec: StratifiedSpec):
    frame, ledger, source_hash = prepare_stratified(df, spec)
    strata = stratified_tables(frame, spec)
    blockers = [item["label"] for item in strata if item["blocking_reasons"]]
    if len(frame) < 10 or blockers:
        raise ValueError(
            "CMH needs at least ten complete independent cases and positive treatment/outcome "
            f"margins in every declared stratum. Blocking strata: {blockers}. "
            "Inspect the preflight tables; no strata are silently removed or merged."
        )
    cube = np.stack([item["table"] for item in strata], axis=2).astype(float)
    fitted = StratifiedTable(cube, shift_zeros=False)
    with warnings.catch_warnings(record=True) as caught, np.errstate(all="ignore"):
        warnings.simplefilter("always")
        cmh_fit = fitted.test_null_odds(correction=False)
        raw_or = float(fitted.oddsratio_pooled)
    statistic = float(cmh_fit.statistic)
    if not math.isfinite(statistic) or statistic < 0:
        raise ValueError(
            "CMH statistic is not finite and nonnegative; no substitute analysis is run."
        )
    # sf avoids cancellation of statsmodels' 1-cdf at very small probabilities.
    cmh = {
        "id": "cmh_association",
        "method": "Cochran-Mantel-Haenszel",
        "status": "estimated",
        "null": "Conditional binary treatment-outcome independence within the declared strata",
        "statistic": statistic,
        "degrees_of_freedom": 1,
        "p_value": float(chi2.sf(statistic, 1)),
        "p_value_method": "asymptotic chi-square survival function (SciPy)",
        "continuity_correction": False,
    }
    effect = {
        "method": "Mantel-Haenszel common odds ratio",
        "direction": {
            "numerator_treatment": spec.treatment_levels[1],
            "denominator_treatment": spec.treatment_levels[0],
            "event": spec.outcome_levels[1],
            "non_event": spec.outcome_levels[0],
        },
        "status": "estimated" if math.isfinite(raw_or) and raw_or > 0 else "boundary",
        "estimate": raw_or if math.isfinite(raw_or) else None,
        "boundary": "zero" if raw_or == 0 else "unbounded" if math.isinf(raw_or) else None,
        "confidence_level": spec.confidence_level,
        "ci_status": "not_estimable",
        "ci_lower": None,
        "ci_upper": None,
        "log_standard_error": None,
        "ci_method": (
            "Normal interval on log(MH OR), Robins-Breslow-Greenland variance; "
            "exponentiated endpoints; pointwise, not multiplicity adjusted"
        ),
    }
    if math.isfinite(raw_or) and raw_or > 0:
        with warnings.catch_warnings(record=True) as interval_warnings, np.errstate(all="ignore"):
            warnings.simplefilter("always")
            lower, upper = map(
                float,
                fitted.oddsratio_pooled_confint(alpha=1 - spec.confidence_level, method="normal"),
            )
            se = float(fitted.logodds_pooled_se)
        caught.extend(interval_warnings)
        if (
            all(math.isfinite(value) for value in [lower, upper, se])
            and 0 < lower <= raw_or <= upper
            and se > 0
        ):
            effect.update(
                ci_status="estimated", ci_lower=lower, ci_upper=upper, log_standard_error=se
            )
        else:
            effect["reason"] = (
                "The log-scale interval was not finite and ordered; no cell correction is applied."
            )
    else:
        effect["reason"] = (
            "The uncorrected pooled OR is at a boundary; a log-normal confidence interval is unavailable."
        )

    equal_odds = _equal_odds(fitted, len(strata), effect["estimate"])
    notes = [
        "Source tables are not changed: no added 0.5, collapsed strata or continuity correction.",
        "CMH and the interval are asymptotic; sparse expected counts require review and are not exact inference.",
        "A common OR assumes an interpretable common association. A nonsignificant or unavailable equal-odds diagnostic does not establish homogeneity.",
        "The odds ratio is not a risk ratio, risk difference or causal treatment effect; declaring randomization does not verify ITT membership or causal assumptions.",
        "Shared complete-case exclusion does not establish MCAR/MAR or remove informative missingness. There is no imputation or weighting.",
        "The primary CMH test is a single prespecified hypothesis; the equal-odds test is diagnostic and does not gate reporting. Other endpoints/analyses are outside this family.",
    ]
    sparse = [item["label"] for item in strata if item["expected_cells_below_five"]]
    if sparse:
        notes.append(f"Expected cells below five occur in these retained strata: {sparse}.")
    notes.extend(str(item.message) for item in caught)
    result = {
        "schema": "clinical-result-v1",
        "method_schema": "stratified-binary-v1",
        "status": "completed",
        "family": "stratified",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "n": len(frame),
        "case_ledger": ledger,
        "strata": strata,
        "cmh": cmh,
        "common_odds_ratio": effect,
        "equal_odds": equal_odds,
        "hypotheses": [
            {
                **cmh,
                "alpha": 1 - spec.confidence_level,
                "reject_null": cmh["p_value"] < 1 - spec.confidence_level,
            }
        ],
        "observations": [
            {
                "data_row": int(index) + 1,
                "treatment": row.treatment,
                "outcome": row.outcome,
                "stratum": row.stratum,
            }
            for index, row in frame.iterrows()
        ],
        "multiplicity": {
            "method": "single_prespecified_primary_hypothesis",
            "size": 1,
            "members": ["cmh_association"],
            "scope": "Primary CMH only; equal-odds is a diagnostic, intervals are pointwise.",
        },
        "warnings": notes,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ["numpy", "pandas", "scipy", "statsmodels"]
        },
    }
    result["receipt_sha256"] = digest(result)
    return result
