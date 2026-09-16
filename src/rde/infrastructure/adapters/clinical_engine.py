"""Local clinical estimators with explicit case sets and no arbitrary code execution.

Each result carries assumptions and analysis denominators; no method selects a
threshold or model by minimizing a p-value. Binary inputs are explicitly 0/1.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

CLINICAL_METHODS = {
    "risk_estimates": "Independent binary outcome: RR, OR, risk difference and CIs",
    "diagnostic_accuracy": "Prespecified binary test: sensitivity, specificity, PPV/NPV and CIs",
    "mcnemar": "Row-aligned paired binary outcomes, exact McNemar test",
    "bland_altman": "Paired continuous measurement agreement and limits of agreement",
    "cohens_kappa": "Unweighted categorical inter-rater agreement",
    "gee": "Population-average clustered model: Gaussian, binomial or Poisson",
    "mixed_effects": "Continuous outcome random-intercept model",
}


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _estimate(value, interval, method: str) -> dict:
    return {
        "estimate": _finite(value),
        "ci_lower": _finite(interval[0]),
        "ci_upper": _finite(interval[1]),
        "ci_method": method,
    }


def _binary(series: pd.Series) -> pd.Series:
    if not series.isin([0, 1]).all():
        raise ValueError(
            f"{series.name}: binary data must be explicitly coded 0/1; no automatic recoding."
        )
    return series.astype(int)


def _frame(df: pd.DataFrame, columns: list[str], numeric: list[str]) -> tuple[pd.DataFrame, dict]:
    columns = list(dict.fromkeys(columns))
    if any(not column or column not in df.columns for column in columns):
        raise ValueError("All required variable names must exist in the dataset.")
    if not df.columns.is_unique:
        raise ValueError("Duplicate column names are ambiguous.")
    frame = df[columns].copy()
    original_missing = frame.isna().any(axis=1)
    for col in numeric:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    included = frame.notna().all(axis=1)
    positions = np.flatnonzero(included.to_numpy()).tolist()
    cases = {
        "n_input": len(df),
        "n_analyzed": int(included.sum()),
        "n_excluded": int((~included).sum()),
        "n_missing": int(original_missing.sum()),
        "n_invalid_numeric": int((~included & ~original_missing).sum()),
        "included_row_positions": positions,
        "row_position_base": 0,
        "strategy": "analysis-specific complete case; rows never independently compacted",
    }
    if included.sum() < 3:
        raise ValueError("At least three analyzable observations are required.")
    return frame.loc[included], cases


def _proportion(success: int, total: int, alpha: float) -> dict:
    from statsmodels.stats.proportion import proportion_confint

    if total == 0:
        return {
            "estimate": None,
            "ci_lower": None,
            "ci_upper": None,
            "numerator": success,
            "denominator": 0,
            "reason": "zero denominator",
        }
    interval = proportion_confint(success, total, alpha=alpha, method="wilson")
    return {
        **_estimate(success / total, interval, "Wilson score"),
        "numerator": success,
        "denominator": total,
    }


def run_clinical_analysis(df: pd.DataFrame, method: str, config: dict) -> dict:
    """Execute a registered estimator; input failures remain failures, never p=1."""
    if method not in CLINICAL_METHODS:
        raise ValueError(f"Unknown clinical method: {method}")
    confidence = float(config.get("confidence_level", 0.95))
    if not 0 < confidence < 1:
        raise ValueError("confidence_level must be strictly between 0 and 1.")
    alpha = 1 - confidence
    target = config.get("target")
    second = config.get("score_variable") or config.get("group_var")
    if method in {"gee", "mixed_effects"}:
        result = _clustered(df, method, config, alpha)
    else:
        numeric = [] if method == "cohens_kappa" else [target, second]
        if target == second:
            raise ValueError("Two distinct variables are required.")
        frame, cases = _frame(df, [target, second], numeric)
        a, b = frame[target], frame[second]
        handlers = {
            "risk_estimates": _risk,
            "diagnostic_accuracy": _diagnostic,
            "mcnemar": _mcnemar,
            "bland_altman": _bland_altman,
            "cohens_kappa": _kappa,
        }
        result = handlers[method](a, b, config, alpha)
        result["case_set"] = cases
    result.update(
        {
            "analysis_type": method,
            "engine": "local-clinical (scipy/statsmodels)",
            "confidence_level": confidence,
            "n": result["case_set"]["n_analyzed"],
            "multiplicity": "Unadjusted within this analysis; define a family across exploratory runs.",
            "claim_scope": "Association/agreement only; study design and clinical judgment govern interpretation.",
        }
    )
    return result


def _risk(outcome, exposure, config, alpha):
    from scipy.stats import fisher_exact
    from statsmodels.stats.contingency_tables import Table2x2
    from statsmodels.stats.proportion import confint_proportions_2indep

    y, x = _binary(outcome), _binary(exposure)
    table = np.array(
        [
            [int(((x == 1) & (y == 1)).sum()), int(((x == 1) & (y == 0)).sum())],
            [int(((x == 0) & (y == 1)).sum()), int(((x == 0) & (y == 0)).sum())],
        ]
    )
    n1, n0 = table.sum(axis=1)
    if min(n1, n0) == 0:
        raise ValueError("Both exposed=1 and reference=0 groups must contain observations.")
    a, c = table[:, 0]
    rd = float(a / n1 - c / n0)
    rd_ci = confint_proportions_2indep(a, n1, c, n0, compare="diff", method="newcomb", alpha=alpha)
    estimates = {"risk_difference": _estimate(rd, rd_ci, "Newcombe-Wilson independent proportions")}
    notes = [
        "Independent observations; unadjusted estimates do not establish causality.",
        "Risk ratio requires a design with estimable risks; do not interpret it as risk in case-control sampling.",
    ]
    if np.all(table > 0):
        model = Table2x2(table, shift_zeros=False)
        estimates["risk_ratio"] = _estimate(
            model.riskratio, model.riskratio_confint(alpha=alpha), "log Wald"
        )
        estimates["odds_ratio"] = _estimate(
            model.oddsratio, model.oddsratio_confint(alpha=alpha), "log Wald"
        )
    else:
        # No invisible continuity correction or meaningless finite estimate.
        estimates["risk_ratio"] = {
            "estimate": float((a / n1) / (c / n0)) if c else None,
            "ci_lower": None,
            "ci_upper": None,
        }
        estimates["odds_ratio"] = {"estimate": None, "ci_lower": None, "ci_upper": None}
        notes.append(
            "Zero cell: log-Wald ratio inference unavailable; no continuity correction applied. Null values may denote unbounded/non-estimable ratios."
        )
    return {
        "estimates": estimates,
        "table": table.tolist(),
        "table_order": "rows: exposed=1, reference=0; columns: event=1, non-event=0",
        "group_counts": {"exposed": int(n1), "reference": int(n0)},
        "p_value": float(fisher_exact(table).pvalue),
        "test": "two-sided Fisher exact",
        "warnings": notes,
    }


def _diagnostic(truth, test, config, alpha):
    gold = _binary(truth)
    threshold = config.get("threshold")
    if threshold is not None:
        threshold = float(threshold)
        if not math.isfinite(threshold):
            raise ValueError("Diagnostic threshold must be finite and prespecified.")
        direction = config.get("positive_direction", "greater_equal")
        if direction not in {"greater_equal", "less_equal"}:
            raise ValueError("positive_direction must be greater_equal or less_equal.")
        predicted = (
            test >= threshold if direction == "greater_equal" else test <= threshold
        ).astype(int)
    else:
        predicted = _binary(test)
    tp = int(((gold == 1) & (predicted == 1)).sum())
    tn = int(((gold == 0) & (predicted == 0)).sum())
    fp = int(((gold == 0) & (predicted == 1)).sum())
    fn = int(((gold == 1) & (predicted == 0)).sum())
    estimates = {
        name: _proportion(num, den, alpha)
        for name, num, den in [
            ("sensitivity", tp, tp + fn),
            ("specificity", tn, tn + fp),
            ("positive_predictive_value", tp, tp + fp),
            ("negative_predictive_value", tn, tn + fn),
            ("accuracy", tp + tn, len(gold)),
        ]
    }
    return {
        "estimates": estimates,
        "confusion_counts": {"TP": tp, "TN": tn, "FP": fp, "FN": fn},
        "threshold": threshold,
        "positive_direction": config.get("positive_direction", "greater_equal"),
        "warnings": [
            "Gold standard must be independently established; threshold is not optimized on these outcomes.",
            "PPV/NPV depend on prevalence and sampling; external validation is needed.",
            "Wilson intervals assume independent subjects, not repeated tests from the same subject.",
        ],
    }


def _mcnemar(before, after, config, alpha):
    from scipy.stats import binomtest
    from statsmodels.stats.contingency_tables import mcnemar

    a, b = _binary(before), _binary(after)
    table = pd.crosstab(a, b).reindex(index=[0, 1], columns=[0, 1], fill_value=0).to_numpy()
    gained, lost = int(table[0, 1]), int(table[1, 0])
    discordant = gained + lost
    test = mcnemar(table, exact=True)
    interval = (
        binomtest(gained, discordant).proportion_ci(confidence_level=1 - alpha, method="exact")
        if discordant
        else None
    )
    odds_ci = (
        [q / (1 - q) if q < 1 else math.inf for q in interval] if interval else [math.nan, math.nan]
    )
    return {
        "table": table.tolist(),
        "table_order": "rows before 0/1, columns after 0/1",
        "discordant_pairs": discordant,
        "statistic": float(test.statistic),
        "p_value": float(test.pvalue),
        "test": "exact two-sided McNemar",
        "estimates": {
            "matched_odds_ratio_after_vs_before": _estimate(
                gained / lost if lost else math.inf, odds_ci, "Clopper-Pearson discordant odds"
            ),
            "paired_risk_difference": {"estimate": (gained - lost) / len(a)},
        },
        "warnings": [
            "Each row must identify one subject's two measurements; complete pairs only.",
            "Null ratio bounds denote non-estimable or unbounded intervals; no discordant pairs means no evidence of change, not equivalence.",
        ],
    }


def _bland_altman(first, second, config, alpha):
    from scipy.stats import norm, t

    differences = first.to_numpy(dtype=float) - second.to_numpy(dtype=float)
    n = len(differences)
    bias, sd = float(np.mean(differences)), float(np.std(differences, ddof=1))
    z, critical = float(norm.ppf(1 - alpha / 2)), float(t.ppf(1 - alpha / 2, n - 1))
    bias_width = critical * sd / math.sqrt(n)
    loa_width = critical * sd * math.sqrt(1 / n + z * z / (2 * (n - 1)))
    lower, upper = bias - z * sd, bias + z * sd
    return {
        "estimates": {
            "bias_first_minus_second": _estimate(
                bias, [bias - bias_width, bias + bias_width], "t interval"
            ),
            "lower_limit_of_agreement": _estimate(
                lower,
                [lower - loa_width, lower + loa_width],
                "approximate normal-differences interval",
            ),
            "upper_limit_of_agreement": _estimate(
                upper,
                [upper - loa_width, upper + loa_width],
                "approximate normal-differences interval",
            ),
        },
        "sd_difference": sd,
        "agreement_coverage": 1 - alpha,
        "warnings": [
            "Assumes independent pairs, approximately normal differences and constant variance.",
            "Limits of agreement are not confidence intervals for the mean. Clinical acceptability margins must be chosen independently.",
            "Repeated measurements per subject require an appropriate hierarchical agreement method.",
        ],
    }


def _kappa(first, second, config, alpha):
    from scipy.stats import norm
    from statsmodels.stats.inter_rater import cohens_kappa

    # Factorize the union without stringifying distinct original labels.
    codes, labels = pd.factorize(pd.concat([first, second], ignore_index=True), sort=False)
    k, n = len(labels), len(first)
    if k < 2:
        raise ValueError("Kappa is not identifiable when all ratings use one category.")
    table = np.zeros((k, k), dtype=int)
    np.add.at(table, (codes[:n], codes[n:]), 1)
    result = cohens_kappa(table)
    se = math.sqrt(max(0.0, float(result.var_kappa)))
    width = float(norm.ppf(1 - alpha / 2)) * se
    return {
        "estimates": {
            "cohens_kappa": _estimate(
                result.kappa, [result.kappa - width, result.kappa + width], "asymptotic normal"
            )
        },
        "table": table.tolist(),
        "categories": [str(label) for label in labels],
        "observed_agreement": float(np.trace(table) / n),
        "warnings": [
            "Unweighted kappa; dependent on category prevalence and marginal distributions.",
            "One paired rating per independent subject; agreement is not diagnostic validity.",
        ],
    }


def _clustered(df, method, config, alpha):
    import statsmodels.api as sm

    target, subject = config.get("target"), config.get("subject_variable")
    covariates = list(dict.fromkeys(config.get("covariates") or []))
    if not subject or not covariates:
        raise ValueError("Clustered models require subject_variable and explicit covariates.")
    if target in covariates or subject in covariates or target == subject:
        raise ValueError("Outcome, subject ID and covariates must have distinct roles.")
    columns = [target, subject, *covariates]
    numeric = [target] + [c for c in covariates if c in df and pd.api.types.is_numeric_dtype(df[c])]
    frame, cases = _frame(df, columns, numeric)
    clusters = frame[subject].nunique()
    if clusters < 3 or clusters == len(frame):
        raise ValueError("Need at least three independent subjects and repeated observations.")
    x = pd.get_dummies(frame[covariates], drop_first=True, dtype=float)
    x = sm.add_constant(x, has_constant="add").astype(float)
    if x.shape[1] >= len(frame) or np.linalg.matrix_rank(x) < x.shape[1]:
        raise ValueError("Design matrix is rank-deficient or has insufficient observations.")
    y = frame[target].astype(float)
    notes = [
        "Model uses analysis-specific complete cases; assess MAR/MNAR and missingness sensitivity.",
        "Covariates and functional form require clinical justification; no causal interpretation is automatic.",
    ]
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        if method == "gee":
            family_name = config.get("family", "gaussian")
            families = {
                "gaussian": sm.families.Gaussian,
                "binomial": sm.families.Binomial,
                "poisson": sm.families.Poisson,
            }
            if family_name not in families:
                raise ValueError("GEE family must be gaussian, binomial or poisson.")
            if family_name == "binomial":
                y = _binary(y)
            if family_name == "poisson" and ((y < 0).any() or (y % 1 != 0).any()):
                raise ValueError("Poisson outcome must be nonnegative integer counts.")
            fitted = sm.GEE(
                y,
                x,
                groups=frame[subject],
                family=families[family_name](),
                cov_struct=sm.cov_struct.Exchangeable(),
            ).fit(maxiter=100, cov_type="robust")
            params, intervals, pvalues = fitted.params, fitted.conf_int(alpha=alpha), fitted.pvalues
            notes.append(
                "GEE robust sandwich inference is asymptotic in the number of independent clusters; few clusters may invalidate Wald CIs."
            )
            model_info = {"family": family_name, "covariance": "exchangeable; robust sandwich"}
        else:
            fitted = sm.MixedLM(y, x, groups=frame[subject]).fit(
                reml=True, method="lbfgs", maxiter=200, disp=False
            )
            params = fitted.fe_params
            intervals, pvalues = (
                fitted.conf_int(alpha=alpha).loc[params.index],
                fitted.pvalues.loc[params.index],
            )
            model_info = {
                "family": "gaussian",
                "random_effects": "subject intercept",
                "estimation": "REML",
                "random_intercept_variance": float(fitted.cov_re.iloc[0, 0]),
            }
            notes.append(
                "Random-intercept Gaussian model assumes suitable conditional residuals/random effects; inspect diagnostics before interpretation."
            )
    converged = bool(getattr(fitted, "converged", False))
    notes.extend(str(item.message) for item in captured)
    if not converged or not np.isfinite(params).all() or not np.isfinite(intervals).all().all():
        raise ValueError(
            "Model did not converge to finite estimates and confidence intervals; simplify or revise the model."
        )
    coefficients = [
        {
            "term": str(term),
            **_estimate(value, intervals.loc[term], "Wald"),
            "p_value": _finite(pvalues.loc[term]),
        }
        for term, value in params.items()
    ]
    cases["n_subjects"] = int(clusters)
    return {
        "case_set": cases,
        "coefficients": coefficients,
        "model": model_info,
        "converged": converged,
        "warnings": notes,
    }


def render_clinical_result(result: dict) -> str:
    """Readable clinical output; detailed row positions stay in JSON evidence."""
    cases = result["case_set"]
    lines = [
        f"# Clinical analysis — {result['analysis_type']}",
        "",
        f"Analyzed **{cases['n_analyzed']} / {cases['n_input']}** observations; "
        f"excluded {cases['n_excluded']} (missing: {cases['n_missing']}; invalid numeric: {cases['n_invalid_numeric']}).",
        f"Confidence level: {result['confidence_level']:.1%}. Case strategy: {cases['strategy']}.",
    ]
    if "n_subjects" in cases:
        lines.append(f"Independent subjects: {cases['n_subjects']}.")
    rows = [{"term": key, **value} for key, value in result.get("estimates", {}).items()]
    rows.extend(result.get("coefficients", []))
    if rows:
        lines.extend(
            [
                "",
                "| Estimate | Value | CI lower | CI upper | Method | p-value | Numerator / denominator |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            values = [
                row.get(key) for key in ["term", "estimate", "ci_lower", "ci_upper", "ci_method"]
            ]
            cells = [
                f"{v:.6g}"
                if isinstance(v, float)
                else str(v).replace("|", "\\|")
                if v is not None
                else "Not estimable"
                for v in values
            ]
            p_value = row.get("p_value")
            cells.append(f"{p_value:.6g}" if isinstance(p_value, (int, float)) else "—")
            cells.append(
                f"{row['numerator']} / {row['denominator']}" if "denominator" in row else "—"
            )
            lines.append("| " + " | ".join(cells) + " |")
    for key in [
        "p_value",
        "test",
        "table",
        "table_order",
        "group_counts",
        "confusion_counts",
        "discordant_pairs",
        "model",
    ]:
        if key in result:
            lines.append(f"- {key}: {result[key]}")
    lines.extend(
        ["", "## Interpretation and limitations", result["claim_scope"], result["multiplicity"]]
    )
    lines.extend(f"- {note}" for note in result.get("warnings", []))
    return "\n".join(lines)
