"""Edge cases that must be rejected before longitudinal model fitting."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from rde.infrastructure.clinical.longitudinal_contract import (
    LongitudinalSpec,
    longitudinal_design,
    longitudinal_preflight,
    prepare_longitudinal,
)


def fixture():
    data = pd.DataFrame(
        [
            {
                "id": f"P{i:02}",
                "visit": t,
                "response": i / 3 + t,
                "group": "A" if i < 8 else "B",
                "baseline": i + 20,
                "duration": 2.0,
            }
            for i in range(16)
            for t in [-2, -1, 0, 1]
        ]
    )
    spec = LongitudinalSpec(
        outcome="response",
        subject="id",
        time="visit",
        time_unit="years",
        time_origin="Age centered at nine years",
        outcome_unit="measurement units",
        context="Synthetic longitudinal edge fixture",
        independent_subjects=True,
        method="gee",
        distribution="gaussian",
        group="group",
        group_reference="A",
        covariates=["baseline"],
        time_by_group=True,
    )
    return data, spec


def test_negative_centered_time_and_partial_visits_keep_observation_and_subject_denominators():
    data, spec = fixture()
    data.loc[63, "response"] = np.nan
    frame, ledger, source_hash = prepare_longitudinal(data, spec)
    assert ledger["input_rows"] == 64 and len(frame) == 63
    assert ledger["n_subjects"] == 16
    assert ledger["missing_excluded_data_rows"] == [64]
    assert ledger["observations_per_subject"] == {"min": 3, "max": 4}
    assert frame.time.min() == -2
    matrix, terms = longitudinal_design(frame, spec)
    assert matrix.loc[0, "time"] == -2
    assert matrix.loc[32, "time:group_L1"] == -2
    assert terms[-1]["components"] == ["time", "group_L1"]
    assert longitudinal_preflight(data, spec)["dataframe_sha256"] == source_hash
    shuffled, shuffled_ledger, shuffled_hash = prepare_longitudinal(data.iloc[::-1], spec)
    assert len(shuffled) == 63 and shuffled_ledger["n_subjects"] == 16
    assert shuffled_ledger["missing_excluded_data_rows"] == [1]
    assert shuffled_hash != source_hash


@pytest.mark.parametrize("fault", ["duplicate", "id", "time", "baseline", "group", "exposure"])
def test_missing_outcome_cannot_hide_late_source_identity_or_baseline_faults(fault):
    data, spec = fixture()
    data["response"] = np.floor(data.response + 5)
    data.loc[63, "response"] = np.nan
    spec = replace(spec, distribution="poisson", exposure="duration", exposure_unit="weeks")
    if fault == "duplicate":
        data.loc[63, "visit"] = 0
    elif fault in {"id", "time"}:
        data.loc[63, "id" if fault == "id" else "visit"] = np.nan
    elif fault in {"baseline", "group"}:
        data.loc[63, fault] = 99 if fault == "baseline" else "A"
    else:
        data.loc[63, "duration"] = 0
    with pytest.raises(ValueError):
        prepare_longitudinal(data, spec)


def test_explicit_source_codes_references_and_lost_visits_are_not_inferred():
    data, spec = fixture()
    data["response"] = ["喘鳴" if i % 3 == 0 else "無" for i in range(len(data))]
    spec = replace(
        spec,
        distribution="binomial",
        positive="喘鳴",
        negative="無",
        time_mode="categorical",
        time_levels=[-2, -1, 0, 1],
    )
    assert longitudinal_preflight(data, spec)["n_subjects"] == 16
    data.loc[63, "response"] = "未知"
    with pytest.raises(ValueError, match="Unmapped"):
        prepare_longitudinal(data, spec)
    data.loc[63, "response"] = "無"
    data.loc[data.visit == -1, "response"] = None
    with pytest.raises(ValueError, match="Every declared categorical time"):
        prepare_longitudinal(data, spec)
    with pytest.raises(ValueError, match="reference"):
        prepare_longitudinal(*[fixture()[0], replace(fixture()[1], group_reference="not present")])


def test_time_varying_role_is_explicit_and_design_aliases_fail_before_fitting():
    data, spec = fixture()
    data["baseline"] += data["visit"]
    with pytest.raises(ValueError, match="Baseline role"):
        prepare_longitudinal(data, spec)
    changed = replace(spec, time_varying_covariates=["baseline"])
    assert longitudinal_preflight(data, changed)["parameters"] == 5
    data["baseline"] = data.visit
    frame, _, _ = prepare_longitudinal(data, changed)
    with pytest.raises(ValueError, match="rank-deficient"):
        longitudinal_design(frame, changed)


def test_explicit_cohort_and_complete_observation_exclusions_remain_disjoint():
    data, spec = fixture()
    data["eligible"] = ["yes" if i < 12 else "no" for i in range(16) for _ in range(4)]
    data.loc[47, "response"] = np.nan
    spec = replace(spec, cohort_filter={"column": "eligible", "values": ["yes"]})
    frame, ledger, _ = prepare_longitudinal(data, spec)
    assert len(frame) == 47 and ledger["n_subjects"] == 12
    assert ledger["filter_excluded_data_rows"] == list(range(49, 65))
    assert ledger["missing_excluded_data_rows"] == [48]
    assert sorted(
        ledger["filter_excluded_data_rows"]
        + ledger["missing_excluded_data_rows"]
        + ledger["complete_data_rows"]
    ) == list(range(1, 65))
