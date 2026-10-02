"""Independent saturated-cell oracles and inference boundaries, synthetic data only."""

from dataclasses import replace
from itertools import product

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

from rde.infrastructure.clinical.survival import digest
from rde.infrastructure.clinical.weighting import run_weighting
from rde.infrastructure.clinical.weighting_contract import WeightingSpec


def cell_fixture(outcome_type="binary"):
    counts = np.array([32, 8, 12, 18, 15, 25, 30, 60])
    outcomes = np.array([0, 1] * 4, dtype=float)
    if outcome_type == "continuous":
        outcomes = np.array([-7, 5, 2, 11, 4, 16, 14, 28], dtype=float)
    records = []
    for i, (x, a, _y) in enumerate(product([0, 1], repeat=3)):
        records += [
            {
                "stratum": ["Low", "High"][x],
                "treatment": ["Control", "Treated"][a],
                "outcome": ["None", "Event"][int(outcomes[i])]
                if outcome_type == "binary"
                else outcomes[i],
            }
        ] * counts[i]
    frame = pd.DataFrame(records)
    frame["case"] = np.arange(1, len(frame) + 1)
    spec = WeightingSpec(
        treatment="treatment",
        treatment_levels=["Control", "Treated"],
        treatment_definition="Synthetic exposure after baseline stratum assignment",
        outcome="outcome",
        outcome_type=outcome_type,
        outcome_unit="synthetic units" if outcome_type == "continuous" else "recorded event",
        outcome_definition="Synthetic fully observed outcome; no actual patients",
        time_origin="Synthetic cohort entry before exposure",
        outcome_window="Complete synthetic follow-up to the fixed endpoint",
        study_design="observational_cohort",
        context="Synthetic numerical oracle only; not a clinical causal claim",
        estimand="ATE",
        independent_rows=True,
        pretreatment_covariates=True,
        subject="case",
        outcome_levels=["None", "Event"] if outcome_type == "binary" else [],
        covariates=[
            dict(
                column="stratum",
                kind="categorical",
                label="Synthetic stratum",
                levels=["Low", "High"],
                reference="Low",
                pre_exposure_basis="Generated before synthetic exposure",
            )
        ],
    )
    return frame, spec, counts, outcomes


def cell_oracle(probabilities, outcomes, estimand):
    """Closed-form stratum standardization, independent of weighted score equations.

    A logistic model saturated in a binary covariate gives empirical stratum
    propensities. Differentiate the multinomial cell functional to obtain all
    four parameters' covariance, without constructing scores, bread or weights.
    """
    cells = probabilities.reshape(2, 2, 2)
    joint = cells.sum(axis=2)
    stratum_mass = joint.sum(axis=1)
    e = joint[:, 1] / stratum_mass
    target = (
        stratum_mass
        if estimand == "ATE"
        else joint[:, 1]
        if estimand == "ATT"
        else joint.prod(axis=1) / stratum_mass
    )
    cell_means = (cells * outcomes.reshape(2, 2, 2)).sum(axis=2) / joint
    mu = (target[:, None] * cell_means).sum(axis=0) / target.sum()
    logits = np.log(e / (1 - e))
    return np.r_[logits[0], logits[1] - logits[0], mu[1], mu[0]]


