"""Welch NI independent arithmetic oracles and source-bound safeguards."""

from dataclasses import replace
from fractions import Fraction
import json
import math

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq
from scipy.special import betainc

from rde.infrastructure.clinical.noninferiority import run_noninferiority
from rde.infrastructure.clinical.noninferiority_contract import (
    NoninferioritySpec,
    noninferiority_preflight,
    prepare_noninferiority,
)
from rde.infrastructure.clinical.survival import digest


def spec_for(**updates):
    spec = NoninferioritySpec(
        subject="person",
        treatment="arm",
        treatment_levels=["control", "active"],
        treatment_definition="Synthetic active treatment versus control",
        outcome="response",
        outcome_definition="Synthetic outcome for numerical validation",
        outcome_window="One prespecified synthetic measurement",
        outcome_unit="score points",
        method="welch_mean",
        direction="higher_is_better",
        margin=2.0,
        margin_scale="outcome_unit",
        margin_basis="Synthetic fixture assumption only; no clinical margin claim",
        population_definition="All independent synthetic participants with a recorded outcome",
        context="Software verification; no real clinical study",
        study_design="randomized_parallel",
        independent_rows=True,
        missing_strategy="complete_case",
        one_sided_alpha=0.025,
    )
    return replace(spec, **updates)


def means_fixture():
    control = [10, 12, 9, 11, 13, 12, 10, 14]
    treatment = [11, 10, 12, 9, 13, 11, 14, 10, 12, 11]
    frame = pd.DataFrame(
        [
            {"person": f"{label}-{index}", "arm": label, "response": value}
            for label, values in [("control", control), ("active", treatment)]
            for index, value in enumerate(values)
        ]
    )
    return frame, spec_for(), control, treatment


def mean_variance(values):
    n = len(values)
    mean = sum(map(Fraction, values)) / n
    variance = sum((Fraction(value) - mean) ** 2 for value in values) / (n - 1)
    return mean, variance


def welch_oracle(control, treatment, margin):
    m0, v0 = mean_variance(control)
    m1, v1 = mean_variance(treatment)
    a, b = v1 / len(treatment), v0 / len(control)
    variance = a + b
    degrees = variance * variance / (a * a / (len(treatment) - 1) + b * b / (len(control) - 1))
    statistic = (float(m1 - m0) + margin) / math.sqrt(float(variance))
    # Student-t upper tail from the incomplete beta identity, not ttest's API.
    probability = 0.5 * float(
        betainc(float(degrees) / 2, 0.5, float(degrees) / (float(degrees) + statistic**2))
    )
    if statistic < 0:
        probability = 1 - probability
    return float(m1 - m0), math.sqrt(float(variance)), float(degrees), statistic, probability


def test_welch_shifted_null_matches_independent_fraction_oracle():
    frame, spec, control, treatment = means_fixture()
    original = frame.copy(deep=True)
    result = run_noninferiority(frame, spec)
    inference = result["noninferiority"]
    effect, se, df, statistic, p_value = welch_oracle(control, treatment, spec.margin)
    assert inference["benefit_difference"] == pytest.approx(effect)
    assert inference["standard_error"] == pytest.approx(se)
    assert inference["degrees_of_freedom"] == pytest.approx(df)
    assert inference["statistic"] == pytest.approx(statistic)
    assert inference["p_value"] == pytest.approx(p_value)
    # Invert the independent incomplete-beta tail; do not reuse runner's t.isf.
    critical = brentq(
        lambda value: 0.5 * betainc(df / 2, 0.5, df / (df + value**2)) - spec.one_sided_alpha, 0, 20
    )
    assert inference["critical_statistic"] == pytest.approx(critical)
    assert inference["lower_confidence_bound"] == pytest.approx(effect - critical * se)
    assert inference["passed"] is True
    assert inference["confidence_level"] == 0.975 and inference["one_sided_alpha"] == 0.025
    assert inference["upper_confidence_bound"] is None
    assert result["receipt_sha256"] == digest(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    )
    json.dumps(result, allow_nan=False)
    pd.testing.assert_frame_equal(frame, original)


def test_superiority_failure_is_not_automatically_noninferiority():
    frame, spec, _, _ = means_fixture()
    result = run_noninferiority(frame, replace(spec, margin=0.05))["noninferiority"]
    assert result["passed"] is False
    assert result["p_value"] > spec.one_sided_alpha
    assert result["lower_confidence_bound"] < -0.05
    assert result["decision"] == "noninferiority_not_demonstrated"


def test_welch_exact_ni_boundary_does_not_pass_and_margin_change_is_versioned():
    frame, spec, _, _ = means_fixture()
    first = run_noninferiority(frame, spec)
    boundary_margin = -first["noninferiority"]["lower_confidence_bound"]
    assert boundary_margin > 0
    at_boundary = run_noninferiority(frame, replace(spec, margin=boundary_margin))
    decision = at_boundary["noninferiority"]
    assert decision["p_value"] == pytest.approx(spec.one_sided_alpha)
    assert decision["passed"] is False and decision["decision"] == "boundary_not_demonstrated"
    assert at_boundary["spec_sha256"] != first["spec_sha256"]
    below = run_noninferiority(frame, replace(spec, margin=boundary_margin - 0.01))[
        "noninferiority"
    ]
    above = run_noninferiority(frame, replace(spec, margin=boundary_margin + 0.01))[
        "noninferiority"
    ]
    assert below["passed"] is False and above["passed"] is True


