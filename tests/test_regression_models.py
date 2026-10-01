"""Synthetic estimator checks against equations and coding/unit invariants.

Public clinical data are exercised separately through the actual MCP workflow.
"""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import nbinom, t

from rde.infrastructure.clinical.regression import run_regression
from rde.infrastructure.clinical.regression_contract import RegressionSpec
from rde.infrastructure.clinical.survival import digest


def study(**updates):
    return RegressionSpec.parse(
        dict(
            outcome="y",
            outcome_unit="original source unit",
            context="Synthetic independent-case numerical boundary checks only",
            independent_rows=True,
            study_design="cross_sectional",
            distribution="gaussian",
            subject="id",
            predictors=[
                dict(
                    column="x",
                    kind="continuous",
                    label="Synthetic exposure",
                    unit="unit",
                    reference=0,
                    increment=1,
                    knots=[],
                ),
                dict(
                    column="group",
                    kind="categorical",
                    label="Synthetic group",
                    reference="A",
                    levels=["A", "B"],
                ),
            ],
        )
        | updates
    )


def observations():
    rng = np.random.default_rng(736025)
    n = 480
    x = rng.uniform(-2, 2, n)
    group = np.arange(n) % 2
    exposure = np.exp(rng.normal(0, 0.4, n))
    linear = 0.3 + 0.35 * x + 0.45 * group
    mu = exposure * np.exp(linear)
    latent = linear + rng.logistic(size=n)
    return pd.DataFrame(
        dict(
            id=[f"synthetic-{i}" for i in range(n)],
            x=x,
            group=np.where(group, "B", "A"),
            exposure=exposure,
            gaussian=linear + rng.normal(size=n) * (0.5 + np.abs(x)),
            binary=rng.binomial(1, expit(linear)),
            poisson=rng.poisson(mu),
            negative_binomial=rng.negative_binomial(1 / 0.7, 1 / (1 + 0.7 * mu)),
            ordinal=np.array(["Low", "Middle", "High", "Highest"])[
                np.digitize(latent, [-0.8, 0.4, 1.5])
            ],
        )
    )


def source(distribution):
    return observations().rename(columns={distribution: "y"})


def test_gaussian_hc3_matches_closed_form_and_keeps_source_row_ledger():
    data = source("gaussian")
    data.loc[3, "x"] = np.nan
    data.loc[8, "y"] = np.nan
    result = run_regression(data, study())
    complete = data.dropna(subset=["x", "y"])
    matrix = np.column_stack([np.ones(len(complete)), complete.x, complete.group == "B"])
    inverse = np.linalg.inv(matrix.T @ matrix)
    beta = inverse @ matrix.T @ complete.y
    residual = complete.y.to_numpy() - matrix @ beta
    leverage = np.einsum("ij,jk,ik->i", matrix, inverse, matrix)
    meat = matrix.T @ np.diag((residual / (1 - leverage)) ** 2) @ matrix
    covariance = inverse @ meat @ inverse
    assert result["optimization_parameters"] == pytest.approx(beta, abs=1e-11)
    assert np.array(result["coefficient_covariance"]) == pytest.approx(covariance, abs=1e-11)
    critical = t.ppf(0.975, len(complete) - 3)
    for row, estimate, se in zip(result["coefficients"], beta, np.sqrt(covariance.diagonal())):
        assert row["lower"] == pytest.approx(estimate - critical * se)
        assert row["upper"] == pytest.approx(estimate + critical * se)
    assert result["case_ledger"]["missing_excluded_data_rows"] == [4, 9]
    assert [r["data_row"] for r in result["points"]] == (complete.index + 1).tolist()
    assert result["multiplicity"]["coefficient_family"] == ["x0_b0", "x1_l0"]
    assert result["coefficients"][0]["p_adjusted"] is None
    assert all(r["p_adjusted"] >= r["p_value"] for r in result["coefficients"][1:])
    assert result["receipt_sha256"] == digest(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    )


def test_binary_group_odds_match_two_by_two_table_and_reverse_outcome_coding():
    data = pd.DataFrame(
        dict(
            id=[f"case-{i}" for i in range(120)],
            group=["A"] * 60 + ["B"] * 60,
            y=[1] * 18 + [0] * 42 + [1] * 33 + [0] * 27,
        )
    )
    spec = study(
        distribution="binomial", outcome_levels=["0", "1"], predictors=[study().predictors[1]]
    )
    result = run_regression(data, spec)
    term = result["coefficients"][1]
    expected_log_or = np.log((33 / 27) / (18 / 42))
    expected_se = np.sqrt(1 / 33 + 1 / 27 + 1 / 18 + 1 / 42)
    assert term["coefficient"] == pytest.approx(expected_log_or)
    assert term["standard_error"] == pytest.approx(expected_se)
    assert result["points"][0]["fitted"] == pytest.approx(18 / 60)
    assert result["points"][-1]["fitted"] == pytest.approx(33 / 60)
    reverse = run_regression(data, replace(spec, outcome_levels=["1", "0"]))
    for left, right in zip(result["coefficients"], reverse["coefficients"]):
        assert left["coefficient"] == pytest.approx(-right["coefficient"], abs=1e-10)
        assert left["lower"] == pytest.approx(1 / right["upper"])
        assert left["p_value"] == pytest.approx(right["p_value"])
    assert [p["fitted"] for p in reverse["points"]] == pytest.approx(
        [1 - p["fitted"] for p in result["points"]]
    )