@pytest.mark.parametrize("estimand", ["ATE", "ATT", "ATO"])
@pytest.mark.parametrize("outcome_type", ["continuous", "binary"])
def test_joint_covariance_matches_independent_multinomial_cell_functional(estimand, outcome_type):
    frame, spec, counts, outcomes = cell_fixture(outcome_type)
    before = frame.copy(deep=True)
    result = run_weighting(frame, replace(spec, estimand=estimand))
    probabilities = counts / counts.sum()
    expected = cell_oracle(probabilities, outcomes, estimand)
    jacobian = np.column_stack(
        [
            cell_oracle(probabilities.astype(complex) + 1e-25j * basis, outcomes, estimand).imag
            / 1e-25
            for basis in np.eye(len(counts))
        ]
    )
    multinomial = (np.diag(probabilities) - np.outer(probabilities, probabilities)) / counts.sum()
    expected_covariance = jacobian @ multinomial @ jacobian.T
    np.testing.assert_allclose(
        result["joint_estimation"]["parameters"], expected, rtol=2e-10, atol=2e-11
    )
    np.testing.assert_allclose(
        result["joint_estimation"]["covariance"], expected_covariance, rtol=2e-9, atol=2e-11
    )
    contrast = np.array([0, 0, 1, -1])
    assert result["effect"]["standard_error"] == pytest.approx(
        np.sqrt(contrast @ expected_covariance @ contrast), rel=2e-9
    )
    assert result["effect"]["estimate"] == pytest.approx(expected[2] - expected[3])
    assert result["receipt_sha256"] == digest(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    )
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("estimand", ["ATE", "ATT", "ATO"])
def test_source_units_and_label_direction_have_the_declared_effect(estimand):
    frame, spec, counts, outcomes = cell_fixture("continuous")
    spec = replace(spec, estimand=estimand)
    original = run_weighting(frame, spec)
    changed = frame.copy()
    changed.outcome = 1000 * changed.outcome + 11
    scaled = run_weighting(changed, replace(spec, outcome_unit="synthetic milli-units"))
    for key in ["estimate", "standard_error", "lower", "upper"]:
        assert scaled["effect"][key] == pytest.approx(1000 * original["effect"][key], rel=1e-10)
    assert scaled["design_sha256"] == original["design_sha256"]
    assert scaled["dataframe_sha256"] != original["dataframe_sha256"]
    reversed_result = run_weighting(
        frame, replace(spec, treatment_levels=list(reversed(spec.treatment_levels)))
    )
    if estimand == "ATT":
        # New treated population is the original controls, not the original ATT.
        expected = cell_oracle(
            counts.reshape(2, 2, 2)[:, ::-1].flatten() / counts.sum(),
            outcomes.reshape(2, 2, 2)[:, ::-1].flatten(),
            estimand,
        )
        assert reversed_result["effect"]["estimate"] == pytest.approx(expected[2] - expected[3])
        assert reversed_result["effect"]["estimate"] != pytest.approx(
            -original["effect"]["estimate"]
        )
    else:
        assert reversed_result["effect"]["estimate"] == pytest.approx(
            -original["effect"]["estimate"]
        )
        assert reversed_result["effect"]["standard_error"] == pytest.approx(
            original["effect"]["standard_error"]
        )
    binary, binary_spec, _, _ = cell_fixture()
    binary_spec = replace(binary_spec, estimand=estimand)
    positive = run_weighting(binary, binary_spec)
    negative = run_weighting(binary, replace(binary_spec, outcome_levels=["Event", "None"]))
    assert negative["effect"]["estimate"] == pytest.approx(-positive["effect"]["estimate"])
    assert negative["effect"]["standard_error"] == pytest.approx(
        positive["effect"]["standard_error"]
    )
    assert negative["effect"]["p_value"] == pytest.approx(positive["effect"]["p_value"])


