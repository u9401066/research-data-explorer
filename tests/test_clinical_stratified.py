"""Independent hand-count oracles and source/estimability boundaries for CMH."""

from dataclasses import replace
from fractions import Fraction
import json
import math

import numpy as np
import pandas as pd
import pytest

from rde.infrastructure.clinical.stratified import run_stratified
from rde.infrastructure.clinical.stratified_contract import (
    StratifiedSpec,
    prepare_stratified,
    stratified_preflight,
)
from rde.infrastructure.clinical.survival import digest


COUNTS = [[[12, 8], [5, 15]], [[6, 14], [4, 16]], [[18, 12], [8, 22]]]


def fixture(counts=None):
    tables = COUNTS if counts is None else counts
    records = []
    for index, table in enumerate(tables):
        for arm in range(2):
            for event in range(2):
                for _ in range(table[arm][event]):
                    records.append(
                        {
                            "person": f"case-{len(records) + 1}",
                            "arm": ["control", "active"][arm],
                            "response": ["no", "yes"][event],
                            "site": f"stratum-{index + 1}",
                        }
                    )
    return pd.DataFrame(records), StratifiedSpec(
        subject="person",
        treatment="arm",
        treatment_levels=["control", "active"],
        treatment_definition="Synthetic active assignment versus synthetic control",
        outcome="response",
        outcome_levels=["no", "yes"],
        outcome_definition="Synthetic event explicitly coded yes",
        outcome_window="One synthetic baseline assessment",
        strata="site",
        strata_levels=[f"stratum-{i + 1}" for i in range(len(tables))],
        context="Synthetic software validation only; no clinical claim",
        study_design="randomized_parallel",
        independent_rows=True,
        missing_strategy="complete_case",
    )


def count_oracle(tables):
    # Exact rational arithmetic from the conditional hypergeometric mean/variance,
    # independent of pandas, numpy and statsmodels' table implementation.
    deviation, variance, numerator, denominator = (Fraction(0) for _ in range(4))
    for (a, b), (c, d) in tables:
        n = a + b + c + d
        deviation += a - Fraction((a + b) * (a + c), n)
        variance += Fraction((a + b) * (a + c) * (b + d) * (c + d), n * n * (n - 1))
        numerator += Fraction(a * d, n)
        denominator += Fraction(b * c, n)
    statistic = float(deviation * deviation / variance)
    return float(numerator / denominator), statistic, math.erfc(math.sqrt(statistic / 2))


def test_hand_counts_cmh_oracle_direction_and_source_receipt():
    frame, spec = fixture()
    original = frame.copy(deep=True)
    result = run_stratified(frame, spec)
    ratio, statistic, p_value = count_oracle(COUNTS)
    assert result["schema"] == "clinical-result-v1"
    assert result["family"] == "stratified" and result["status"] == "completed"
    assert [item["table"] for item in result["strata"]] == COUNTS
    assert result["common_odds_ratio"]["estimate"] == pytest.approx(ratio, rel=1e-13)
    assert result["cmh"]["statistic"] == pytest.approx(statistic, rel=1e-13)
    assert result["cmh"]["p_value"] == pytest.approx(p_value, rel=1e-12)
    assert result["common_odds_ratio"]["direction"] == {
        "numerator_treatment": "active",
        "denominator_treatment": "control",
        "event": "yes",
        "non_event": "no",
    }
    assert result["equal_odds"]["status"] == "estimated"
    assert result["n"] == 140
    assert result["receipt_sha256"] == digest(
        {key: value for key, value in result.items() if key != "receipt_sha256"}
    )
    json.dumps(result, allow_nan=False)
    pd.testing.assert_frame_equal(frame, original)


def test_log_normal_interval_matches_hand_calculation_for_identical_strata():
    counts = [[[30, 10], [10, 30]], [[30, 10], [10, 30]]]
    frame, spec = fixture(counts)
    effect = run_stratified(frame, spec)["common_odds_ratio"]
    # For two identical tables the MH log variance reduces to half the
    # single-table sum of reciprocal cell counts.
    expected_se = math.sqrt((1 / 30 + 1 / 10 + 1 / 10 + 1 / 30) / 2)
    z_975 = 1.959963984540054
    assert effect["estimate"] == pytest.approx(9)
    assert effect["log_standard_error"] == pytest.approx(expected_se, rel=1e-13)
    assert effect["ci_lower"] == pytest.approx(math.exp(math.log(9) - z_975 * expected_se))
    assert effect["ci_upper"] == pytest.approx(math.exp(math.log(9) + z_975 * expected_se))
    assert effect["ci_status"] == "estimated"


