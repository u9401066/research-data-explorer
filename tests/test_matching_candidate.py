"""Independent assignment enumeration and pair-difference covariance checks."""

from dataclasses import asdict, replace
from itertools import product

import numpy as np
import pandas as pd
import pytest
from scipy.stats import t

from rde.infrastructure.clinical.matching import (
    MatchingSpec,
    optimal_pairs,
    pair_cluster_effect,
    run_matching,
)
from test_weighting_models import cell_fixture


def enumerated_objective(treated, controls, caliper):
    """Enumerate partial injective maps, without assignment/cost-matrix code."""
    alternatives = []
    for mapping in product(range(-1, len(controls)), repeat=len(treated)):
        used = [index for index in mapping if index >= 0]
        if len(set(used)) != len(used):
            continue
        differences = [
            abs(value - controls[j]) for value, j in zip(treated, mapping, strict=True) if j >= 0
        ]
        if all(value <= caliper for value in differences):
            alternatives.append((-len(used), sum(differences)))
    return min(alternatives)


@pytest.mark.parametrize("seed", range(12))
def test_assignment_matches_exhaustive_partial_maps(seed):
    rng = np.random.default_rng(seed)
    treated, controls = rng.integers(-3, 4, 4), rng.integers(-3, 4, 3)
    caliper = seed % 3
    pairs = optimal_pairs(treated, controls, caliper)
    assert (-len(pairs), sum(p[2] for p in pairs)) == enumerated_objective(
        treated, controls, caliper
    )
    assert len({j for _, j, _ in pairs}) == len(pairs)


def test_cardinality_precedes_distance_and_boundary_is_inclusive():
    # Greedy nearest for the first treated case would consume the only legal
    # control of the second. The global design must retain both pairs.
    assert optimal_pairs([0.1, 0.0], [0.0, 0.3], 0.2) == [
        (0, 1, pytest.approx(0.2)),
        (1, 0, 0.0),
    ]
    assert optimal_pairs([0.0, 1.0], [0.0, 2.0], 0) == [(0, 0, 0.0)]


@pytest.mark.parametrize("binary", [False, True])
def test_cr1_inference_matches_independent_pair_difference_formula(binary):
    control = np.array([1, 0, 0, 1, 0, 0, 1, 1], dtype=float)
    treated = np.array([1, 1, 0, 0, 1, 1, 1, 1], dtype=float)
    if not binary:
        control = control * 7 + np.arange(8) ** 2
        treated = treated * 9 + np.arange(8)
    actual = pair_cluster_effect(treated, control, 0.95)
    differences = treated - control
    count = len(differences)
    expected_mean = sum(differences) / count
    # Pair differences give an independent scalar derivation of treatment-only
    # OLS variance, then the explicitly selected N/K CR1 correction.
    sample_variance = sum((value - expected_mean) ** 2 for value in differences) / (count - 1)
    expected_se = np.sqrt(sample_variance / count * (2 * count - 1) / (2 * count - 2))
    assert actual["estimate"] == pytest.approx(expected_mean)
    assert actual["standard_error"] == pytest.approx(expected_se)
    assert actual["df"] == count - 1
    assert actual["p_value"] == pytest.approx(2 * t.sf(abs(expected_mean / expected_se), count - 1))
    radius = expected_se * t.ppf(0.975, count - 1)
    assert actual["ci_lower"] == pytest.approx(expected_mean - radius)
    assert actual["ci_upper"] == pytest.approx(expected_mean + radius)


def matching_fixture(outcome_type="continuous"):
    frame, weighting, counts, outcomes = cell_fixture(outcome_type)
    payload = asdict(weighting)
    payload.update(family="matching", estimand="matched_treated", caliper_sd=0.2)
    return frame, MatchingSpec.parse(payload)


