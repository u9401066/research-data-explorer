"""Independent comparison intervals: boundary estimates and numerical references."""

import json
from pathlib import Path
import hashlib

import numpy as np
import pytest
from scipy import stats
from statsmodels.stats.proportion import confint_proportions_2indep

from rde.infrastructure.clinical.comparison_estimates import (
    binary_comparison,
    probability_ratio,
    rank_difference,
    ratio_score,
    welch_difference,
)

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures/comparison-intervals/reference.json").read_text()
)


def decoded(number):
    return {
        "positive_infinity": float("inf"),
        "negative_infinity": -float("inf"),
        "undefined": float("nan"),
    }.get(number["status"], number["value"])


def test_welch_keeps_direction_and_unequal_variance_df_and_rejects_false_certainty():
    a, b = [1, 3, 6, 7, 8], [1, 1, 2, 2, 2, 3, 5, 15, 20]
    result = welch_difference(a, b, 0.99)
    reference = stats.ttest_ind(a, b, equal_var=False)
    assert result["p_value"] == pytest.approx(reference.pvalue)
    assert result["degrees_of_freedom"] == pytest.approx(reference.df)
    assert [decoded(result["effect"][k]) for k in ("lower", "upper")] == pytest.approx(
        tuple(reference.confidence_interval(0.99))
    )
    reverse = welch_difference(b, a, 0.99)
    assert decoded(reverse["effect"]["lower"]) == pytest.approx(-decoded(result["effect"]["upper"]))
    constant = welch_difference([1, 1], [3, 3])
    assert decoded(constant["effect"]["estimate"]) == -2
    assert constant["effect"]["status"] == "unavailable" and constant["p_value"] is None
    json.dumps(constant, allow_nan=False)


def test_analytic_two_sample_bca_matches_scipy_delete_one_jackknife():
    first = np.array([1, 1, 2, 3, 5, 8, 13, 21])
    second = np.array([1, 2, 2, 4, 6, 9, 12, 19, 30, 32, 35])

    def direct_pairs(a, b):
        # Independent brute-force statistic; SciPy explicitly constructs the
        # delete-one samples, rather than the engine's sorted influences.
        # Count pairs before division so equal discrete statistics remain exact
        # floating-point ties in the BCa bias percentile.
        return (2 * np.count_nonzero(a[:, None] > b) + np.count_nonzero(a[:, None] == b)) / (
            len(a) * len(b)
        ) - 1

    result = rank_difference(first, second, 0.9, resamples=999, seed=382)
    reference = stats.bootstrap(
        (first, second),
        direct_pairs,
        confidence_level=0.9,
        n_resamples=999,
        vectorized=False,
        paired=False,
        batch=64,
        method="BCa",
        random_state=np.random.default_rng(382),
    )
    assert decoded(result["effect"]["estimate"]) == pytest.approx(direct_pairs(first, second))
    assert [decoded(result["effect"][k]) for k in ("lower", "upper")] == pytest.approx(
        tuple(reference.confidence_interval), abs=1e-12
    )
    assert result == rank_difference(first, second, 0.9, resamples=999, seed=382)
    assert result["resampling"]["completed"] == 999
    assert -1 <= decoded(result["effect"]["lower"]) < decoded(result["effect"]["upper"]) <= 1


@pytest.mark.parametrize("a,b", [([1, 1], [1, 1]), ([3, 3, 4], [1, 1, 2])])
def test_rank_degenerate_support_does_not_draw_a_spurious_zero_width_ci(a, b):
    result = rank_difference(a, b)
    assert result["effect"]["status"] == "unavailable"
    assert result["resampling"]["completed"] == 0
    assert result["effect"]["estimate"]["status"] == "finite"
    json.dumps(result, allow_nan=False)


def test_all_events_score_interval_contains_one_and_has_analytic_bounds():
    for n1, n0 in [(2, 2), (10, 10), (13, 21), (100, 300)]:
        actual = probability_ratio(n1, n1, n0, n0)
        critical = stats.chi2.ppf(0.95, 1) * (n1 + n0) / (n1 + n0 - 1)
        assert decoded(actual["lower"]) == pytest.approx(1 / (1 + critical / n1))
        assert decoded(actual["upper"]) == pytest.approx(1 + critical / n0)
        assert decoded(actual["lower"]) < 1 < decoded(actual["upper"])