def test_welch_lower_is_better_and_joint_role_direction_reversal():
    frame, spec, _, _ = means_fixture()
    reference = run_noninferiority(frame, spec)["noninferiority"]
    negated = frame.copy()
    negated["response"] *= -1
    result = run_noninferiority(negated, replace(spec, direction="lower_is_better"))[
        "noninferiority"
    ]
    assert result["benefit_difference"] == pytest.approx(reference["benefit_difference"])
    assert result["raw_treatment_minus_control"] == pytest.approx(
        -reference["raw_treatment_minus_control"]
    )
    assert result["p_value"] == pytest.approx(reference["p_value"])
    switched = run_noninferiority(
        frame,
        replace(spec, direction="lower_is_better", treatment_levels=spec.treatment_levels[::-1]),
    )["noninferiority"]
    assert switched["p_value"] == pytest.approx(reference["p_value"])


def test_zero_variance_is_not_replaced_with_a_different_test():
    frame, spec, _, _ = means_fixture()
    frame.loc[frame.arm == "control", "response"] = 10
    preflight = noninferiority_preflight(frame, spec)
    assert preflight["can_execute"] is False
    assert preflight["groups"][0]["sample_variance"] == 0
    with pytest.raises(ValueError, match="No variance correction"):
        run_noninferiority(frame, spec)


def test_source_permutation_trace_determinism_and_missing_population_limits():
    frame, spec = means_fixture()[:2]
    frame.loc[0, "response"] = None
    preflight = noninferiority_preflight(frame, spec)
    assert preflight["missing_required"] == 1
    assert preflight["case_ledger"]["missing_excluded_data_rows"] == [1]
    assert preflight["case_ledger"]["population_membership_verification"] == "not_performed"
    first = run_noninferiority(frame, spec)
    assert run_noninferiority(frame.copy(), spec) == first
    shuffled = frame.sample(frac=1, random_state=31).reset_index(drop=True)
    second = run_noninferiority(shuffled, spec)
    assert first["noninferiority"]["p_value"] == pytest.approx(second["noninferiority"]["p_value"])
    assert first["dataframe_sha256"] != second["dataframe_sha256"]
    for row in second["observations"]:
        original = shuffled.iloc[row["data_row"] - 1]
        assert original.arm == row["treatment"]
        assert row["value"] == original.response
    json.dumps(second, allow_nan=False)


def test_bad_source_codes_and_identity_cannot_hide_in_missing_rows():
    frame, spec = means_fixture()[:2]
    frame.loc[0, "response"] = None
    frame.loc[0, "arm"] = "undeclared"
    with pytest.raises(ValueError, match="Undeclared treatment"):
        prepare_noninferiority(frame, spec)
    frame.loc[0, "arm"] = "active"
    frame.loc[0, "person"] = frame.loc[1, "person"]
    with pytest.raises(ValueError, match="duplicate subject"):
        prepare_noninferiority(frame, spec)
    frame.loc[0, "person"] = "new-distinct-id"
    frame.loc[0, "arm"] = None
    frame["response"] = frame.response.astype(object)
    frame.loc[0, "response"] = "bad-code"
    with pytest.raises(ValueError, match="Undeclared outcome|non-numeric"):
        prepare_noninferiority(frame, spec)


@pytest.mark.parametrize(
    "changes",
    [
        {"margin": 0},
        {"margin": -1},
        {"margin": True},
        {"margin": float("inf")},
        {"one_sided_alpha": 0},
        {"one_sided_alpha": 0.5},
        {"one_sided_alpha": 0.05},
        {"confidence_level": 0.95},
        {"direction": "choose_from_results"},
        {"independent_rows": False},
        {"independent_rows": 1},
        {"study_design": "case_control"},
        {"missing_strategy": "nonresponder"},
        {"subject": "response"},
        {"treatment_levels": ["control", "control"]},
        {"population_definition": "ITT"},
        {"margin_basis": "guess"},
        {"method": "superiority"},
    ],
)
def test_invalid_or_underspecified_ni_spec_is_rejected(changes):
    with pytest.raises(ValueError):
        NoninferioritySpec.parse({**spec_for().to_dict(), **changes})


def test_alpha_confidence_relation_is_one_sided_and_unknown_fields_rejected():
    spec = spec_for(one_sided_alpha=0.05, confidence_level=0.95)
    assert NoninferioritySpec.parse(spec.to_dict()) == spec
    with pytest.raises(ValueError, match="Unknown"):
        NoninferioritySpec.parse({**spec.to_dict(), "add_half_cell": True})
    with pytest.raises(ValueError, match="Missing"):
        NoninferioritySpec.parse({k: v for k, v in spec.to_dict().items() if k != "margin_basis"})


