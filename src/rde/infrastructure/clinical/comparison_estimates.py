"""Fixed, directional independent-group estimates for the comparison study.

No automatic estimand selection. Undefined and unbounded results retain explicit
states and strict JSON; a plotting function must never turn them into zero.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
from scipy import optimize, stats
from scipy.stats.contingency import odds_ratio
from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint


def scalar(value):
    value = float(value)
    if math.isnan(value):
        return {"value": None, "status": "undefined"}
    if math.isinf(value):
        return {"value": None, "status": "positive_infinity" if value > 0 else "negative_infinity"}
    return {"value": value, "status": "finite"}


def interval(estimate, bounds, confidence, method, reason=None):
    lower, upper = bounds if bounds is not None else (float("nan"), float("nan"))
    return {
        "estimate": scalar(estimate),
        "lower": scalar(lower),
        "upper": scalar(upper),
        "confidence_level": confidence,
        "method": method,
        "status": "available" if bounds is not None else "unavailable",
        "reason": reason,
        "coverage": "pointwise; not adjusted for multiplicity",
    }


def _confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.8 <= value <= 0.999:
        raise ValueError("Comparison confidence level must be between 0.8 and 0.999.")


def _samples(first, second, confidence):
    _confidence(confidence)
    values = [np.asarray(sample, dtype=float) for sample in (first, second)]
    if any(
        sample.ndim != 1 or len(sample) < 2 or not np.isfinite(sample).all() for sample in values
    ):
        raise ValueError(
            "Each independent group needs at least two finite values; resolve exclusions first."
        )
    return values


def welch_difference(first, second, confidence=0.95):
    first, second = _samples(first, second, confidence)
    try:
        with np.errstate(over="raise", invalid="raise"):
            variances = np.array([sample.var(ddof=1) / len(sample) for sample in (first, second)])
            difference = float(first.mean() - second.mean())
    except FloatingPointError as error:
        raise ValueError(
            "Numeric range exceeds finite Welch arithmetic; review the source scale."
        ) from error
    variance = float(variances.sum())
    method = "Welch t interval with Welch–Satterthwaite degrees of freedom"
    if variance <= 0 or not math.isfinite(variance):
        return {
            "effect": interval(
                difference,
                None,
                confidence,
                method,
                "No finite positive estimated sampling variance.",
            ),
            "p_value": None,
            "statistic": None,
            "degrees_of_freedom": None,
            "test": "two-sided Welch t",
            "standard_error": None,
        }
    df = 1 / sum(
        (v / variance) ** 2 / (len(sample) - 1) for v, sample in zip(variances, (first, second))
    )
    se = math.sqrt(variance)
    statistic = difference / se
    critical = stats.t.ppf((1 + confidence) / 2, df)
    return {
        "effect": interval(
            difference, (difference - critical * se, difference + critical * se), confidence, method
        ),
        "p_value": float(2 * stats.t.sf(abs(statistic), df)),
        "statistic": float(statistic),
        "degrees_of_freedom": float(df),
        "test": "two-sided Welch t",
        "standard_error": se,
    }


def rank_dominance(first, second, axis=-1):
    """P(first > second) - P(first < second), with ties contributing zero."""
    first, second = np.moveaxis(first, axis, -1), np.moveaxis(second, axis, -1)
    n1, n2 = first.shape[-1], second.shape[-1]
    ranks = stats.rankdata(np.concatenate([first, second], axis=-1), axis=-1)
    u = ranks[..., :n1].sum(axis=-1) - n1 * (n1 + 1) / 2
    return 2 * u / (n1 * n2) - 1


def rank_difference(first, second, confidence=0.95, *, resamples=1999, seed=20261002):
    first, second = _samples(first, second, confidence)
    if type(resamples) is not int or not 999 <= resamples <= 19999:
        raise ValueError("Rank BCa requires a prespecified 999..19999 resamples.")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Rank BCa requires a prespecified unsigned 32-bit seed.")
    n1, n2 = len(first), len(second)
    ties = len(np.unique(np.concatenate([first, second]))) < n1 + n2
    p_method = "exact" if min(n1, n2) <= 8 and not ties else "asymptotic"
    test = stats.mannwhitneyu(
        first, second, alternative="two-sided", method=p_method, use_continuity=True
    )
    effect = float(2 * test.statistic / (n1 * n2) - 1)
    # Analytic delete-one influences avoid O(n²) jackknife sample construction.
    # Each independent sample's influence is scaled by its own sample size.
    a, b = np.sort(first), np.sort(second)
    influence_a = (
        np.searchsorted(b, first, side="left") + np.searchsorted(b, first, side="right") - n2
    ) / n2 - effect
    influence_b = (
        n1 - np.searchsorted(a, second, side="left") - np.searchsorted(a, second, side="right")
    ) / n1 - effect
    influences = (influence_a, influence_b)
    variance_term = sum(np.sum(u**2) / len(u) ** 2 for u in influences)
    acceleration = (
        (sum(np.sum(u**3) / len(u) ** 3 for u in influences) / (6 * variance_term**1.5))
        if variance_term > 0
        else None
    )
    method = "Independent-group BCa bootstrap of signed rank-biserial correlation"
    batch = max(1, min(64, 1_000_000 // (n1 + n2)))
    result = {
        "p_value": float(test.pvalue),
        "statistic": float(test.statistic),
        "test": f"two-sided Mann–Whitney {p_method}"
        + ("; tie and continuity correction" if p_method == "asymptotic" else ""),
        "definition": "P(first > second) - P(first < second); no median-difference or location-shift estimate",
        "resampling": {
            "seed": seed,
            "generator": "NumPy PCG64",
            "requested": resamples,
            "completed": 0,
            "batch": batch,
            "acceleration": None if acceleration is None else float(acceleration),
        },
        "warnings": [
            "The rank interval and Mann–Whitney p-value use different procedures; interval inclusion of zero does not invert this p-value. Small tied samples may need a specified permutation test."
        ],
    }
    if acceleration is None:
        result["effect"] = interval(
            effect,
            None,
            confidence,
            method,
            "Degenerate empirical influence; no BCa interval can be estimated. A constant or completely separated sample does not prove population certainty.",
        )
        return result
    rng = np.random.default_rng(seed)
    distribution = []
    for start in range(0, resamples, batch):
        size = min(batch, resamples - start)
        x = first[rng.integers(0, n1, size=(size, n1))]
        y = second[rng.integers(0, n2, size=(size, n2))]
        distribution.extend(rank_dominance(x, y).tolist())
    distribution = np.asarray(distribution)
    percentile = float(((distribution < effect).mean() + (distribution <= effect).mean()) / 2)
    result["resampling"].update(
        {
            "completed": resamples,
            "distribution_sha256": hashlib.sha256(distribution.astype("<f8").tobytes()).hexdigest(),
            "bias_percentile": percentile,
        }
    )
    if not 0 < percentile < 1:
        result["effect"] = interval(
            effect,
            None,
            confidence,
            method,
            "The bootstrap bias correction is nonfinite; no alternative interval was substituted.",
        )
        return result
    z0 = stats.norm.ppf(percentile)
    z = stats.norm.ppf([(1 - confidence) / 2, (1 + confidence) / 2])
    denominator = 1 - acceleration * (z0 + z)
    if np.any(denominator <= 0):
        result["effect"] = interval(
            effect,
            None,
            confidence,
            method,
            "BCa transformation crosses its pole; no alternative interval was substituted.",
        )
        return result
    quantiles = stats.norm.cdf(z0 + (z0 + z) / denominator)
    bounds = np.quantile(distribution, quantiles, method="linear")
    result["resampling"]["adjusted_quantiles"] = quantiles.tolist()
    result["effect"] = interval(effect, bounds, confidence, method)
    return result


def _counts(first_events, first_n, second_events, second_n, confidence):
    _confidence(confidence)
    if any(type(v) is not int for v in (first_events, first_n, second_events, second_n)):
        raise ValueError("Event counts and group denominators must be exact integers.")
    if (
        min(first_n, second_n) < 2
        or not 0 <= first_events <= first_n
        or not 0 <= second_events <= second_n
    ):
        raise ValueError("Each event count must fit its group denominator of at least two.")


def ratio_score(log_ratio, a, n1, c, n0):
    """Miettinen–Nurminen score squared, with constrained binomial MLEs.

    The stable quadratic root avoids cancellation at extreme candidate ratios.
    n/(n-1) variance correction is fixed and recorded; no pseudo-counts are used.
    """
    ratio = math.exp(log_ratio)
    total = n1 + n0
    coefficient = ratio * (n1 + c) + n0 + a
    discriminant = coefficient**2 - 4 * ratio * total * (a + c)
    # Tiny negative roundoff can occur at a double root (all events, ratio=1).
    if discriminant < -1e-12 * coefficient**2:
        raise ValueError("Invalid constrained binomial discriminant.")
    q = 2 * (a + c) / (coefficient + math.sqrt(max(0, discriminant)))
    p = ratio * q
    if not -1e-12 <= p <= 1 + 1e-12 or not -1e-12 <= q <= 1 + 1e-12:
        raise ValueError("The constrained event probabilities left their parameter space.")
    p, q = min(1, max(0, p)), min(1, max(0, q))
    numerator = a / n1 - ratio * c / n0
    variance = (p * (1 - p) / n1 + ratio**2 * q * (1 - q) / n0) * total / (total - 1)
    if variance == 0:
        return 0.0 if numerator == 0 else float("inf")
    return numerator**2 / variance


def probability_ratio(a, n1, c, n0, confidence=0.95):
    _counts(a, n1, c, n0, confidence)
    method = "Miettinen–Nurminen score inversion; n/(n-1) variance correction"
    if a == c == 0:
        return interval(
            float("nan"),
            (0, float("inf")),
            confidence,
            method,
            "No events in either sample: the proportion ratio is undefined; the score acceptance set is the entire nonnegative parameter space.",
        )
    estimate = (a / n1) / (c / n0) if c else float("inf")
    critical = stats.chi2.ppf(confidence, 1)
    center = math.log(estimate) if a and c else (-40 if a == 0 else 40)

    def objective(value):
        return ratio_score(value, a, n1, c, n0) - critical

    bounds = []
    for side, boundary in [(-1, a == 0), (1, c == 0)]:
        if boundary:
            bounds.append(0 if side == -1 else float("inf"))
            continue
        edge = center + side
        while objective(edge) <= 0 and abs(edge) < 80:
            edge += side
        if objective(edge) <= 0:
            raise ValueError(
                "Score interval root could not be bracketed; no infinite bound was fabricated."
            )
        low, high = sorted((center, edge))
        bounds.append(math.exp(optimize.brentq(objective, low, high, xtol=1e-12)))
    return interval(estimate, bounds, confidence, method)


def binary_comparison(a, n1, c, n0, confidence=0.95, *, probabilities_identified=True):
    _counts(a, n1, c, n0, confidence)
    if type(probabilities_identified) is not bool:
        raise ValueError("Declare whether the sampling design identifies event probabilities.")
    alpha = 1 - confidence
    table = np.array([[a, n1 - a], [c, n0 - c]])
    conditional = odds_ratio(table, kind="conditional")
    exact_ci = conditional.confidence_interval(confidence_level=confidence)
    difference = (
        confint_proportions_2indep(a, n1, c, n0, compare="diff", method="newcomb", alpha=alpha)
        if probabilities_identified
        else None
    )
    proportions = []
    for count, total in ((a, n1), (c, n0)) if probabilities_identified else []:
        proportions.append(
            {
                "events": count,
                "n": total,
                **interval(
                    count / total,
                    proportion_confint(count, total, method="wilson", alpha=alpha),
                    confidence,
                    "Wilson score",
                ),
            }
        )
    effects = {
        "odds_ratio": interval(
            conditional.statistic,
            tuple(exact_ci),
            confidence,
            "Conditional MLE odds ratio; central exact conditional interval",
            "A zero outcome margin leaves the conditional odds ratio undefined."
            if math.isnan(conditional.statistic)
            else None,
        ),
    }
    if probabilities_identified:
        effects.update(
            {
                "proportion_difference": interval(
                    a / n1 - c / n0, difference, confidence, "Newcombe independent Wilson intervals"
                ),
                "proportion_ratio": probability_ratio(a, n1, c, n0, confidence),
            }
        )
    return {
        "table": table.tolist(),
        "table_order": "rows: first, second; columns: event, non-event",
        "group_proportions": proportions,
        "effects": effects,
        "probabilities_identified": probabilities_identified,
        "p_value": float(stats.fisher_exact(table, alternative="two-sided").pvalue),
        "test": "two-sided Fisher exact; probability ordering at fixed margins",
        "warnings": [
            "Pointwise intervals are not multiplicity-adjusted. The central exact OR interval is not the inversion of the probability-ordered two-sided Fisher p-value; RD and RR use separate interval procedures. Case-control samples do not identify population event probabilities or their difference/ratio."
        ],
    }