def test_overlap_weights_balance_prespecified_splines_interactions_and_preserve_every_row():
    rng = np.random.default_rng(194)
    n = 1200
    age = rng.normal(50, 8, n)
    group = rng.integers(0, 3, n)
    probability = expit(-0.4 + 0.08 * (age - 50) + 0.02 * (age - 50) * (group == 2) + 0.3 * group)
    treatment = rng.binomial(1, probability)
    frame = pd.DataFrame(
        dict(
            case=np.arange(1, n + 1),
            age=age,
            stratum=np.array(["Low", "Middle", "High"])[group],
            treatment=np.array(["Control", "Treated"])[treatment],
            outcome=3 * treatment + age * 0.1 + rng.normal(size=n),
            eligible=["yes"] * n,
        )
    )
    _, base, _, _ = cell_fixture("continuous")
    spec = replace(
        base,
        estimand="ATO",
        cohort_filter={"column": "eligible", "values": ["yes"]},
        covariates=[
            dict(
                column="age",
                kind="continuous",
                label="Synthetic age",
                unit="years",
                reference=50,
                increment=10,
                knots=[36, 44, 52, 60, 68],
                pre_exposure_basis="Generated before exposure",
            ),
            {**base.covariates[0], "levels": ["Low", "Middle", "High"]},
        ],
        interactions=[["age", "stratum"]],
    )
    frame.loc[0, "outcome"] = np.nan
    frame.loc[1, "eligible"] = "no"
    result = run_weighting(frame, spec)
    assert len(result["points"]) == n
    assert result["points"][0]["status"] == "missing_required"
    assert result["points"][1]["status"] == "outside_cohort"
    assert result["points"][-1]["data_row"] == n
    assert result["points"][-1]["source_identity"] == str(n)
    assert result["n"] == n - 2
    for balance in result["diagnostics"]["basis_balance"]:
        assert abs(balance["weighted_smd"]) < 1e-8
    for code in [0, 1]:
        points = [row for row in result["points"] if row["treatment_code"] == code]
        assert sum(row["normalized_weight"] for row in points) == pytest.approx(1)
        histogram = [
            row
            for row in result["diagnostics"]["propensity_histogram"]
            if row["treatment_code"] == code
        ]
        assert sum(row["n"] for row in histogram) == len(points)
        assert sum(row["weighted_proportion"] for row in histogram) == pytest.approx(1)
    # A separate numerical derivative checks the nonsymmetric full Jacobian,
    # particularly the score-dependent ATO weight derivative.
    from rde.infrastructure.clinical.regression_contract import regression_design
    from rde.infrastructure.clinical.weighting_contract import prepare_weighting

    retained, _, _ = prepare_weighting(frame, spec)
    design, _, _ = regression_design(retained, spec.propensity_spec())
    x, a, y = design.to_numpy(), retained.treatment.to_numpy(), retained.response.to_numpy()
    theta = np.array(result["joint_estimation"]["parameters"])

    def scores(parameters):
        ps = expit(x @ parameters[:-2])
        return np.r_[
            (x * (a - ps)[:, None]).mean(axis=0),
            (a * (1 - ps) * (y - parameters[-2])).mean(),
            ((1 - a) * ps * (y - parameters[-1])).mean(),
        ]

    jacobian = np.column_stack(
        [
            (scores(theta + 1e-5 * direction) - scores(theta - 1e-5 * direction)) / 2e-5
            for direction in np.eye(len(theta))
        ]
    )
    np.testing.assert_allclose(-jacobian, result["joint_estimation"]["bread"], rtol=5e-6, atol=5e-8)


def test_fixed_balance_denominator_uses_treated_target_and_indicator_variance():
    frame, spec, _, _ = cell_fixture()
    result = run_weighting(frame, replace(spec, estimand="ATT"))
    high = next(row for row in result["diagnostics"]["covariate_balance"] if row["level"] == "High")
    treated = frame[frame.treatment == "Treated"]
    p = (treated.stratum == "High").mean()
    sd = np.sqrt(p * (1 - p))
    assert high["standardization_sd"] == pytest.approx(sd)
    assert high["smd"] == pytest.approx(high["difference"] / sd)
    assert high["weighted_smd"] == pytest.approx(high["weighted_difference"] / sd)
    assert high["treated_weighted_mean"] == pytest.approx(p)


def test_one_constant_outcome_group_keeps_estimable_difference_and_unclipped_interval():
    frame, spec, _, _ = cell_fixture()
    rows = []
    for category in ["Low", "High"]:
        rows += [dict(stratum=category, treatment="Control", outcome="None")] * 8
        rows += [
            dict(stratum=category, treatment="Treated", outcome=value)
            for value in ["None", "Event"]
        ]
    frame = pd.DataFrame(rows)
    frame["case"] = np.arange(1, len(frame) + 1)
    result = run_weighting(frame, replace(spec, confidence_level=0.999))
    covariance = np.array(result["joint_estimation"]["covariance"])
    assert np.linalg.matrix_rank(covariance) < len(covariance)
    assert result["effect"]["control_mean"] == 0
    assert result["effect"]["standard_error"] > 0
    assert result["effect"]["upper"] > 1
    frame.loc[frame.treatment == "Treated", "outcome"] = "Event"
    with pytest.raises(ValueError, match="positive sandwich variance"):
        run_weighting(frame, spec)


def test_separation_stops_instead_of_clipping_or_changing_the_model():
    frame, spec, _, _ = cell_fixture()
    frame.treatment = np.where(frame.stratum == "High", "Treated", "Control")
    with pytest.raises(ValueError, match="separation"):
        run_weighting(frame, spec)