@pytest.mark.parametrize("method", ["binary_risk_difference", "wald_risk_difference", "score"])
def test_binary_requests_are_rejected_without_estimator_substitution(method):
    frame, spec = means_fixture()[:2]
    with pytest.raises(ValueError, match="unsupported|Only welch_mean"):
        NoninferioritySpec.parse({**spec.to_dict(), "method": method})
    with pytest.raises(ValueError, match="unsupported|Only welch_mean"):
        run_noninferiority(frame, replace(spec, method=method))


def test_binary_values_cannot_be_disguised_as_a_welch_continuous_outcome():
    frame, spec = means_fixture()[:2]
    frame["response"] = np.arange(len(frame)) % 2
    preflight = noninferiority_preflight(frame, spec)
    assert preflight["can_execute"] is False
    assert any("continuous_outcome" in row["reason"] for row in preflight["blocking_groups"])
    with pytest.raises(ValueError, match="estimator boundary"):
        run_noninferiority(frame, spec)


@pytest.mark.parametrize("scale", ["absolute_probability", "percentage_points", "relative_effect"])
def test_margin_must_use_the_original_continuous_outcome_unit(scale):
    with pytest.raises(ValueError, match="original continuous outcome scale"):
        NoninferioritySpec.parse({**spec_for().to_dict(), "margin_scale": scale})


def test_positive_unit_conversion_preserves_inference_and_changes_identity():
    frame, spec = means_fixture()[:2]
    original = run_noninferiority(frame, spec)
    changed = frame.copy()
    changed["response"] = changed.response * 100 + 10_000
    converted = run_noninferiority(
        changed, replace(spec, margin=spec.margin * 100, outcome_unit="hundredth score points")
    )
    before, after = original["noninferiority"], converted["noninferiority"]
    assert after["p_value"] == pytest.approx(before["p_value"])
    assert after["benefit_difference"] == pytest.approx(before["benefit_difference"] * 100)
    assert after["lower_confidence_bound"] == pytest.approx(before["lower_confidence_bound"] * 100)
    assert after["passed"] == before["passed"]
    assert converted["spec_sha256"] != original["spec_sha256"]
    assert converted["dataframe_sha256"] != original["dataframe_sha256"]


@pytest.mark.parametrize("bad_value", [float("inf"), float("-inf"), "not-numeric"])
def test_nonfinite_or_malformed_outcomes_cannot_hide_in_missing_treatment(bad_value):
    frame, spec = means_fixture()[:2]
    frame["response"] = frame.response.astype(object)
    frame.loc[0, "arm"] = None
    frame.loc[0, "response"] = bad_value
    with pytest.raises(ValueError, match="nonfinite|non-numeric"):
        prepare_noninferiority(frame, spec)


@pytest.mark.parametrize("bad_id", [None, "", "  "])
def test_missing_subject_is_rejected_before_complete_case_removal(bad_id):
    frame, spec = means_fixture()[:2]
    frame.loc[0, "person"] = bad_id
    frame.loc[0, "response"] = None
    with pytest.raises(ValueError, match="subject identity"):
        prepare_noninferiority(frame, spec)


def test_duplicate_source_columns_and_removed_binary_settings_are_rejected():
    frame, spec = means_fixture()[:2]
    duplicated = pd.concat([frame, frame[["response"]]], axis=1)
    with pytest.raises(ValueError, match="uniquely named"):
        prepare_noninferiority(duplicated, spec)
    with pytest.raises(ValueError, match="Unknown"):
        NoninferioritySpec.parse({**spec.to_dict(), "outcome_levels": ["no", "yes"]})


def test_insufficient_complete_cases_and_absent_arm_are_not_silently_analyzed():
    frame, spec = means_fixture()[:2]
    frame.loc[0:9, "response"] = None
    preflight = noninferiority_preflight(frame, spec)
    assert preflight["minimum_complete_cases_met"] is False
    assert preflight["can_execute"] is False
    assert any(item["group"] == "control" for item in preflight["blocking_groups"])
    assert preflight["case_ledger"]["missing_excluded_data_rows"] == list(range(1, 11))
    json.dumps(preflight, allow_nan=False)
    with pytest.raises(ValueError, match="insufficient complete cases"):
        run_noninferiority(frame, spec)


@pytest.mark.parametrize("shift", [-100, -3, 0, 3, 100])
def test_welch_tails_match_independent_beta_oracle_for_both_signs(shift):
    frame, spec, control, treatment = means_fixture()
    frame.loc[frame.arm == "active", "response"] += shift
    result = run_noninferiority(frame, spec)["noninferiority"]
    oracle = welch_oracle(control, [value + shift for value in treatment], spec.margin)
    assert result["statistic"] == pytest.approx(oracle[3])
    assert result["p_value"] == pytest.approx(oracle[4], rel=1e-10, abs=1e-15)
    assert result["passed"] == (result["lower_confidence_bound"] > -spec.margin)