@pytest.mark.parametrize("quasi", [False, True])
def test_complete_and_quasi_complete_logistic_separation_are_rejected(quasi):
    x = np.resize([-1.0, 0.0, 0.0, 1.0] if quasi else [-1.0, -1.0, 1.0, 1.0], 80)
    data = pd.DataFrame(dict(id=np.arange(80), x=x, y=np.resize([0, 0, 1, 1], 80)))
    spec = study(
        distribution="binomial", outcome_levels=["0", "1"], predictors=study().predictors[:1]
    )
    with pytest.raises(ValueError, match="quasi-complete binary separation"):
        run_regression(data, spec)


@pytest.mark.parametrize("distribution", ["poisson", "negative_binomial"])
def test_count_offset_unit_change_preserves_counts_comparisons_and_dispersion(distribution):
    data = source(distribution)
    spec = study(distribution=distribution, exposure="exposure", exposure_unit="year")
    result = run_regression(data, spec)
    converted = data.copy()
    converted.exposure *= 12
    changed = run_regression(converted, replace(spec, exposure_unit="month"))
    assert changed["coefficients"][0]["coefficient"] == pytest.approx(
        result["coefficients"][0]["coefficient"] - np.log(12), abs=2e-6
    )
    for left, right in zip(result["coefficients"][1:], changed["coefficients"][1:]):
        assert left["estimate"] == pytest.approx(right["estimate"], rel=2e-6)
        assert left["lower"] == pytest.approx(right["lower"], rel=2e-6)
        assert left["effect_scale"] == "rate ratio"
    assert [p["fitted"] for p in result["points"]] == pytest.approx(
        [p["fitted"] for p in changed["points"]], rel=2e-6
    )
    if distribution == "negative_binomial":
        assert result["nuisance_parameters"][0]["estimate"] == pytest.approx(
            changed["nuisance_parameters"][0]["estimate"], rel=2e-6
        )
    no_offset = run_regression(data, replace(spec, exposure=None, exposure_unit=None))
    assert no_offset["coefficients"][1]["effect_scale"] == "mean count ratio"


@pytest.mark.parametrize("distribution", ["poisson", "negative_binomial"])
def test_zero_count_group_is_not_reported_as_a_finite_protective_association(distribution):
    data = pd.DataFrame(
        dict(
            id=np.arange(80),
            group=["A"] * 40 + ["B"] * 40,
            y=[0] * 40 + list(np.resize([0, 1, 2, 3], 40)),
        )
    )
    spec = study(distribution=distribution, predictors=[study().predictors[1]])
    with pytest.raises(ValueError, match="Count separation"):
        run_regression(data, spec)


def test_nb2_joint_dispersion_matches_independent_negative_binomial_likelihood():
    data = source("negative_binomial")
    result = run_regression(
        data, study(distribution="negative_binomial", exposure="exposure", exposure_unit="year")
    )
    matrix = np.column_stack([np.ones(len(data)), data.x, data.group == "B"])

    def nll(params):
        mu = data.exposure.to_numpy() * np.exp(matrix @ params[:3])
        size = np.exp(-params[3])
        return -nbinom.logpmf(data.y, size, size / (size + mu)).sum()

    reference = minimize(nll, [0.2, 0.2, 0.2, np.log(0.5)], method="BFGS", options={"gtol": 1e-5})
    assert reference.success, reference.message
    assert result["optimization_parameters"][:3] == pytest.approx(reference.x[:3], abs=2e-6)
    alpha = result["nuisance_parameters"][0]["estimate"]
    assert alpha == pytest.approx(np.exp(reference.x[3]), rel=2e-6)
    assert result["model"]["log_likelihood"] == pytest.approx(-reference.fun, abs=1e-8)
    for row in result["points"]:
        assert row["pearson_residual"] == pytest.approx(
            (row["observed"] - row["fitted"]) / np.sqrt(row["fitted"] + alpha * row["fitted"] ** 2)
        )
    assert result["model"]["total_parameters"] == 4


