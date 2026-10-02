"""Independent references for paired effects, ties, zeros and subject resampling."""

import itertools
import json

import numpy as np
import pytest
from scipy import stats

from rde.infrastructure.clinical.repeated_estimates import (
    friedman,
    friedman_w,
    paired_mean,
    signed_rank,
    signed_rank_effect,
    signed_rank_jackknife,
)


def reference_rank(delta):
    values = np.asarray(delta)
    values = values[values != 0]
    if not len(values):
        return float("nan")
    # Pairwise comparisons independently construct tied midranks.
    ranks = np.array(
        [
            1 + np.sum(np.abs(values) < abs(x)) + (np.sum(np.abs(values) == abs(x)) - 1) / 2
            for x in values
        ]
    )
    return np.sum(np.sign(values) * ranks) / (len(values) * (len(values) + 1) / 2)


@pytest.mark.parametrize(
    "delta",
    [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 2],
        [0, 2, -2, 3, -4],
        [1, 1, -1, 2, -2, 3, 0, 0],
        [1, 2, 3, 4, 5],
    ],
)
def test_analytic_jackknife_matches_independent_delete_one_with_ties_and_zeros(delta):
    delta = np.array(delta, dtype=float)
    expected = [reference_rank(np.delete(delta, i)) for i in range(len(delta))]
    np.testing.assert_allclose(signed_rank_jackknife(delta), expected, atol=1e-15)
    np.testing.assert_allclose(signed_rank_effect(delta), reference_rank(delta), atol=1e-15)


@pytest.mark.parametrize(
    "delta",
    [
        [0, 2, -2, 3, -4],
        [1, 1, -1, 2, -2, 3, 0, 0],
        [1, 2, 3, 4, 5],
    ],
)
def test_conditional_exact_p_matches_exhaustive_sign_assignments(delta):
    delta = np.array(delta, dtype=float)
    nonzero = delta[delta != 0]
    ranks = stats.rankdata(abs(nonzero))
    observed = min(ranks[nonzero > 0].sum(), ranks[nonzero < 0].sum())
    distribution = [
        min(ranks[np.array(signs) > 0].sum(), ranks[np.array(signs) < 0].sum())
        for signs in itertools.product([-1, 1], repeat=len(nonzero))
    ]
    expected = np.mean(np.array(distribution) <= observed)
    actual = signed_rank(delta, np.zeros(len(delta)), resamples=999, seed=18)
    reverse = signed_rank(np.zeros(len(delta)), delta, resamples=999, seed=18)
    assert actual["p_value"] == pytest.approx(expected, abs=1e-15)
    assert actual["p_value"] == reverse["p_value"]
    assert actual["effect"]["estimate"]["value"] == -reverse["effect"]["estimate"]["value"]
    assert actual["zero_difference_pairs"] == np.sum(delta == 0)
    assert actual["nonzero_pairs"] == len(nonzero)
    json.dumps(actual, allow_nan=False)


def test_paired_bca_matches_scipy_subject_delete_one_resampling():
    delta = np.array([0, 1, -1, 2, 3, -4, -5, 8, 10, -11, 13, -15, 16, 17, -20, 22])
    actual = signed_rank(delta, np.zeros(len(delta)), 0.9, resamples=999, seed=831)
    reference = stats.bootstrap(
        (delta,),
        reference_rank,
        vectorized=False,
        n_resamples=999,
        batch=64,
        confidence_level=0.9,
        method="BCa",
        random_state=np.random.default_rng(831),
    )
    assert actual["effect"]["status"] == "available"
    assert [actual["effect"][k]["value"] for k in ("lower", "upper")] == pytest.approx(
        tuple(reference.confidence_interval), abs=1e-12
    )
    assert actual == signed_rank(delta, np.zeros(len(delta)), 0.9, resamples=999, seed=831)
    assert actual["resampling"]["completed"] == 999


def test_large_signed_rank_tied_variance_matches_scipy_wilcox_approximation():
    delta = np.tile([0, -1, 1, 2, -2, 3, 4, -5], 12)
    result = signed_rank(delta, np.zeros(len(delta)), resamples=999)
    expected = stats.wilcoxon(delta, zero_method="wilcox", correction=False, method="approx")
    assert result["p_value"] == pytest.approx(expected.pvalue, abs=1e-14)
    assert result["statistic"] == expected.statistic
    assert result["p_value_method"].startswith("normal approximation")


