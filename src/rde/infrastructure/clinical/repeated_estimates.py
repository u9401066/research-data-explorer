"""Paired t and signed-rank effects; resampling always preserves subject pairing."""

import hashlib
import math

import numpy as np
from scipy import stats

from .comparison_estimates import interval, _confidence


def differences(first, second, confidence):
    _confidence(confidence)
    x, y = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if (
        x.ndim != 1
        or x.shape != y.shape
        or len(x) < 5
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
    ):
        raise ValueError("At least five finite, explicitly paired subjects are required.")
    with np.errstate(over="raise", invalid="raise"):
        try:
            return x - y
        except FloatingPointError as error:
            raise ValueError(
                "Paired subtraction exceeds finite arithmetic; review source units."
            ) from error


def paired_mean(first, second, confidence=0.95):
    delta = differences(first, second, confidence)
    n = len(delta)
    scale = float(np.max(np.abs(delta))) or 1.0
    scaled = delta / scale
    mean = float(np.mean(scaled) * scale)
    se = float(np.std(scaled, ddof=1) / math.sqrt(n) * scale)
    result = {
        "statistic": None,
        "p_value": None,
        "test": "two-sided paired Student t",
        "degrees_of_freedom": n - 1,
        "standard_error": se if math.isfinite(se) else None,
    }
    method = "Paired mean-difference Student t interval; subject-level differences"
    if se <= 0 or not math.isfinite(se):
        result["effect"] = interval(
            mean,
            None,
            confidence,
            method,
            "No finite positive difference variance; no zero-width population interval is substituted.",
        )
        return result
    statistic = mean / se
    bound = float(stats.t.ppf((1 + confidence) / 2, n - 1) * se)
    if (
        not math.isfinite(statistic)
        or not math.isfinite(bound)
        or not all(math.isfinite(v) for v in (mean - bound, mean + bound))
    ):
        raise ValueError("Paired inference exceeds finite arithmetic; review source scale.")
    result.update(
        statistic=statistic,
        p_value=float(2 * stats.t.sf(abs(statistic), n - 1)),
        effect=interval(mean, (mean - bound, mean + bound), confidence, method),
    )
    return result


