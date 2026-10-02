"""Study-level comparison edges: exact roles, case identity and fixed families."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from rde.infrastructure.clinical.comparison import run_comparison
from rde.infrastructure.clinical.comparison_contract import (
    ComparisonSpec,
    comparison_preflight,
    prepare_comparison,
)
from rde.infrastructure.clinical.survival import digest


def fixture():
    frame = pd.DataFrame(
        {
            "arm": ["B", "C", "A"] * 10,
            "response": [float((i * 7) % 23) + i / 10 for i in range(30)],
            "subject": list(range(30)),
            "eligible": ["yes"] * 29 + ["no"],
        }
    )
    frame.loc[0, "response"] = np.nan
    spec = ComparisonSpec(
        outcome="response",
        group="arm",
        group_levels=["A", "B", "C"],
        contrasts=[["C", "A"], ["B", "A"]],
        method="welch_mean",
        primary_effect="mean_difference",
        outcome_unit="score points",
        outcome_definition="Synthetic numerical score for engineering validation",
        outcome_window="One synthetic baseline observation",
        context="Engineering fixture; no clinical claim",
        study_design="cross_sectional",
        independent_rows=True,
        subject="subject",
        omnibus=True,
        cohort_filter={"column": "eligible", "values": ["yes"]},
    )
    return frame, spec


def test_fixed_labels_shared_cases_and_planned_family_survive_missing_first_row():
    frame, spec = fixture()
    original = frame.copy(deep=True)
    preflight = comparison_preflight(frame, spec)
    assert (
        preflight["n"] == 28 and preflight["outside_cohort"] == preflight["missing_required"] == 1
    )
    assert preflight["groups"] == [
        {"label": "A", "n": 9},
        {"label": "B", "n": 9},
        {"label": "C", "n": 10},
    ]
    assert preflight["planned_hypotheses"] == 3
    result = run_comparison(frame, spec)
    assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
    assert [r["data_row"] for r in result["observations"]] == list(range(2, 30))
    assert result["contrasts"][0]["groups"] == ["C", "A"]
    assert result["contrasts"][0]["data_rows"] == [list(range(2, 30, 3)), list(range(3, 28, 3))]
    raw = [r["p_value"] for r in result["hypotheses"]]
    assert [r["adjusted_p_value"] for r in result["hypotheses"]] == pytest.approx(
        multipletests(raw, method="holm")[1]
    )
    assert result["receipt_sha256"] == digest(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    )
    json.dumps(result, allow_nan=False)
    pd.testing.assert_frame_equal(frame, original)


def test_duplicate_subject_and_bad_coding_cannot_hide_in_excluded_outcome_rows():
    frame, spec = fixture()
    frame.loc[0, "subject"] = frame.loc[1, "subject"]
    with pytest.raises(ValueError, match="identity"):
        prepare_comparison(frame, spec)
    frame, spec = fixture()
    frame.loc[0, "arm"] = "unreviewed"
    with pytest.raises(ValueError, match="Undeclared group"):
        prepare_comparison(frame, spec)
    with pytest.raises(ValueError, match="Reversed|reversed"):
        replace(spec, contrasts=[["B", "A"], ["A", "B"]]).validate()


def test_unavailable_test_retains_its_family_slot_and_does_not_become_p_one():
    frame, spec = fixture()
    frame["response"] = frame["arm"].map({"A": 1.0, "B": 2.0, "C": 3.0})
    frame.loc[frame.arm == "C", "response"] += np.arange(10)
    result = run_comparison(frame, replace(spec, omnibus=False, multiplicity="bonferroni"))
    assert result["multiplicity"]["size"] == 2
    assert result["contrasts"][1]["p_value"] is None
    assert result["contrasts"][1]["adjusted_p_value"] is None
    assert result["contrasts"][1]["effects"]["mean_difference"]["status"] == "unavailable"
    assert result["contrasts"][0]["adjusted_p_value"] == pytest.approx(
        min(1, result["contrasts"][0]["p_value"] * 2)
    )


def test_case_control_study_never_emits_population_probability_effects_or_intervals():
    frame, spec = fixture()
    frame["response"] = ["case", "control", "control"] * 10
    spec = replace(
        spec,
        method="binary",
        primary_effect="odds_ratio",
        outcome_levels=["control", "case"],
        study_design="case_control",
        omnibus=False,
    )
    result = run_comparison(frame, spec)
    for contrast in result["contrasts"]:
        assert set(contrast["effects"]) == {"odds_ratio"}
        assert contrast["group_proportions"] == []
        assert contrast["probabilities_identified"] is False
    with pytest.raises(ValueError, match="does not identify"):
        replace(spec, primary_effect="proportion_difference").validate()
    with pytest.raises(ValueError, match="sparse"):
        comparison_preflight(frame, replace(spec, omnibus=True))


def test_rank_study_requires_fixed_resampling_and_can_reproduce_the_complete_receipt():
    frame, spec = fixture()
    with pytest.raises(ValueError, match="prespecified BCa"):
        replace(spec, method="rank", primary_effect="rank_biserial").validate()
    spec = replace(
        spec,
        method="rank",
        primary_effect="rank_biserial",
        bootstrap={"resamples": 999, "seed": 274},
    )
    first = run_comparison(frame, spec)
    assert first == run_comparison(frame, spec)
    assert all(c["effects"]["rank_biserial"]["status"] == "available" for c in first["contrasts"])
    assert [c["resampling"]["seed"] for c in first["contrasts"]] == [274, 275]