@pytest.mark.parametrize("outcome_type", ["continuous", "binary"])
def test_saturated_strata_scores_source_ledger_and_outcome_blind_assignment(outcome_type):
    frame, spec = matching_fixture(outcome_type)
    original = frame.copy(deep=True)
    result = run_matching(frame, spec)
    assert result["matching_population"]["matched_pairs"] == 70
    assert result["matching_population"]["unmatched_treated"] == 50
    assert result["matching_population"]["unmatched_controls"] == 10
    by_id = frame.set_index(frame.case.astype(str))
    for row in result["source_case_ledger"]:
        source = by_id.loc[row["subject_id"]]
        expected_score = 30 / 70 if source.stratum == "Low" else 90 / 130
        assert row["propensity"] == pytest.approx(expected_score, abs=1e-12)
        assert frame.iloc[row["source_data_row"] - 1]["case"] == source["case"]
    for pair in result["pairs"]:
        assert by_id.loc[pair["treated_id"]].stratum == by_id.loc[pair["control_id"]].stratum
    changed = frame.copy()
    changed["outcome"] = changed["outcome"].iloc[::-1].to_numpy()
    altered = run_matching(changed, spec)

    def pair_ids(value):
        return [(p["treated_id"], p["control_id"]) for p in value["pairs"]]

    assert pair_ids(result) == pair_ids(altered)
    assert result["dataframe_sha256"] != altered["dataframe_sha256"]
    shuffled = run_matching(frame.sample(frac=1, random_state=7), spec)
    assert pair_ids(result) == pair_ids(shuffled)
    assert result["effect"] == shuffled["effect"]
    assert result["dataframe_sha256"] != shuffled["dataframe_sha256"]
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize(
    "settings",
    [
        {"estimand": "ATT"},
        {"family": "weighting"},
        {"subject": None},
        {"method": "with_replacement"},
        {"inference": "independent_t"},
        {"caliper_sd": float("nan")},
        {"caliper_sd": True},
        {"study_design": "case_control"},
        {"pretreatment_covariates": False},
    ],
)
def test_rejects_unapproved_design_substitutions(settings):
    frame, spec = matching_fixture()
    with pytest.raises(ValueError):
        run_matching(frame, replace(spec, **settings))


def test_duplicate_subject_missing_roles_and_separation_are_explicit():
    frame, spec = matching_fixture()
    duplicate = frame.copy()
    duplicate.loc[1, "case"] = duplicate.loc[0, "case"]
    with pytest.raises(ValueError, match="identity"):
        run_matching(duplicate, spec)
    separated = frame.copy()
    separated["stratum"] = separated.treatment.map({"Control": "Low", "Treated": "High"})
    with pytest.raises(ValueError, match="separation|overlap"):
        run_matching(separated, spec)
    missing = frame.copy()
    missing.loc[0, "outcome"] = np.nan
    result = run_matching(missing, spec)
    assert result["population"]["missing_excluded_data_rows"] == [1]
    assert result["source_case_ledger"][0]["status"] == "missing_required"
    assert result["source_case_ledger"][0]["missing_source_roles"] == ["outcome"]


def test_zero_pair_variance_does_not_fabricate_uncertainty():
    with pytest.raises(ValueError, match="variance"):
        pair_cluster_effect([2] * 8, [1] * 8, 0.95)


def test_whole_source_ledger_keeps_missing_filter_and_match_exclusions():
    frame, spec = matching_fixture()
    frame["cohort"] = "in"
    frame.loc[0, "cohort"] = "out"
    frame.loc[1, "outcome"] = np.nan
    frame.loc[2, "stratum"] = None
    spec = replace(spec, cohort_filter={"column": "cohort", "values": ["in"]})
    result = run_matching(frame, spec)
    rows, ledger = result["source_case_ledger"], result["case_ledger"]
    assert [r["source_data_row"] for r in rows] == list(range(1, 201))
    assert [r["status"] for r in rows[:3]] == [
        "outside_cohort",
        "missing_required",
        "missing_required",
    ]
    assert rows[1]["missing_source_roles"] == ["outcome"] and rows[2]["missing_source_roles"] == [
        "stratum"
    ]
    assert ledger["propensity_complete_data_rows"] == list(range(4, 201))
    assert sorted(ledger["complete_data_rows"] + ledger["matching_excluded_data_rows"]) == list(
        range(4, 201)
    )
    assert len(ledger["complete_data_rows"]) == result["n"] == 2 * len(result["pairs"])
    assert all(row["unmatched_reason"] for row in rows if row["status"] == "unmatched")


@pytest.mark.parametrize("column,bad", [("treatment", "unmapped"), ("stratum", "unmapped")])
def test_illegal_observed_source_code_rejected_before_missing_drop(column, bad):
    frame, spec = matching_fixture()
    frame.loc[0, "outcome"] = np.nan
    frame.loc[0, column] = bad
    with pytest.raises(ValueError, match="Unmapped|undeclared"):
        run_matching(frame, spec)


def test_binary_illegal_outcome_cannot_hide_behind_missing_covariate():
    frame, spec = matching_fixture("binary")
    frame.loc[0, "outcome"] = "unknown-code"
    frame.loc[0, "stratum"] = None
    with pytest.raises(ValueError, match="Unmapped outcome"):
        run_matching(frame, spec)