@pytest.mark.parametrize("delta", [[0] * 8, [1] * 8, [0] * 7 + [1], [0] * 6 + [1, -2]])
def test_degenerate_rank_support_never_fabricates_population_certainty(delta):
    result = signed_rank(delta, np.zeros(len(delta)), resamples=999, seed=981)
    assert result["effect"]["status"] == "unavailable"
    assert result["effect"]["lower"]["status"] == "undefined"
    if not any(delta):
        assert result["p_value"] is None
        assert result["effect"]["estimate"]["status"] == "undefined"
    if result["resampling"]["completed"]:
        assert result["resampling"]["undefined_resamples"] > 0
    json.dumps(result, allow_nan=False)


def test_paired_mean_direction_and_interval_match_direct_t_test():
    a, b = np.array([3, 5, 7, 9, 11, 14, 15]), np.array([2, 4, 9, 7, 12, 10, 11])
    actual = paired_mean(a, b, 0.99)
    expected = stats.ttest_rel(a, b)
    assert actual["p_value"] == pytest.approx(expected.pvalue)
    assert actual["statistic"] == pytest.approx(expected.statistic)
    assert [actual["effect"][k]["value"] for k in ("lower", "upper")] == pytest.approx(
        tuple(expected.confidence_interval(0.99))
    )
    reverse = paired_mean(b, a, 0.99)
    assert reverse["effect"]["lower"]["value"] == pytest.approx(-actual["effect"]["upper"]["value"])
    for scale in [1e-150, 1e150]:
        scaled = paired_mean(a * scale, b * scale, 0.99)
        assert scaled["p_value"] == pytest.approx(actual["p_value"])
        assert scaled["effect"]["lower"]["value"] / scale == pytest.approx(
            actual["effect"]["lower"]["value"]
        )


@pytest.mark.parametrize("delta", [0, 2, -3])
def test_constant_difference_mean_ci_and_p_remain_unavailable(delta):
    actual = paired_mean(np.arange(8) + delta, np.arange(8))
    assert actual["effect"]["estimate"]["value"] == delta
    assert actual["effect"]["status"] == "unavailable"
    assert actual["p_value"] is None
    json.dumps(actual, allow_nan=False)


def test_invalid_paired_inputs_fail_before_inference():
    for first, second in [
        ([1] * 4, [2] * 4),
        ([1] * 5, [2] * 6),
        ([float("nan")] * 5, [1] * 5),
        ([1e308] * 5, [-1e308] * 5),
    ]:
        for method in [paired_mean, signed_rank]:
            with pytest.raises(ValueError):
                method(first, second)


def test_friedman_ties_and_subject_vector_bca_match_independent_reference():
    matrix = np.random.default_rng(178).integers(0, 9, size=(18, 4))
    actual = friedman(matrix, 0.9, resamples=999, seed=927)
    expected = stats.friedmanchisquare(*matrix.T)
    assert actual["statistic"] == pytest.approx(expected.statistic)
    assert actual["p_value"] == pytest.approx(expected.pvalue)
    assert actual["effect"]["estimate"]["value"] == pytest.approx(expected.statistic / (18 * 3))

    def reference_w(indices):
        sampled = matrix[indices.astype(int)]
        return stats.friedmanchisquare(*sampled.T).statistic / (
            len(indices) * (matrix.shape[1] - 1)
        )

    reference = stats.bootstrap(
        (np.arange(len(matrix)),),
        reference_w,
        vectorized=False,
        n_resamples=999,
        batch=64,
        confidence_level=0.9,
        method="BCa",
        random_state=np.random.default_rng(927),
    )
    assert actual["effect"]["status"] == "available"
    # Different floating-point formulas can perturb exact distribution ties.
    # Compare the SciPy reference after quantifying their effect, not by rounding
    # the original source measurements.
    assert [actual["effect"][k]["value"] for k in ("lower", "upper")] == pytest.approx(
        tuple(reference.confidence_interval), abs=1e-12
    )
    centered = stats.rankdata(matrix, axis=1) - 2.5
    assert friedman_w(centered) == pytest.approx(reference_w(np.arange(len(matrix))))
    json.dumps(actual, allow_nan=False)


def test_friedman_all_tied_subject_vectors_have_no_inference():
    result = friedman(np.tile(np.arange(10)[:, None], (1, 3)), resamples=999)
    assert result["p_value"] is None and result["statistic"] is None
    assert result["effect"]["status"] == "unavailable"
    assert result["effect"]["estimate"]["status"] == "undefined"
    json.dumps(result, allow_nan=False)