def test_ratio_score_matches_regular_library_intervals_and_reciprocal_boundaries():
    cases = [
        (8, 10, 1, 6),
        (1, 100, 4, 13),
        (9, 13, 2, 100),
        (0, 10, 2, 10),
        (2, 10, 0, 10),
        (10, 10, 2, 10),
    ]
    for a, n1, c, n0 in cases:
        actual = probability_ratio(a, n1, c, n0)
        reverse = probability_ratio(c, n0, a, n1)
        low, high = (decoded(actual[k]) for k in ("lower", "upper"))
        if a and c:
            reference = confint_proportions_2indep(a, n1, c, n0, compare="ratio", method="score")
            assert [low, high] == pytest.approx(reference, abs=1e-8)
        assert decoded(reverse["lower"]) == pytest.approx(1 / high)
        assert decoded(reverse["upper"]) == pytest.approx(1 / low if low else float("inf"))
        for bound in (low, high):
            if bound and np.isfinite(bound):
                assert ratio_score(np.log(bound), a, n1, c, n0) == pytest.approx(
                    stats.chi2.ppf(0.95, 1), abs=1e-7
                )
        json.dumps(actual, allow_nan=False)


def test_binary_zero_cells_preserve_undefined_point_and_unbounded_interval():
    none = binary_comparison(0, 10, 0, 10)
    assert none["effects"]["proportion_difference"]["estimate"]["value"] == 0
    for key in ("proportion_ratio", "odds_ratio"):
        assert none["effects"][key]["estimate"]["status"] == "undefined"
        assert none["effects"][key]["lower"]["value"] == 0
        assert none["effects"][key]["upper"]["status"] == "positive_infinity"
    zero = binary_comparison(0, 10, 2, 10)
    infinite = binary_comparison(2, 10, 0, 10)
    assert zero["effects"]["odds_ratio"]["estimate"]["value"] == 0
    assert infinite["effects"]["odds_ratio"]["estimate"]["status"] == "positive_infinity"
    assert infinite["effects"]["odds_ratio"]["upper"]["status"] == "positive_infinity"
    for result in (none, zero, infinite):
        assert 0 <= result["p_value"] <= 1
        json.dumps(result, allow_nan=False)


def test_invalid_counts_and_samples_fail_before_resampling():
    for values in [(1.5, 10, 2, 10), (True, 10, 2, 10), (11, 10, 2, 10), (0, 0, 2, 10)]:
        with pytest.raises(ValueError):
            binary_comparison(*values)
    for values in [([1, float("inf")], [2, 3]), ([1], [2, 3])]:
        with pytest.raises(ValueError):
            rank_difference(*values)


@pytest.mark.parametrize("reference", REFERENCE["cases"])
def test_binary_intervals_match_independent_r_likelihood_and_conditional_enumeration(reference):
    actual = binary_comparison(*reference["counts"], confidence=REFERENCE["confidence"])
    assert actual["p_value"] == pytest.approx(reference["fisher_p"], abs=1e-13)
    rd = actual["effects"]["proportion_difference"]
    assert [decoded(rd[k]) for k in ("lower", "upper")] == pytest.approx(
        reference["proportion_difference"], abs=1e-12
    )
    for name in ("proportion_ratio", "odds_ratio"):
        for field, expected in reference[name].items():
            number = actual["effects"][name][field]
            assert number["status"] == expected["status"]
            if number["status"] == "finite":
                # R's RR reference numerically maximizes the binomial likelihood,
                # independently of the constrained closed-form Python solver.
                tolerance = 2e-6 if name == "proportion_ratio" else 1e-10
                assert number["value"] == pytest.approx(expected["value"], rel=tolerance, abs=1e-10)


def test_reference_script_identity_and_r_welch_values_are_retained():
    script = Path(__file__).parent / "fixtures/comparison-intervals/reference.R"
    assert (
        hashlib.sha256(script.read_bytes()).hexdigest() == REFERENCE["provenance"]["script_sha256"]
    )
    actual = welch_difference([1, 3, 6, 7, 8], [1, 1, 2, 2, 2, 3, 5, 15, 20], 0.99)
    expected = REFERENCE["welch"]
    assert actual["p_value"] == pytest.approx(expected["p"], abs=1e-13)
    assert actual["degrees_of_freedom"] == pytest.approx(expected["df"], abs=1e-12)
    assert [decoded(actual["effect"][k]) for k in ("lower", "upper")] == pytest.approx(
        expected["ci"], abs=1e-11
    )


@pytest.mark.parametrize("scale", [1e-150, 1e150])
def test_welch_degrees_of_freedom_do_not_square_overflow_or_underflow(scale):
    a, b = np.array([1, 2, 4, 9]), np.array([0, 2, 3, 5, 6, 8])
    base = welch_difference(a, b)
    scaled = welch_difference(a * scale, b * scale)
    assert scaled["degrees_of_freedom"] == pytest.approx(base["degrees_of_freedom"])
    assert scaled["p_value"] == pytest.approx(base["p_value"])
    assert scaled["effect"]["lower"]["value"] / scale == pytest.approx(
        base["effect"]["lower"]["value"]
    )
    json.dumps(scaled, allow_nan=False)