@pytest.mark.parametrize("reverse", ["treatment", "outcome", "both"])
def test_reversing_declared_direction_changes_or_not_cmh(reverse):
    frame, spec = fixture()
    original = run_stratified(frame, spec)
    swapped = replace(
        spec,
        treatment_levels=spec.treatment_levels[::-1]
        if reverse in {"treatment", "both"}
        else spec.treatment_levels,
        outcome_levels=spec.outcome_levels[::-1]
        if reverse in {"outcome", "both"}
        else spec.outcome_levels,
    )
    result = run_stratified(frame, swapped)
    first, second = original["common_odds_ratio"], result["common_odds_ratio"]
    assert result["cmh"]["statistic"] == pytest.approx(original["cmh"]["statistic"])
    assert result["cmh"]["p_value"] == pytest.approx(original["cmh"]["p_value"])
    assert second["estimate"] == pytest.approx(
        first["estimate"] if reverse == "both" else 1 / first["estimate"]
    )
    assert second["ci_lower"] == pytest.approx(
        first["ci_lower"] if reverse == "both" else 1 / first["ci_upper"]
    )
    assert second["ci_upper"] == pytest.approx(
        first["ci_upper"] if reverse == "both" else 1 / first["ci_lower"]
    )
    assert result["spec_sha256"] != original["spec_sha256"]


def test_permutation_preserves_statistics_but_changes_source_identity_and_trace():
    frame, spec = fixture()
    original = run_stratified(frame, spec)
    shuffled = frame.sample(frac=1, random_state=8).reset_index(drop=True)
    result = run_stratified(shuffled, spec)
    assert result["cmh"] == original["cmh"]
    assert result["common_odds_ratio"] == original["common_odds_ratio"]
    assert result["dataframe_sha256"] != original["dataframe_sha256"]
    for row in result["observations"]:
        source = shuffled.iloc[row["data_row"] - 1]
        assert [row["treatment"], row["outcome"], row["stratum"]] == [
            source.arm,
            source.response,
            source.site,
        ]
    reordered = run_stratified(frame, replace(spec, strata_levels=spec.strata_levels[::-1]))
    assert reordered["cmh"]["statistic"] == pytest.approx(original["cmh"]["statistic"])
    assert [item["label"] for item in reordered["strata"]] == spec.strata_levels[::-1]


def test_preflight_shared_complete_cases_and_each_excluded_source_row():
    frame, spec = fixture()
    frame.loc[0, "response"] = None
    frame.loc[1, "arm"] = None
    frame.loc[2, "site"] = None
    frame.loc[3, ["response", "arm"]] = None
    preflight = stratified_preflight(frame, spec)
    assert preflight["n"] == 136 and preflight["missing_required"] == 4
    assert preflight["case_ledger"]["missing_excluded_data_rows"] == [1, 2, 3, 4]
    assert preflight["case_ledger"]["missing_by_role"] == {"arm": 2, "response": 2, "site": 1}
    assert preflight["case_ledger"]["identity_checked_rows"] == 140
    assert preflight["can_execute"] is True
    assert "p_value" not in json.dumps(preflight) and "estimate" not in preflight
    result = run_stratified(frame, spec)
    assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
    assert result["case_ledger"] == preflight["case_ledger"]


@pytest.mark.parametrize(
    "role,missing", [("arm", "response"), ("response", "site"), ("site", "arm")]
)
def test_undeclared_source_codes_cannot_hide_behind_missing_other_roles(role, missing):
    frame, spec = fixture()
    frame.loc[0, role] = "unreviewed"
    frame.loc[0, missing] = None
    with pytest.raises(ValueError, match="Undeclared"):
        prepare_stratified(frame, spec)


@pytest.mark.parametrize("identity", [None, "case-2", "   "])
def test_bad_subject_identity_blocks_before_missing_exclusion(identity):
    frame, spec = fixture()
    frame.loc[0, "person"] = identity
    frame.loc[0, "response"] = None
    with pytest.raises(ValueError, match="identity"):
        prepare_stratified(frame, spec)


