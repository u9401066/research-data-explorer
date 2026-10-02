"""Prespecified independent comparisons and immutable numerical plotting inputs."""

import importlib.metadata
import math
import warnings

import numpy as np
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint

from .comparison_contract import ComparisonSpec, prepare_comparison
from .comparison_estimates import binary_comparison, rank_difference, welch_difference
from .survival import digest


def _omnibus(samples, spec):
    label = {
        "welch_mean": "Welch unequal-variance one-way ANOVA",
        "rank": "Kruskal–Wallis tie-corrected chi-square approximation",
        "binary": "Pearson chi-square; no continuity correction",
    }[spec.method]
    notes = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if spec.method == "welch_mean":
            from statsmodels.stats.oneway import anova_oneway

            fit = anova_oneway(samples, use_var="unequal", welch_correction=True)
            statistic, p = float(fit.statistic), float(fit.pvalue)
            df = list(map(float, fit.df))
        elif spec.method == "rank":
            if np.unique(np.concatenate(samples)).size == 1:
                statistic, p, df = float("nan"), float("nan"), [len(samples) - 1]
                notes.append("All values are tied; a Kruskal–Wallis H statistic is undefined.")
            else:
                fit = stats.kruskal(*samples)
                statistic, p, df = float(fit.statistic), float(fit.pvalue), [len(samples) - 1]
            if min(map(len, samples)) < 5:
                notes.append(
                    "Some groups have fewer than five cases; the omnibus chi-square approximation may be inaccurate."
                )
        else:
            table = [[int(sum(v == event)) for v in samples] for event in (0, 1)]
            fit = stats.chi2_contingency(table, correction=False)
            statistic, p, df = float(fit.statistic), float(fit.pvalue), [int(fit.dof)]
        notes.extend(str(item.message) for item in caught)
    available = math.isfinite(statistic) and math.isfinite(p) and all(math.isfinite(v) for v in df)
    if not available:
        notes.append(
            "No finite omnibus inference is available; no replacement test or p-value was substituted."
        )
    return {
        "id": "omnibus",
        "role": "omnibus",
        "test": label,
        "statistic": statistic if available else None,
        "p_value": p if available else None,
        "degrees_of_freedom": df if available else None,
        "warnings": notes,
    }