def test_fixed_treated_sd_distribution_and_binary_four_cells():
    frame, spec = matching_fixture("binary")
    result = run_matching(frame, spec)
    for row in result["balance"]:
        before_t = frame.loc[frame.treatment == "Treated", "stratum"].eq(row["level"]).astype(float)
        assert row["standardization_sd"] == pytest.approx(
            np.sqrt(before_t.mean() * (1 - before_t.mean()))
        )
        assert row["matched_smd"] == pytest.approx(
            row["matched_difference"] / row["standardization_sd"]
        )
        assert row["after"]["control"]["n"] == row["after"]["treated"]["n"] == 70
        assert 0 <= row["after"]["ecdf_max_difference"] <= 1
    pairs = result["pairs"]
    expected = [
        [
            sum(p["control_outcome"] == c and p["treated_outcome"] == t for p in pairs)
            for t in (0, 1)
        ]
        for c in (0, 1)
    ]
    assert result["paired_binary"]["cells"] == expected
    assert sum(map(sum, expected)) == 70
    assert result["paired_binary"]["discordant_pairs"] == expected[0][1] + expected[1][0]


def test_zero_treated_sd_is_unknown_and_not_fabricated_balance():
    frame, spec = matching_fixture()
    frame["baseline"] = 0.0
    control = frame.index[frame.treatment == "Control"]
    frame.loc[control, "baseline"] = np.tile([-1.0, 1.0], len(control) // 2)
    spec = replace(
        spec,
        covariates=spec.covariates
        + [
            dict(
                column="baseline",
                kind="continuous",
                label="Baseline",
                unit="units",
                reference=0.0,
                increment=1.0,
                knots=[],
                pre_exposure_basis="Recorded before treatment",
            )
        ],
    )
    result = run_matching(frame, spec)
    row = next(r for r in result["balance"] if r["column"] == "baseline")
    assert row["standardization_sd"] == 0 and row["smd"] is None and row["matched_smd"] is None
    assert "zero_original_treated_sd" in row["review_reasons"]


def test_zero_logit_sd_only_permits_exact_scores_and_five_pair_floor():
    with pytest.raises(ValueError, match="five"):
        pair_cluster_effect([1, 2, 3, 5], [0, 1, 1, 0], 0.95)
    assert optimal_pairs([0.0, 0.0], [0.0, 1.0], 0.0) == [(0, 0, 0.0)]


def test_propensity_nonconvergence_is_not_replaced_or_clipped(monkeypatch):
    import statsmodels.api as sm

    original = sm.GLM.fit

    def unconverged(*args, **kwargs):
        result = original(*args, **kwargs)
        result.converged = False
        return result

    monkeypatch.setattr(sm.GLM, "fit", unconverged)
    frame, spec = matching_fixture()
    with pytest.raises(ValueError, match="converged"):
        run_matching(frame, spec)


def test_identity_cannot_be_hidden_by_cohort_filter():
    frame, spec = matching_fixture()
    frame["cohort"] = "in"
    frame.loc[0, "cohort"] = "out"
    frame.loc[0, "case"] = frame.loc[1, "case"]
    with pytest.raises(ValueError, match="identity"):
        run_matching(frame, replace(spec, cohort_filter={"column": "cohort", "values": ["in"]}))


def test_small_binary_matching_retains_quality_flags_and_zero_logit_sd():
    _, spec = matching_fixture("binary")
    frame = pd.DataFrame(
        {
            "case": np.arange(1, 25),
            "treatment": ["Control"] * 12 + ["Treated"] * 12,
            "stratum": ["Low", "High"] * 12,
            "outcome": ["None"] * 12 + ["None", "Event"] * 6,
        }
    )
    result = run_matching(frame, spec)
    assert result["matching_population"]["matched_pairs"] == 12
    assert result["matching"]["pooled_logit_sd"] == pytest.approx(0, abs=1e-14)
    assert all(
        pair["absolute_logit_distance"] <= result["matching"]["absolute_logit_caliper"]
        for pair in result["pairs"]
    )
    assert result["paired_binary"]["discordant_pairs"] == 6
    assert {"few_matched_pairs", "few_discordant_pairs"} <= set(
        result["diagnostics"]["review_flags"]
    )
    assert result["effect"]["estimate"] == pytest.approx(0.5)
    assert result["effect"]["df"] == 11