@pytest.mark.parametrize(
    "change",
    [
        {"independent_rows": False},
        {"independent_rows": 1},
        {"missing_strategy": "fill_zero"},
        {"subject": "arm"},
        {"treatment_levels": ["active", "active"]},
        {"outcome_levels": ["yes"]},
        {"strata_levels": ["stratum-1"]},
        {"study_design": "cluster_randomized"},
        {"confidence_level": 1},
        {"confidence_level": True},
        {"family": "comparison"},
    ],
)
def test_invalid_spec_is_rejected(change):
    _, spec = fixture()
    with pytest.raises(ValueError):
        StratifiedSpec.parse({**spec.to_dict(), **change})


def test_strict_parse_rejects_extra_or_missing_fields_and_round_trips():
    _, spec = fixture()
    assert StratifiedSpec.parse(spec.to_dict()) == spec
    assert spec.variables() == ["person", "arm", "response", "site"]
    with pytest.raises(ValueError, match="Unknown"):
        StratifiedSpec.parse({**spec.to_dict(), "shift_zeros": True})
    with pytest.raises(ValueError, match="Missing"):
        StratifiedSpec.parse(
            {key: value for key, value in spec.to_dict().items() if key != "subject"}
        )
    with pytest.raises(ValueError, match="Unknown"):
        StratifiedSpec.parse([])


def test_empty_declared_stratum_is_preserved_and_blocks_execution():
    frame, spec = fixture()
    spec = replace(spec, strata_levels=[*spec.strata_levels, "not_exported"])
    preflight = stratified_preflight(frame, spec)
    assert preflight["can_execute"] is False
    empty = preflight["strata"][-1]
    assert empty["label"] == "not_exported" and empty["table"] == [[0, 0], [0, 0]]
    assert empty["data_rows"] == [] and empty["expected_under_independence"] is None
    assert preflight["blocking_strata"][0]["stratum"] == "not_exported"
    with pytest.raises(ValueError, match="not_exported"):
        run_stratified(frame, spec)


@pytest.mark.parametrize("table", [[[0, 0], [10, 12]], [[0, 12], [0, 11]]])
def test_zero_margin_stratum_is_not_silently_discarded(table):
    frame, spec = fixture([COUNTS[0], table])
    preflight = stratified_preflight(frame, spec)
    assert preflight["strata"][1]["table"] == table
    assert preflight["blocking_strata"][0]["stratum"] == "stratum-2"
    with pytest.raises(ValueError, match="stratum-2"):
        run_stratified(frame, spec)


def test_all_missing_stratum_retains_source_denominator_and_blocks():
    frame, spec = fixture()
    frame.loc[frame.site == "stratum-1", "response"] = None
    preflight = stratified_preflight(frame, spec)
    assert preflight["case_ledger"]["strata_counts"][0] == {
        "label": "stratum-1",
        "source_rows": 40,
        "complete_rows": 0,
    }
    assert preflight["strata"][0]["table"] == [[0, 0], [0, 0]]
    assert preflight["can_execute"] is False


def test_zero_cell_is_retained_without_half_cell_correction():
    counts = [[[0, 10], [8, 12]], [[12, 8], [4, 16]]]
    frame, spec = fixture(counts)
    result = run_stratified(frame, spec)
    ratio, statistic, p_value = count_oracle(counts)
    assert [item["table"] for item in result["strata"]] == counts
    assert result["strata"][0]["zero_cells"] == 1
    assert result["common_odds_ratio"]["estimate"] == pytest.approx(ratio)
    assert result["cmh"]["statistic"] == pytest.approx(statistic)
    assert result["cmh"]["p_value"] == pytest.approx(p_value)
    assert result["common_odds_ratio"]["ci_status"] == "estimated"


@pytest.mark.parametrize("boundary", ["zero", "unbounded"])
def test_boundary_common_or_is_explicit_and_not_fabricated_finite(boundary):
    counts = [[[0, 15], [10, 8]], [[0, 12], [6, 14]]]
    if boundary == "unbounded":
        counts = [table[::-1] for table in counts]
    frame, spec = fixture(counts)
    result = run_stratified(frame, spec)
    effect = result["common_odds_ratio"]
    assert effect["status"] == "boundary" and effect["boundary"] == boundary
    assert effect["estimate"] == (0 if boundary == "zero" else None)
    assert effect["ci_lower"] is None and effect["ci_upper"] is None
    assert result["equal_odds"]["status"] == "not_estimable"
    assert result["equal_odds"]["p_value"] is None
    assert math.isfinite(result["cmh"]["statistic"])
    json.dumps(result, allow_nan=False)