def run_comparison(df, spec: ComparisonSpec):
    frame, ledger, frame_hash = prepare_comparison(df, spec)
    samples = {
        label: frame.loc[frame.group == label, "response"].to_numpy(dtype=float)
        for label in spec.group_levels
    }
    summaries = []
    for label, values in samples.items():
        summary = {"label": label, "n": len(values)}
        if spec.method == "binary":
            summary["events"] = int(values.sum())
            summary["non_events"] = len(values) - int(values.sum())
            if spec.study_design not in {"case_control", "unspecified"}:
                lower, upper = proportion_confint(
                    summary["events"], len(values), alpha=1 - spec.confidence_level, method="wilson"
                )
                summary.update(
                    proportion=summary["events"] / len(values),
                    lower=float(lower),
                    upper=float(upper),
                )
        else:
            summary.update(
                {
                    "mean": float(values.mean()),
                    "sd": float(values.std(ddof=1)),
                    "min": float(values.min()),
                    "q25": float(np.quantile(values, 0.25)),
                    "median": float(np.median(values)),
                    "q75": float(np.quantile(values, 0.75)),
                    "max": float(values.max()),
                }
            )
            if any(not math.isfinite(v) for k, v in summary.items() if k not in {"label", "n"}):
                raise ValueError(
                    "Numeric scale produced nonfinite descriptive statistics; resolve source units first."
                )
            spread = summary["q75"] - summary["q25"]
            summary["whisker_low"] = float(values[values >= summary["q25"] - 1.5 * spread].min())
            summary["whisker_high"] = float(values[values <= summary["q75"] + 1.5 * spread].max())
        summaries.append(summary)
    hypotheses, contrasts = [], []
    if spec.omnibus:
        hypotheses.append(_omnibus(list(samples.values()), spec))
    for index, pair in enumerate(spec.contrasts):
        first, second = [samples[label] for label in pair]
        if spec.method == "welch_mean":
            estimate = welch_difference(first, second, spec.confidence_level)
            estimate["effects"] = {"mean_difference": estimate.pop("effect")}
        elif spec.method == "rank":
            estimate = rank_difference(
                first,
                second,
                spec.confidence_level,
                resamples=spec.bootstrap["resamples"],
                seed=(spec.bootstrap["seed"] + index) % 2**32,
            )
            estimate["effects"] = {"rank_biserial": estimate.pop("effect")}
        else:
            estimate = binary_comparison(
                int(first.sum()),
                len(first),
                int(second.sum()),
                len(second),
                spec.confidence_level,
                probabilities_identified=spec.study_design not in {"case_control", "unspecified"},
            )
        contrast = {
            "id": f"contrast_{index + 1}",
            "groups": pair,
            "sample_sizes": [len(first), len(second)],
            "primary_effect": spec.primary_effect,
            "data_rows": [(frame.index[frame.group == label] + 1).tolist() for label in pair],
            **estimate,
        }
        contrasts.append(contrast)
        hypotheses.append(
            {
                "id": contrast["id"],
                "role": "planned_contrast",
                "test": estimate["test"],
                "p_value": estimate["p_value"],
                "statistic": estimate.get("statistic"),
                "warnings": estimate.get("warnings", []),
            }
        )
    alpha = 1 - spec.confidence_level
    # Keep the full prespecified family even when one test is unavailable. Its
    # neutral placeholder affects correction only; never publish it as a p-value.
    adjusted = multipletests(
        [row["p_value"] if row["p_value"] is not None else 1 for row in hypotheses],
        alpha=alpha,
        method="fdr_bh" if spec.multiplicity == "fdr" else spec.multiplicity,
    )[1]
    for row, adjusted_p in zip(hypotheses, adjusted, strict=True):
        row["adjusted_p_value"] = float(adjusted_p) if row["p_value"] is not None else None
        row["reject_null"] = bool(adjusted_p < alpha) if row["p_value"] is not None else None
        row["alpha"] = alpha
    by_id = {row["id"]: row for row in hypotheses}
    for contrast in contrasts:
        contrast["adjusted_p_value"] = by_id[contrast["id"]]["adjusted_p_value"]
        contrast["reject_null"] = by_id[contrast["id"]]["reject_null"]
    result = {
        "schema": "independent-comparison-v1",
        "status": "completed",
        "family": "comparison",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": frame_hash,
        "n": len(frame),
        "case_ledger": ledger,
        "groups": summaries,
        "contrasts": contrasts,
        "hypotheses": hypotheses,
        "observations": [
            {"data_row": int(index) + 1, "group": row.group, "value": float(row.response)}
            for index, row in frame.iterrows()
        ],
        "multiplicity": {
            "method": spec.multiplicity,
            "alpha": alpha,
            "size": len(hypotheses),
            "members": [r["id"] for r in hypotheses],
            "scope": "All prespecified contrast tests and the optional omnibus in this study; unavailable tests retain their planned family slot. Effect intervals are pointwise and unadjusted; other outcomes/studies/branches are not included.",
        },
        "warnings": [
            "The direction is first group minus second for differences, and first / second for ratios; raw source labels and the event definition are prespecified.",
            "Unadjusted associations do not establish causal effects. Declaring a randomized design does not verify randomization, ITT membership or missingness assumptions.",
            "A p-value above alpha does not establish equivalence. Confidence intervals describe different effects and are not interchangeable with the multiplicity-adjusted decision.",
            "Undefined or unbounded estimates and unavailable intervals must remain explicit in all figures and reports; they are never zero-valued substitutes.",
        ],
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scipy", "statsmodels")
        },
    }
    result["receipt_sha256"] = digest(result)
    return result