def signed_rank_effect(delta, axis=-1):
    """Matched rank-biserial (positive rank sum - negative rank sum) / total.

    Zero differences are excluded from ranks and denominator (wilcox). With no
    nonzero differences the estimand is undefined, not an estimated exact zero.
    """
    delta = np.moveaxis(np.asarray(delta), axis, -1)
    zero = np.sum(delta == 0, axis=-1, keepdims=True)
    ranks = stats.rankdata(np.abs(delta), axis=-1) - zero
    m = delta.shape[-1] - zero[..., 0]
    numerator = np.sum(np.sign(delta) * ranks, axis=-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return numerator / (m * (m + 1) / 2)


def signed_rank_jackknife(delta):
    """Exact delete-one values in O(n log n), including zero differences."""
    nonzero = delta != 0
    values = delta[nonzero]
    m = len(values)
    estimate = float(signed_rank_effect(delta))
    answer = np.full(len(delta), estimate)
    if m < 2:
        answer[nonzero] = np.nan
        return answer
    absolute, signs = np.abs(values), np.sign(values)
    order = np.argsort(absolute, kind="stable")
    sorted_abs, sorted_signs = absolute[order], signs[order]
    left = np.searchsorted(sorted_abs, absolute, side="left")
    right = np.searchsorted(sorted_abs, absolute, side="right")
    prefix = np.concatenate(([0.0], np.cumsum(sorted_signs)))
    ranks = (left + right + 1) / 2
    numerator = np.sum(signs * ranks)
    removed_peer_weight = prefix[-1] - prefix[right] + 0.5 * (prefix[right] - prefix[left] - signs)
    answer[nonzero] = (numerator - signs * ranks - removed_peer_weight) / ((m - 1) * m / 2)
    return answer


def subject_bca(data, statistic, jackknife, confidence, *, resamples, seed, method):
    """One independent subject is a resampling unit, regardless of occasion count."""
    _confidence(confidence)
    if (
        type(resamples) is not int
        or not 999 <= resamples <= 19999
        or type(seed) is not int
        or not 0 <= seed < 2**32
    ):
        raise ValueError("Subject BCa requires 999..19999 draws and an unsigned 32-bit seed.")
    data = np.asarray(data)
    estimate = float(statistic(data))
    batch = max(1, min(64, 1_000_000 // data.size))
    receipt = {
        "seed": seed,
        "generator": "NumPy PCG64",
        "requested": resamples,
        "completed": 0,
        "batch": batch,
        "resampling_unit": "independent subject with paired measurements retained",
    }

    def unavailable(reason):
        return interval(estimate, None, confidence, method, reason), receipt

    if not math.isfinite(estimate) or not np.isfinite(jackknife).all():
        return unavailable(
            "The statistic or a subject delete-one value is undefined; no alternative interval is substituted."
        )
    influences = np.mean(jackknife) - jackknife
    square = np.sum(influences**2)
    if np.ptp(jackknife) == 0 or square <= 0:
        return unavailable(
            "Degenerate empirical subject influence; no BCa interval. A constant sample does not prove population certainty."
        )
    acceleration = float(np.sum(influences**3) / (6 * square**1.5))
    receipt["acceleration"] = acceleration
    rng = np.random.default_rng(seed)
    distribution = np.empty(resamples)
    for start in range(0, resamples, batch):
        size = min(batch, resamples - start)
        indices = rng.integers(0, len(data), size=(size, len(data)))
        distribution[start : start + size] = statistic(data[indices])
    receipt.update(
        completed=resamples,
        distribution_sha256=hashlib.sha256(distribution.astype("<f8").tobytes()).hexdigest(),
        undefined_resamples=int((~np.isfinite(distribution)).sum()),
    )
    if not np.isfinite(distribution).all():
        return unavailable(
            "Some subject resamples have an undefined statistic; none were discarded and no replacement interval was substituted."
        )
    if np.ptp(distribution) == 0:
        return unavailable(
            "All requested subject resamples have the same statistic; no zero-width population interval is substituted."
        )
    percentile = float(((distribution < estimate).mean() + (distribution <= estimate).mean()) / 2)
    receipt["bias_percentile"] = percentile
    if not 0 < percentile < 1:
        return unavailable(
            "Bootstrap bias correction is nonfinite; no alternative interval was substituted."
        )
    z0 = stats.norm.ppf(percentile)
    z = stats.norm.ppf([(1 - confidence) / 2, (1 + confidence) / 2])
    denominator = 1 - acceleration * (z0 + z)
    if np.any(denominator <= 0):
        return unavailable(
            "BCa transformation crosses its pole; no alternative interval was substituted."
        )
    quantiles = stats.norm.cdf(z0 + (z0 + z) / denominator)
    receipt["adjusted_quantiles"] = quantiles.tolist()
    return interval(
        estimate, np.quantile(distribution, quantiles, method="linear"), confidence, method
    ), receipt


def signed_rank(first, second, confidence=0.95, *, resamples=1999, seed=20261002):
    delta = differences(first, second, confidence)
    values = delta[delta != 0]
    ranks = stats.rankdata(np.abs(values))
    plus, minus = float(ranks[values > 0].sum()), float(ranks[values < 0].sum())
    m = len(values)
    test = "two-sided Wilcoxon signed-rank; wilcox zeros; no continuity correction"
    if not m:
        p = None
        method = "undefined: no nonzero signed ranks"
    elif m <= 50:
        # Conditional exact sign-flip distribution, including tied midranks.
        # Multiplying by two retains every half-rank as an exact integer.
        weights = np.rint(2 * ranks).astype(int)
        counts = [1]
        for weight in weights:
            updated = counts + [0] * int(weight)
            for i, count in enumerate(counts):
                updated[i + int(weight)] += count
            counts = updated
        p = min(1.0, 2 * sum(counts[: round(2 * min(plus, minus)) + 1]) / 2**m)
        method = "exact conditional sign flips; tied ranks retained; at most 50 nonzero pairs"
    else:
        z = (plus - ranks.sum() / 2) / math.sqrt(float(np.sum(ranks * ranks) / 4))
        p = float(2 * stats.norm.sf(abs(z)))
        method = "normal approximation with tied-rank variance; more than 50 nonzero pairs"
    effect, resampling = subject_bca(
        delta,
        signed_rank_effect,
        signed_rank_jackknife(delta),
        confidence,
        resamples=resamples,
        seed=seed,
        method="Subject-paired BCa interval of matched rank-biserial correlation",
    )
    return {
        "statistic": min(plus, minus) if m else None,
        "p_value": p,
        "test": test,
        "p_value_method": method,
        "effect": effect,
        "resampling": resampling,
        "nonzero_pairs": m,
        "zero_difference_pairs": len(delta) - m,
        "positive_rank_sum": plus,
        "negative_rank_sum": minus,
        "definition": "(positive signed-rank sum - negative signed-rank sum) / total nonzero rank sum; first minus second. Not independent-group dominance or a median-difference estimate.",
        "warnings": [
            "Paired BCa and the signed-rank p-value use different inference; interval inclusion of zero does not invert the test. Zero differences are excluded from ranks, retained as subjects in resampling; no implicit rounding of source differences."
        ],
    }


def friedman_w(centered_ranks):
    summed = np.sum(centered_ranks, axis=-2)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.sum(summed * summed, axis=-1) / (
            centered_ranks.shape[-2] * np.sum(centered_ranks * centered_ranks, axis=(-2, -1))
        )


def friedman(matrix, confidence=0.95, *, resamples=1999, seed=20261002):
    matrix = np.asarray(matrix, dtype=float)
    if (
        matrix.ndim != 2
        or matrix.shape[0] < 5
        or matrix.shape[1] < 3
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("Friedman requires at least five complete subjects and three occasions.")
    n, k = matrix.shape
    centered = stats.rankdata(matrix, axis=1) - (k + 1) / 2
    estimate = float(friedman_w(centered))
    total = centered.sum(axis=0)
    squares = np.sum(centered * centered)
    with np.errstate(divide="ignore", invalid="ignore"):
        jackknife = np.sum((total - centered) ** 2, axis=1) / (
            (n - 1) * (squares - np.sum(centered * centered, axis=1))
        )
    effect, resampling = subject_bca(
        centered,
        friedman_w,
        jackknife,
        confidence,
        resamples=resamples,
        seed=seed,
        method="Subject-vector BCa interval of tie-corrected Kendall concordance W",
    )
    statistic = n * (k - 1) * estimate if math.isfinite(estimate) else None
    return {
        "statistic": statistic,
        "p_value": float(stats.chi2.sf(statistic, k - 1)) if statistic is not None else None,
        "test": "Friedman tie-corrected chi-square approximation",
        "degrees_of_freedom": k - 1,
        "effect": effect,
        "resampling": resampling,
        "warnings": [
            "The chi-square approximation can be inaccurate with at most 10 subjects or at most 6 occasions."
        ]
        if n <= 10 or k <= 6
        else [],
    }
