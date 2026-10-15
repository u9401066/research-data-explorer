"""Prespecified 1:1 caliper matching and approximate pair-cluster OLS inference.

No Abadie-Imbens matching-imputation variance, full-population ATT, or
finite-sample validity is claimed.
Matching optimization and model estimation use SciPy and statsmodels.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import importlib.metadata
import math
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.special import expit

from .regression import _reject_binary_separation
from .regression_contract import regression_design
from .survival import digest, level
from .weighting import _balance
from .weighting_contract import WeightingSpec, prepare_weighting


@dataclass(frozen=True, kw_only=True)
class MatchingSpec(WeightingSpec):
    """Reuse validated source roles; do not execute the weighting estimator."""

    caliper_sd: float
    family: str = "matching"
    method: str = "optimal_1to1_logit_caliper"
    inference: str = "pair_cluster_cr1_t"

    def source_spec(self):
        payload = {f.name: getattr(self, f.name) for f in fields(WeightingSpec)}
        # ATT here selects the existing pre-treatment source-role validator.
        # The actual matching estimand and result are never inferred from it.
        payload.update(family="weighting", estimand="ATT")
        return WeightingSpec.parse(payload)

    @classmethod
    def parse(cls, options):
        if not isinstance(options, dict) or set(options) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown matching settings; use the exact study contract.")
        try:
            result = cls(**options)
        except TypeError as error:
            raise ValueError(f"Missing matching settings: {error}") from error
        result.validate()
        return result

    def validate(self):
        if (
            self.family != "matching"
            or self.method != "optimal_1to1_logit_caliper"
            or self.inference != "pair_cluster_cr1_t"
            or self.estimand != "matched_treated"
        ):
            raise ValueError(
                "Use prespecified 1:1 matching without replacement and pair-cluster inference "
                "for the matched-treated population; full ATT/ATE and other variants are not implicit."
            )
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("Matching requires a stable, nonmissing, unique subject identity.")
        if (
            type(self.caliper_sd) not in {int, float}
            or not math.isfinite(self.caliper_sd)
            or not 0 < self.caliper_sd <= 2
        ):
            raise ValueError("Prespecify a positive logit-SD caliper no greater than 2.")
        self.source_spec()


QUALITY_POLICY = {
    "schema": "matching-quality-policy-v1",
    "minimum_pairs": 5,
    "small_pair_warning_below": 30,
    "sparse_discordant_warning_below": 10,
    "absolute_smd_review_above": 0.1,
    "variance_ratio_review_outside": [0.5, 2.0],
    "scope": "Fixed descriptive review rules, not power calculations or proof of causal validity; no outcome-driven design changes.",
}


def prepare_matching(df, spec):
    spec.validate()
    if spec.subject in df.columns and df.columns.is_unique:
        identifiers = df[spec.subject].map(level)
        if identifiers.isna().any() or identifiers.duplicated().any():
            raise ValueError(
                "Every source subject identity must be nonmissing and unique before cohort or missing-role exclusions."
            )
    frame, ledger, source_hash = prepare_weighting(df, spec.source_spec())
    ledger = {
        **ledger,
        "policy": "Common complete cases across treatment, outcome and all baseline propensity covariates before matching; no imputation. Outcome availability defines this cohort but outcome values never select pairs.",
    }
    return frame, ledger, source_hash


def matching_preflight(df, spec):
    frame, ledger, source_hash = prepare_matching(df, spec)
    design, terms, groups = regression_design(frame, spec.propensity_spec())
    if len(design.columns) + 2 >= len(frame):
        raise ValueError(
            "Propensity parameters plus two must be below the complete-case count; not a power rule."
        )
    return {
        "schema": "matching-preflight-v1",
        "spec": spec.to_dict(),
        "spec_sha256": digest(spec.to_dict()),
        "dataframe_sha256": source_hash,
        "design_sha256": digest(
            {"columns": design.columns.tolist(), "values": design.to_numpy().tolist()}
        ),
        "n": len(frame),
        "input_rows": len(df),
        "case_ledger": ledger,
        "terms": terms,
        "term_groups": groups,
        "quality_policy": QUALITY_POLICY.copy(),
        "study_design": spec.study_design,
        "estimand": spec.estimand,
        "method": spec.method,
        "inference": spec.inference,
        "propensity_parameters": len(design.columns),
        "treatment_levels": [
            {"label": label, "code": code, "n": int((frame.treatment == code).sum())}
            for code, label in enumerate(spec.treatment_levels)
        ],
        "outcome_levels": [
            {"label": label, "code": code, "n": int((frame.response == code).sum())}
            for code, label in enumerate(spec.outcome_levels)
        ],
        "can_execute": True,
        "scope": "Source-role and complete-case design checks only. Propensity convergence, matching quality and retained pair count remain unknown until execution; causal assumptions are not verified.",
    }


def _distribution(values):
    return {
        "n": len(values),
        "mean": float(np.mean(values)),
        "sample_variance": float(np.var(values, ddof=1)),
        **dict(
            zip(
                ["min", "q25", "median", "q75", "max"],
                map(float, np.quantile(values, [0, 0.25, 0.5, 0.75, 1])),
                strict=True,
            )
        ),
    }


def _matching_balance(values, treatment, matched, *, indicator=False):
    values = np.asarray(values, dtype=float)
    before = [values[treatment == code] for code in (0, 1)]
    after = [values[(treatment == code) & matched.astype(bool)] for code in (0, 1)]
    result = _balance(values, treatment, matched, "ATT", indicator=indicator)
    result["matched_control_mean"] = result.pop("control_weighted_mean")
    result["matched_treated_mean"] = result.pop("treated_weighted_mean")
    result["matched_difference"] = result.pop("weighted_difference")
    result["matched_smd"] = result.pop("weighted_smd")
    for label, pair in [("before", before), ("after", after)]:
        result[label] = {"control": _distribution(pair[0]), "treated": _distribution(pair[1])}
        support = np.unique(np.r_[pair[0], pair[1]])
        cdfs = [np.searchsorted(np.sort(v), support, side="right") / len(v) for v in pair]
        result[label]["ecdf_max_difference"] = float(np.max(np.abs(cdfs[0] - cdfs[1])))
        vc, vt = [np.var(v, ddof=1) for v in pair]
        result[label]["variance_ratio"] = float(vt / vc) if vc > 0 and not indicator else None
        result[label]["variance_ratio_status"] = (
            "not_applicable_indicator"
            if indicator
            else "zero_control_variance"
            if vc == 0
            else "estimated"
        )
    result["review_reasons"] = []
    if result["matched_smd"] is None:
        result["review_reasons"].append("zero_original_treated_sd")
    elif abs(result["matched_smd"]) > QUALITY_POLICY["absolute_smd_review_above"]:
        result["review_reasons"].append("residual_mean_imbalance")
    vr = result["after"]["variance_ratio"]
    if not indicator and (vr is None or not 0.5 <= vr <= 2):
        result["review_reasons"].append("residual_variance_imbalance_or_undefined")
    return result


def optimal_pairs(treated_logits, control_logits, caliper):
    """Maximum cardinality, then minimum total absolute logit discrepancy.

    Callers supply identity-sorted rows. Dummy controls represent unmatched
    treated cases. Their penalty dominates every possible valid-distance sum;
    forbidden edges cost still more. No control may be reused.
    """
    treated = np.asarray(treated_logits, dtype=float)
    control = np.asarray(control_logits, dtype=float)
    if (
        treated.ndim != 1
        or control.ndim != 1
        or not len(treated)
        or not len(control)
        or not np.isfinite(treated).all()
        or not np.isfinite(control).all()
        or not math.isfinite(caliper)
        or caliper < 0
    ):
        raise ValueError("Matching needs finite score vectors and a nonnegative absolute caliper.")
    nt, nc = len(treated), len(control)
    if nt * (nc + nt) > 2_000_000:
        raise ValueError("The exact assignment exceeds the 2,000,000-cell runtime limit.")
    distances = np.abs(treated[:, None] - control[None, :])
    allowed = distances <= caliper
    penalty = nt + 1.0
    cost = np.full((nt, nc + nt), penalty)
    cost[:, :nc] = np.where(
        allowed, distances / caliper if caliper > 0 else 0.0, penalty * (nt + 1.0)
    )
    rows, columns = linear_sum_assignment(cost)
    return [
        (int(i), int(j), float(distances[i, j]))
        for i, j in zip(rows, columns, strict=True)
        if j < nc and allowed[i, j]
    ]


def pair_cluster_effect(treated, controls, confidence):
    """Statsmodels OLS [intercept, treatment], CR1 by pair, t(G-1)."""
    import statsmodels.api as sm

    first, second = np.asarray(treated, dtype=float), np.asarray(controls, dtype=float)
    if (
        first.ndim != 1
        or second.shape != first.shape
        or len(first) < 5
        or not np.isfinite(first).all()
        or not np.isfinite(second).all()
        or not 0 < confidence < 1
    ):
        raise ValueError("At least five finite complete pairs are required; not a power rule.")
    differences = first - second
    if not np.isfinite(differences).all() or np.ptp(differences) == 0:
        raise ValueError("Pair-difference variance is zero or nonfinite; no CI fabricated.")
    count = len(first)
    y = np.column_stack([second, first]).ravel()
    treatment = np.tile([0.0, 1.0], count)
    design = np.column_stack([np.ones(len(y)), treatment])
    fit = sm.OLS(y, design).fit(
        cov_type="cluster",
        cov_kwds={
            "groups": np.repeat(np.arange(count), 2),
            "use_correction": True,
            "df_correction": True,
        },
        use_t=True,
    )
    covariance = np.asarray(fit.cov_params())
    if not np.isfinite(covariance).all() or covariance[1, 1] <= 0:
        raise ValueError("Pair-cluster effect variance is zero or nonfinite; no CI fabricated.")
    bounds = fit.conf_int(alpha=1 - confidence)[1]
    return {
        "estimate": float(fit.params[1]),
        "standard_error": float(fit.bse[1]),
        "statistic": float(fit.tvalues[1]),
        "p_value": float(fit.pvalues[1]),
        "confidence_level": confidence,
        "ci_lower": float(bounds[0]),
        "ci_upper": float(bounds[1]),
        "df": int(fit.df_resid_inference),
        "n_pairs": count,
        "control_mean": float(second.mean()),
        "treated_mean": float(first.mean()),
        "parameters": fit.params.tolist(),
        "covariance": covariance.tolist(),
        "method": "Treatment-only OLS; pair-cluster CR1; two-sided t with G-1 df",
        "covariance_correction": "G/(G-1) * (N-1)/(N-K), N=2G, K=2",
        "scope": "Approximate post-matching inference; not exact small-sample inference or Abadie-Imbens 2016 propensity-estimation adjustment.",
    }


def run_matching(df, spec: MatchingSpec):
    import statsmodels.api as sm

    spec.validate()
    frame, population, source_hash = prepare_matching(df, spec)
    identifiers = df.reset_index(drop=True).loc[frame.index, spec.subject].map(level)
    frame = frame.loc[identifiers.sort_values(kind="stable").index]
    identifiers = identifiers.loc[frame.index]
    design, terms, _ = regression_design(frame, spec.propensity_spec())
    x = design.to_numpy(dtype=float)
    if x.shape[1] + 2 >= len(frame):
        raise ValueError("Propensity parameters plus two must be below complete-case count.")
    a = frame.treatment.to_numpy(dtype=float)
    _reject_binary_separation(x, a)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fit = sm.GLM(a, x, family=sm.families.Binomial()).fit(maxiter=200, tol=1e-12)
    beta = np.asarray(fit.params, dtype=float)
    logits, notes = x @ beta, [str(item.message) for item in caught]
    scores = expit(logits)
    if (
        not fit.converged
        or not np.isfinite(beta).all()
        or not np.isfinite(scores).all()
        or (scores <= 0).any()
        or (scores >= 1).any()
        or any("separation" in note.lower() for note in notes)
        or np.max(np.abs(np.mean(x * (a - scores)[:, None], axis=0)) / np.max(np.abs(x), axis=0))
        > 1e-8
    ):
        raise ValueError("Propensity fit must be finite, converged and nonseparated; no clipping.")
    information = x.T @ ((scores * (1 - scores))[:, None] * x)
    if (
        not np.isfinite(information).all()
        or np.linalg.matrix_rank(information) != x.shape[1]
        or np.min(np.linalg.eigvalsh(information)) <= 0
    ):
        raise ValueError(
            "Propensity information is singular or nonpositive; no penalized fallback."
        )
    group_indices = [np.flatnonzero(a == code) for code in (0, 1)]
    controls, treated = group_indices
    pooled_sd = float(np.sqrt((logits[controls].var(ddof=1) + logits[treated].var(ddof=1)) / 2))
    absolute_caliper = spec.caliper_sd * pooled_sd
    pairs = optimal_pairs(logits[treated], logits[controls], absolute_caliper)
    if len(pairs) < 5:
        raise ValueError("Fewer than five eligible pairs; do not widen the caliper automatically.")
    selected_t = np.array([treated[i] for i, _, _ in pairs])
    selected_c = np.array([controls[j] for _, j, _ in pairs])
    y = frame.response.to_numpy(dtype=float)
    effect = pair_cluster_effect(y[selected_t], y[selected_c], spec.confidence_level)
    matched = np.zeros(len(frame), dtype=float)
    matched[selected_t] = matched[selected_c] = 1
    pair_rows = [
        {
            "pair_id": f"pair-{ordinal + 1:06d}",
            "treated_id": identifiers.iloc[treated[i]],
            "control_id": identifiers.iloc[controls[j]],
            "treated_data_row": int(frame.index[treated[i]]) + 1,
            "control_data_row": int(frame.index[controls[j]]) + 1,
            "absolute_logit_distance": distance,
            "treated_propensity": float(scores[treated[i]]),
            "control_propensity": float(scores[controls[j]]),
            "treated_outcome": float(y[treated[i]]),
            "control_outcome": float(y[controls[j]]),
        }
        for ordinal, (i, j, distance) in enumerate(pairs)
    ]
    lookup = {row[key]: row["pair_id"] for row in pair_rows for key in ("treated_id", "control_id")}
    records = [
        {
            "subject_id": identifiers.iloc[i],
            "source_data_row": int(frame.index[i]) + 1,
            "treatment_code": int(a[i]),
            "propensity": float(scores[i]),
            "logit": float(logits[i]),
            "pair_id": lookup.get(identifiers.iloc[i]),
            "status": "matched" if matched[i] else "unmatched",
            "unmatched_reason": None
            if matched[i]
            else (
                "no_control_within_caliper"
                if not np.any(np.abs(logits[i] - logits[controls]) <= absolute_caliper)
                else "control_competition_at_maximum_cardinality"
            )
            if a[i] == 1
            else (
                "no_treated_within_caliper"
                if not np.any(np.abs(logits[i] - logits[treated]) <= absolute_caliper)
                else "unused_control_at_maximum_cardinality"
            ),
        }
        for i in range(len(frame))
    ]
    balance = []
    for i, covariate in enumerate(spec.covariates):
        values = frame[f"x{i}"]
        categories = covariate["levels"] if covariate["kind"] == "categorical" else [None]
        for category in categories:
            balance.append(
                {
                    "column": covariate["column"],
                    "level": category,
                    **_matching_balance(
                        values if category is None else (values == category).astype(float),
                        a,
                        matched,
                        indicator=category is not None,
                    ),
                }
            )
    terms_by_key = {term["term"]: term for term in terms}
    basis_balance = []
    for term in terms[1:]:
        indicator = term["role"] == "categorical" or (
            term["role"] == "interaction"
            and all(terms_by_key[key]["role"] == "categorical" for key in term["components"])
        )
        basis_balance.append(
            {**term, **_matching_balance(design[term["term"]], a, matched, indicator=indicator)}
        )
    selected_rows = sorted(int(frame.index[i]) + 1 for i in [*selected_t, *selected_c])
    unmatched_rows = sorted(int(frame.index[i]) + 1 for i in range(len(frame)) if not matched[i])
    ledger = {
        **population,
        "n": len(selected_rows),
        "propensity_complete_data_rows": population["complete_data_rows"],
        "complete_data_rows": selected_rows,
        "matching_excluded_data_rows": unmatched_rows,
    }
    by_row = {record["source_data_row"]: record for record in records}
    missing_rows = set(population["missing_excluded_data_rows"])
    source = df.reset_index(drop=True)
    for index in range(len(source)):
        row = index + 1
        if row not in by_row:
            absent = (
                [column for column in spec.variables() if pd.isna(level(source.loc[index, column]))]
                if row in missing_rows
                else []
            )
            by_row[row] = {
                "subject_id": level(source.loc[index, spec.subject]),
                "source_data_row": row,
                "status": "missing_required" if row in missing_rows else "outside_cohort",
                "missing_source_roles": absent,
                "propensity": None,
                "logit": None,
                "pair_id": None,
                "treatment_code": None,
                "unmatched_reason": None,
            }
    records = [by_row[row] for row in sorted(by_row)]
    groups, histogram = [], []
    edges = np.linspace(0, 1, 21)
    for code, label in enumerate(spec.treatment_levels):
        original, retained = scores[a == code], scores[(a == code) & matched.astype(bool)]
        groups.append(
            {
                "code": code,
                "source_label": label,
                "eligible_n": len(original),
                "matched_n": len(retained),
                "before": _distribution(original),
                "after": _distribution(retained),
            }
        )
        before_hist, _ = np.histogram(original, edges)
        after_hist, _ = np.histogram(retained, edges)
        histogram.extend(
            {
                "treatment_code": code,
                "left": float(edges[i]),
                "right": float(edges[i + 1]),
                "eligible_n": int(before_hist[i]),
                "matched_n": int(after_hist[i]),
                "eligible_proportion": float(before_hist[i] / len(original)),
                "matched_proportion": float(after_hist[i] / len(retained)),
            }
            for i in range(20)
        )
    paired_binary = None
    if spec.outcome_type == "binary":
        counts = [
            [int(np.sum((y[selected_c] == c) & (y[selected_t] == t))) for t in (0, 1)]
            for c in (0, 1)
        ]
        paired_binary = {
            "rows": "control outcome code 0,1",
            "columns": "treated outcome code 0,1",
            "cells": counts,
            "discordant_pairs": counts[0][1] + counts[1][0],
            "source_outcome_levels": spec.outcome_levels,
        }
    flags = []
    if len(pairs) < QUALITY_POLICY["small_pair_warning_below"]:
        flags.append("few_matched_pairs")
    if (
        paired_binary
        and paired_binary["discordant_pairs"] < QUALITY_POLICY["sparse_discordant_warning_below"]
    ):
        flags.append("few_discordant_pairs")
    if any(row["review_reasons"] for row in balance + basis_balance):
        flags.append("observed_balance_requires_review")
    result = {
        "schema": "clinical-result-v1",
        "method_schema": "matching-study-v1",
        "family": "matching",
        "status": "completed",
        "n": len(selected_rows),
        "spec": asdict(spec),
        "spec_sha256": digest(asdict(spec)),
        "dataframe_sha256": source_hash,
        "population": population,
        "matching_population": {
            "complete_cases": len(frame),
            "matched_pairs": len(pairs),
            "matched_people": 2 * len(pairs),
            "unmatched_treated": len(treated) - len(pairs),
            "unmatched_controls": len(controls) - len(pairs),
            "target": "The treated subset retained by the prespecified matching design",
        },
        "matching": {
            "method": spec.method,
            "ratio": "1:1",
            "replacement": False,
            "caliper_sd": spec.caliper_sd,
            "caliper_scale": "sqrt((sample_var(control_logit) + sample_var(treated_logit))/2)",
            "pooled_logit_sd": pooled_sd,
            "absolute_logit_caliper": absolute_caliper,
            "bounds": "inclusive; zero logit SD permits only exact score matches",
            "objective": "maximum cardinality then minimum total absolute logit discrepancy",
            "order": "canonical subject-id order; tied assignment is solver-version dependent",
        },
        "propensity": {
            "parameters": beta.tolist(),
            "terms": terms,
            "warnings": notes,
            "converged": True,
            "model": "Unpenalized logistic GLM with intercept",
            "information": information.tolist(),
        },
        "pairs": pair_rows,
        "case_ledger": ledger,
        "source_case_ledger": records,
        "balance": balance,
        "basis_balance": basis_balance,
        "diagnostics": {
            "groups": groups,
            "propensity_histogram": histogram,
            "common_score_range": {
                "lower": max(g["before"]["min"] for g in groups),
                "upper": min(g["before"]["max"] for g in groups),
            },
            "standardization": "Fixed original complete-case treated SD; indicators use p*(1-p), continuous bases use sample variance ddof=1",
            "histogram_policy": "20 fixed bins on [0,1], final bin closed; no smoothing or score clipping",
            "quality_policy": QUALITY_POLICY.copy(),
            "review_flags": flags,
        },
        "paired_binary": paired_binary,
        "effect": {
            **effect,
            "measure": "risk_difference" if spec.outcome_type == "binary" else "mean_difference",
            "direction": "treated minus control",
        },
        "multiplicity": {
            "method": "single_prespecified_matched_contrast",
            "size": 1,
            "members": ["matched_treated_contrast"],
        },
        "limitations": [
            "Matched-treated contrast is not automatically the full original ATT or ATE.",
            "Matching uses treatment and baseline covariates; outcome values never enter score fitting or assignment.",
            "Complete-case selection and matching exclusions change the analysis population; missingness is not proven ignorable.",
            "Observed balance and a caliper do not prove positivity, absence of unmeasured confounding or causal identification.",
            "Pair-cluster inference is approximate; limited pairs and residual imbalance require explicit review. It does not fully adjust estimated-propensity uncertainty or prove finite-sample coverage.",
            "No with-replacement, multiple-controls, survival, recurrent-event, pooled-MI or automatic caliper search support.",
        ],
        "versions": {
            name: importlib.metadata.version(name) for name in ("scipy", "statsmodels", "numpy")
        },
    }
    result["receipt_sha256"] = digest(result)
    return result