def test_pooled_or_one_retains_primary_results_without_fake_diagnostic_p_one():
    frame, spec = fixture([[[10, 10], [10, 10]], [[15, 15], [15, 15]]])
    result = run_stratified(frame, spec)
    assert result["common_odds_ratio"]["estimate"] == 1
    assert result["common_odds_ratio"]["ci_status"] == "estimated"
    assert result["cmh"]["statistic"] == 0 and result["cmh"]["p_value"] == 1
    assert result["equal_odds"]["status"] == "not_estimable"
    assert result["equal_odds"]["p_value"] is None
    assert "OR=1" in result["equal_odds"]["reason"]


def test_sparse_strata_remain_visible_and_same_cmh_formula():
    counts = [[[2, 1], [1, 2]], [[2, 1], [1, 2]]]
    frame, spec = fixture(counts)
    preflight = stratified_preflight(frame, spec)
    assert preflight["can_execute"] is True
    assert all(item["expected_cells_below_five"] == 4 for item in preflight["strata"])
    result = run_stratified(frame, spec)
    assert result["cmh"]["statistic"] == pytest.approx(count_oracle(counts)[1])
    assert any("below five" in message for message in result["warnings"])


def test_nonfinite_and_nonscalar_codes_and_duplicate_columns_fail_explicitly():
    frame, spec = fixture()
    frame.loc[0, "arm"] = np.inf
    with pytest.raises(ValueError, match="nonfinite"):
        prepare_stratified(frame, spec)
    frame, spec = fixture()
    frame.at[0, "arm"] = ["control"]
    with pytest.raises(ValueError, match="scalar"):
        prepare_stratified(frame, spec)
    frame, spec = fixture()
    frame.columns = ["person", "arm", "response", "response"]
    with pytest.raises(ValueError, match="uniquely"):
        prepare_stratified(frame, spec)


def test_case_control_never_outputs_risks_or_risk_ratios():
    frame, spec = fixture()
    result = run_stratified(frame, replace(spec, study_design="case_control"))
    assert result["common_odds_ratio"]["estimate"] == pytest.approx(count_oracle(COUNTS)[0])
    assert "risk_ratio" not in result and "risk_difference" not in result
    assert all("proportion" not in stratum for stratum in result["strata"])


def test_repeated_person_across_strata_cannot_become_independent_by_stratification():
    frame, spec = fixture()
    frame.loc[frame.site == "stratum-2", "person"] = frame.loc[
        frame.site == "stratum-1", "person"
    ].to_numpy()
    with pytest.raises(ValueError, match="duplicate subject"):
        prepare_stratified(frame, spec)


def test_minimum_complete_cases_is_separate_from_positive_stratum_margins():
    frame, spec = fixture([[[2, 1], [1, 2]], [[2, 1], [1, 2]]])
    frame.loc[[0, 5, 6, 11], "response"] = None
    preflight = stratified_preflight(frame, spec)
    assert preflight["n"] == 8 and preflight["blocking_strata"] == []
    assert preflight["minimum_complete_cases_met"] is False
    assert preflight["can_execute"] is False
    with pytest.raises(ValueError, match="ten complete"):
        run_stratified(frame, spec)
    with pytest.raises(ValueError, match="10..100,000"):
        prepare_stratified(frame.iloc[:9], spec)


def test_repeat_is_deterministic_and_changed_source_has_a_different_receipt():
    frame, spec = fixture()
    first = run_stratified(frame, spec)
    assert run_stratified(frame.copy(deep=True), spec) == first
    frame.loc[0, "response"] = "yes"
    changed = run_stratified(frame, spec)
    assert changed["spec_sha256"] == first["spec_sha256"]
    assert changed["dataframe_sha256"] != first["dataframe_sha256"]
    assert changed["receipt_sha256"] != first["receipt_sha256"]
    assert changed["strata"][0]["table"] == [[11, 9], [5, 15]]
