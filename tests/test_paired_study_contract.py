"""Pairing and missingness must remain auditable before and after inference."""

from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from rde.infrastructure.clinical.repeated import run_repeated
from rde.infrastructure.clinical.repeated_contract import (
    RepeatedSpec,
    prepare_repeated,
    repeated_preflight,
)
from rde.infrastructure.clinical.survival import digest


def specification(**overrides):
    return RepeatedSpec.parse(
        {
            "family": "repeated",
            "subject": "study_code",
            "measurements": [
                {"column": c, "label": f"Visit {i}"}
                for i, c in enumerate(["baseline", "day7", "day28"])
            ],
            "contrasts": [["day7", "baseline"], ["day28", "baseline"]],
            "outcome_name": "Synthetic clinical score",
            "outcome_unit": "score points",
            "outcome_definition": "The same synthetic measured outcome at each visit.",
            "context": "Synthetic independent subjects for numerical workflow verification.",
            "method": "signed_rank",
            "primary_effect": "rank_biserial",
            "case_strategy": "pairwise",
            "independent_subjects": True,
            "same_outcome": True,
            "omnibus": True,
            "bootstrap": {"resamples": 999, "seed": 731},
            "multiplicity": "holm",
            **overrides,
        }
    )


def fixture():
    rng = np.random.default_rng(989)
    df = pd.DataFrame(
        rng.integers(0, 20, (24, 3)).astype(float), columns=["baseline", "day7", "day28"]
    )
    df["study_code"] = [f"S{i:02}" for i in range(24)]
    df["cohort"] = ["A"] * 22 + ["B"] * 2
    df.loc[0, "baseline"] = np.nan
    df.loc[1, "day7"] = np.nan
    df.loc[2, "day28"] = np.nan
    return df


def test_preflight_preserves_full_source_and_distinct_pairwise_populations():
    df = fixture()
    before = df.copy(deep=True)
    spec = specification(cohort_filter={"column": "cohort", "values": ["A"]})
    result = repeated_preflight(df, spec)
    assert result["spec"] == spec.to_dict()
    assert result["spec_sha256"] == digest(spec.to_dict())
    assert result["n"] == 19
    ledger = result["case_ledger"]
    assert ledger["filter_excluded_data_rows"] == [23, 24]
    assert ledger["missing_excluded_data_rows"] == [1, 2, 3]
    assert ledger["observed_bitmask_by_cohort_row"][:3] == [6, 5, 3]
    assert ledger["contrasts"][0]["complete_data_rows"] == list(range(3, 23))
    assert ledger["contrasts"][1]["complete_data_rows"] == [2, *range(4, 23)]
    assert result["planned_hypotheses"] == 3
    assert not {"effect", "p_value", "hypotheses"} & result.keys()
    pd.testing.assert_frame_equal(before, df)


def test_duplicate_subjects_cannot_be_hidden_by_missing_measurements():
    df = fixture()
    df.loc[0, "study_code"] = df.loc[1, "study_code"]
    with pytest.raises(ValueError, match="duplicate subject"):
        prepare_repeated(df, specification())
    df.loc[0, "study_code"] = None
    with pytest.raises(ValueError, match="missing or duplicate"):
        prepare_repeated(df, specification())


def test_invalid_measurement_is_not_a_missing_value_and_no_name_based_exclusion():
    df = fixture().astype({"day7": object})
    df.loc[0, "day7"] = "not measured?"
    with pytest.raises(ValueError):
        prepare_repeated(df, specification())
    df = fixture().rename(columns={"day7": "BMI"})
    df.loc[1, "BMI"] = -1000
    spec = specification(
        measurements=[{"column": c, "label": c} for c in ["baseline", "BMI", "day28"]],
        contrasts=[["BMI", "baseline"]],
    )
    frame, ledger, _ = prepare_repeated(df, spec)
    assert frame.loc[1, "BMI"] == -1000
    assert 2 in ledger["contrasts"][0]["complete_data_rows"]


@pytest.mark.parametrize(
    "override",
    [
        {"contrasts": [["day7", "baseline"], ["baseline", "day7"]]},
        {"contrasts": [["baseline", "baseline"]]},
        {"subject": "baseline"},
        {"independent_subjects": 1},
        {"same_outcome": False},
        {"confidence_level": True},
        {"method": "paired_mean"},
        {"bootstrap": {"resamples": 998, "seed": 1}},
        {"bootstrap": {"resamples": 999, "seed": True}},
        {"cohort_filter": {"column": "day7", "values": ["3"]}},
        {"unexpected": True},
        {"multiplicity": "none"},
    ],
)
def test_malformed_or_ambiguous_design_fails_before_estimation(override):
    with pytest.raises(ValueError):
        specification(**override)


def test_all_contrasts_are_retained_and_family_keeps_unavailable_test():
    df = fixture()
    df["day28"] = df["baseline"]
    spec = specification()
    result = run_repeated(df, spec)
    assert len(result["contrasts"]) == 2
    assert result["contrasts"][1]["p_value"] is None
    hypotheses = result["hypotheses"]
    expected = multipletests(
        [r["p_value"] if r["p_value"] is not None else 1 for r in hypotheses], method="holm"
    )[1]
    for row, p in zip(hypotheses, expected, strict=True):
        assert row["adjusted_p_value"] == (pytest.approx(p) if row["p_value"] is not None else None)
    assert result["multiplicity"]["members"] == ["omnibus", "contrast_1", "contrast_2"]
    assert result["contrasts"][1]["effect"]["estimate"]["status"] == "undefined"
    json.dumps(result, allow_nan=False)


def test_frozen_pairing_row_membership_and_receipt_cannot_be_changed_by_display_order():
    df = fixture()
    spec = specification()
    result = run_repeated(df, spec)
    assert result["n"] == 21
    assert [c["n"] for c in result["contrasts"]] == [22, 22]
    for contrast in result["contrasts"]:
        assert contrast["data_rows"] == [r["data_row"] for r in contrast["observations"]]
        for row in contrast["observations"]:
            original = df.iloc[row["data_row"] - 1]
            assert row["first"] == original[contrast["columns"][0]]
            assert row["second"] == original[contrast["columns"][1]]
            assert row["difference"] == row["first"] - row["second"]
    reordered = specification(measurements=list(reversed(spec.measurements)))
    assert run_repeated(df, reordered)["contrasts"] == result["contrasts"]
    copy = deepcopy(result)
    receipt = copy.pop("receipt_sha256")
    assert receipt == digest(copy)
    copy["observations"][0]["values"][0] += 1
    assert receipt != digest(copy)
    assert result == run_repeated(df, spec)


def test_complete_case_mean_contract_has_no_friedman_or_resampling():
    result = run_repeated(
        fixture(),
        specification(
            method="paired_mean",
            primary_effect="mean_difference",
            bootstrap=None,
            omnibus=False,
            case_strategy="complete",
        ),
    )
    assert result["omnibus"] is None
    assert result["multiplicity"]["size"] == 2
    assert all(c["n"] == result["n"] for c in result["contrasts"])
    assert all("resampling" not in c for c in result["contrasts"])
