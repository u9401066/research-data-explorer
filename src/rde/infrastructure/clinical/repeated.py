"""Within-person comparisons with frozen pairing, effects and drawing inputs."""

import importlib.metadata
import math

import numpy as np
from statsmodels.stats.multitest import multipletests

from .repeated_contract import RepeatedSpec, prepare_repeated
from .repeated_estimates import differences, friedman, paired_mean, signed_rank
from .survival import digest


def describe(values):
    """Scale before moments to avoid squaring large source measurements."""
    values = np.asarray(values, dtype=float)
    scale = float(np.max(np.abs(values))) or 1.0
    scaled = values / scale
    quantiles = np.quantile(scaled, [0, 0.25, 0.5, 0.75, 1]) * scale
    summary = {
        "n": len(values),
        "mean": float(np.mean(scaled) * scale),
        "sd": float(np.std(scaled, ddof=1) * scale),
        **dict(zip(["min", "q25", "median", "q75", "max"], map(float, quantiles), strict=True)),
    }
    if not all(math.isfinite(v) for v in summary.values()):
        raise ValueError("Nonfinite descriptive statistics; review source units before analysis.")
    return summary


def run_repeated(df, spec: RepeatedSpec):
    frame, ledger, frame_hash = prepare_repeated(df, spec)
    common = frame.loc[[row - 1 for row in ledger["complete_data_rows"]]]
    occasions = [
        {**item, **describe(common[item["column"]].to_numpy())} for item in spec.measurements
    ]
    hypotheses, contrasts = [], []
    omnibus = None
    if spec.omnibus:
        omnibus = {
            "id": "omnibus",
            "n": ledger["n"],
            "data_rows": ledger["complete_data_rows"],
            "effect_kind": "kendall_w",
            **friedman(
                common.to_numpy(),
                spec.confidence_level,
                resamples=spec.bootstrap["resamples"],
                seed=(spec.bootstrap["seed"] + len(spec.contrasts)) % 2**32,
            ),
        }
        hypotheses.append(
            {
                "id": "omnibus",
                "role": "omnibus",
                "n": ledger["n"],
                **{k: omnibus[k] for k in ["test", "p_value", "statistic", "warnings"]},
            }
        )
    for index, pair in enumerate(ledger["contrasts"]):
        subset = frame.loc[[row - 1 for row in pair["complete_data_rows"]], pair["columns"]]
        first, second = subset.to_numpy().T
        estimate = (
            paired_mean(first, second, spec.confidence_level)
            if spec.method == "paired_mean"
            else signed_rank(
                first,
                second,
                spec.confidence_level,
                resamples=spec.bootstrap["resamples"],
                seed=(spec.bootstrap["seed"] + index) % 2**32,
            )
        )
        delta = differences(first, second, spec.confidence_level)
        contrast = {
            "id": pair["id"],
            "columns": pair["columns"],
            "n": pair["n"],
            "data_rows": pair["complete_data_rows"],
            "effect_kind": spec.primary_effect,
            "difference_summary": describe(delta),
            "observations": [
                {"data_row": row, "first": float(a), "second": float(b), "difference": float(d)}
                for row, a, b, d in zip(
                    pair["complete_data_rows"], first, second, delta, strict=True
                )
            ],
            **estimate,
        }
        contrasts.append(contrast)
        hypotheses.append(
            {
                "id": pair["id"],
                "role": "planned_contrast",
                "n": pair["n"],
                "test": estimate["test"],
                "p_value": estimate["p_value"],
                "statistic": estimate["statistic"],
                "warnings": estimate.get("warnings", []),
            }
        )
    alpha = 1 - spec.confidence_level
    adjusted = multipletests(
        [h["p_value"] if h["p_value"] is not None else 1 for h in hypotheses],
        alpha=alpha,
        method="fdr_bh" if spec.multiplicity == "fdr" else spec.multiplicity,
    )[1]
    for hypothesis, p in zip(hypotheses, adjusted, strict=True):
        hypothesis.update(
            adjusted_p_value=float(p) if hypothesis["p_value"] is not None else None,
            reject_null=bool(p < alpha) if hypothesis["p_value"] is not None else None,
            alpha=alpha,
        )
    by_id = {h["id"]: h for h in hypotheses}
    for estimate in contrasts + ([omnibus] if omnibus else []):
        estimate.update({k: by_id[estimate["id"]][k] for k in ["adjusted_p_value", "reject_null"]})
    result = {
        "schema": "paired-repeated-v2",
        "family": "repeated",
        "status": "completed",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": frame_hash,
        "n": ledger["n"],
        "case_ledger": ledger,
        "occasions": occasions,
        "contrasts": contrasts,
        "omnibus": omnibus,
        "hypotheses": hypotheses,
        "observations": [
            {"data_row": int(index) + 1, "values": list(map(float, values))}
            for index, values in zip(common.index, common.to_numpy(), strict=True)
        ],
        "multiplicity": {
            "method": spec.multiplicity,
            "alpha": alpha,
            "size": len(hypotheses),
            "members": [h["id"] for h in hypotheses],
            "scope": "All prespecified paired contrasts plus Friedman only if planned. Unavailable tests retain their family slot. Pointwise effect intervals are unadjusted. Other studies/outcomes/branches are excluded.",
        },
        "warnings": [
            "Each contrast is first occasion minus second, regardless of display order. Subject pairing is retained throughout estimation and resampling.",
            "Occasion summaries and Friedman use common complete subjects; paired effects use the declared complete/pairwise case set. Pairwise populations may differ and must not share one denominator.",
            "All planned contrasts are reported regardless of omnibus significance. A p-value above alpha does not establish equivalence.",
            "Paired t inference concerns mean differences and assumes independent subjects and adequate difference-distribution assumptions. Signed-rank inference assumes sign symmetry under the null; the matched rank-biserial effect is neither a median difference nor independent-group dominance.",
            "Within-person changes do not establish treatment causality. This workflow does not adjust covariates, cluster subjects, estimate treatment-by-time interactions or model crossover period/carryover effects.",
            "Complete/pairwise deletion does not resolve informative missingness. No imputation, outcome-name plausibility exclusion or implicit numeric rounding is performed.",
        ],
        "versions": {
            name: importlib.metadata.version(name)
            for name in ["numpy", "pandas", "scipy", "statsmodels"]
        },
    }
    result["receipt_sha256"] = digest(result)
    return result