def test_ordinal_reversal_inverts_odds_and_cutpoints_without_treating_labels_as_numbers():
    data = source("ordinal")
    spec = study(distribution="ordinal", outcome_levels=["Low", "Middle", "High", "Highest"])
    result = run_regression(data, spec)
    reverse = run_regression(
        data, replace(spec, outcome_levels=list(reversed(spec.outcome_levels)))
    )
    assert result["model"]["total_parameters"] == 5
    assert all(row["role"] != "intercept" for row in result["coefficients"])
    cuts = np.array([r["estimate"] for r in result["nuisance_parameters"]])
    reverse_cuts = np.array([r["estimate"] for r in reverse["nuisance_parameters"]])
    assert cuts == pytest.approx(-reverse_cuts[::-1], abs=3e-6)
    for left, right in zip(result["coefficients"], reverse["coefficients"]):
        assert left["estimate"] == pytest.approx(1 / right["estimate"], rel=3e-6)
        assert left["lower"] == pytest.approx(1 / right["upper"], rel=3e-5)
    for left, right in zip(result["points"], reverse["points"]):
        expected = np.diff(np.r_[0, expit(cuts - left["linear_predictor"]), 1])
        assert left["category_probabilities"] == pytest.approx(expected, abs=1e-10)
        assert left["category_probabilities"] == pytest.approx(
            right["category_probabilities"][::-1], abs=1e-6
        )
        assert "residual" not in left and "fitted" not in left
    parameters = np.array(result["optimization_parameters"])
    covariance = np.array(result["optimization_covariance"])

    # Independently differentiate transformed thresholds to check covariance mapping.
    def cutpoints(params):
        return np.r_[params[2], np.exp(params[3:])].cumsum()

    step = np.eye(len(parameters)) * 1e-5
    jacobian = np.column_stack(
        [(cutpoints(parameters + h) - cutpoints(parameters - h)) / 2e-5 for h in step]
    )
    expected_se = np.sqrt(np.diag(jacobian @ covariance @ jacobian.T))
    assert [p["standard_error"] for p in result["nuisance_parameters"]] == pytest.approx(
        expected_se, rel=1e-7
    )


def test_spline_basis_is_not_mislabeled_as_unit_effect_and_reference_change_preserves_fit():
    data = source("binary")
    predictors = deepcopy(study().predictors)
    predictors[0]["knots"] = [-1.7, -0.5, 0.5, 1.7]
    spec = study(
        distribution="binomial",
        outcome_levels=["0", "1"],
        predictors=predictors,
        interactions=[["x", "group"]],
    )
    result = run_regression(data, spec)
    changed_predictors = deepcopy(predictors)
    changed_predictors[0]["reference"] = 0.5
    changed = run_regression(data, replace(spec, predictors=changed_predictors))
    assert [p["fitted"] for p in result["points"]] == pytest.approx(
        [p["fitted"] for p in changed["points"]], abs=1e-9
    )
    spline_terms = [
        r
        for r in result["coefficients"]
        if r["role"] == "spline_basis" or r["role"] == "interaction"
    ]
    assert len(spline_terms) == 6
    assert all(
        not r["exponentiated"] and "basis coefficient" in r["effect_scale"] for r in spline_terms
    )
    nonlinear = next(r for r in result["joint_tests"] if r["role"] == "nonlinearity")
    assert nonlinear["df"] == 4 and len(nonlinear["terms"]) == 4
    reference = next(p for p in result["conditional_curves"][0]["points"] if p["value"] == 0)
    assert reference == dict(value=0.0, estimate=1.0, lower=1.0, upper=1.0)
    assert result["conditional_curves"][0]["profile"] == {"group": "A"}
    assert result["multiplicity"]["families_separate"] is True
    assert result["multiplicity"]["ci_adjusted"] is False


def test_interaction_group_reference_swap_preserves_fit_and_inverts_ratio_of_ratios():
    data = source("binary")
    spec = study(distribution="binomial", outcome_levels=["0", "1"], interactions=[["x", "group"]])
    result = run_regression(data, spec)
    predictors = deepcopy(spec.predictors)
    predictors[1]["reference"] = "B"
    reverse = run_regression(data, replace(spec, predictors=predictors))
    assert [r["fitted"] for r in result["points"]] == pytest.approx(
        [r["fitted"] for r in reverse["points"]], abs=1e-10
    )
    left, right = result["coefficients"][-1], reverse["coefficients"][-1]
    assert left["effect_scale"] == right["effect_scale"] == "ratio of odds ratios"
    assert left["estimate"] == pytest.approx(1 / right["estimate"])
    assert left["lower"] == pytest.approx(1 / right["upper"])
    assert result["coefficients"][1]["coefficient"] + left["coefficient"] == pytest.approx(
        reverse["coefficients"][1]["coefficient"]
    )
