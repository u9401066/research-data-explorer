"""Clinical source/role failures must not become an apparently usable weight set."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from rde.infrastructure.clinical.weighting_contract import WeightingSpec, weighting_preflight


def fixture():
    frame = pd.DataFrame(
        {
            "case": np.arange(1, 25),
            "treatment": ["Treated" if i % 3 == 0 else "Control" for i in range(24)],
            "outcome": ["Event" if i % 5 == 0 else "None" for i in range(24)],
            "age": np.arange(40.0, 64.0),
            "group": ["F" if (i // 2) % 2 else "M" for i in range(24)],
            "eligible": ["yes"] * 24,
        }
    )
    spec = WeightingSpec(
        treatment="treatment",
        treatment_levels=["Control", "Treated"],
        treatment_definition="Synthetic baseline exposure, not actual patient data",
        outcome="outcome",
        outcome_type="binary",
        outcome_unit="recorded event indicator",
        outcome_definition="Synthetic fully observed event after exposure",
        time_origin="Synthetic cohort entry",
        outcome_window="Prespecified complete synthetic follow-up",
        study_design="observational_cohort",
        context="Synthetic source-boundary test only; not a causal finding",
        estimand="ATE",
        independent_rows=True,
        pretreatment_covariates=True,
        subject="case",
        outcome_levels=["None", "Event"],
        covariates=[
            dict(
                column="age",
                kind="continuous",
                label="Synthetic age",
                unit="years",
                reference=50,
                increment=10,
                knots=[],
                pre_exposure_basis="Generated before synthetic exposure",
            ),
            dict(
                column="group",
                kind="categorical",
                label="Synthetic group",
                levels=["F", "M"],
                reference="F",
                pre_exposure_basis="Fixed synthetic baseline category",
            ),
        ],
    )
    return frame, spec


def test_one_common_population_retains_source_rows_and_literal_none_label():
    frame, spec = fixture()
    frame.loc[0, "age"] = np.nan
    frame.loc[2, "outcome"] = None
    frame.loc[4, "eligible"] = "no"
    frame.index = ["unreliable serialized row label"] * len(frame)
    spec = replace(spec, cohort_filter={"column": "eligible", "values": ["yes"]})
    before = frame.copy(deep=True)
    pre = weighting_preflight(frame, spec)
    assert pre["n"] == 21
    assert pre["case_ledger"]["missing_excluded_data_rows"] == [1, 3]
    assert pre["case_ledger"]["filter_excluded_data_rows"] == [5]
    assert pre["case_ledger"]["complete_data_rows"] == [
        i for i in range(1, 25) if i not in {1, 3, 5}
    ]
    assert pre["outcome_levels"] == [
        {"label": "None", "code": 0, "n": 17},
        {"label": "Event", "code": 1, "n": 4},
    ]
    assert pre["treatment_levels"] == [
        {"label": "Control", "code": 0, "n": 14},
        {"label": "Treated", "code": 1, "n": 7},
    ]
    pd.testing.assert_frame_equal(frame, before)
    changed = frame.copy()
    changed.iloc[8, changed.columns.get_loc("outcome")] = "Event"
    other = weighting_preflight(changed, spec)
    assert other["dataframe_sha256"] != pre["dataframe_sha256"]
    assert other["design_sha256"] == pre["design_sha256"]


@pytest.mark.parametrize("identity", [None, 4])
def test_identity_errors_precede_missing_outcome_exclusion(identity):
    frame, spec = fixture()
    frame.loc[7, "case"] = identity
    frame.loc[7, "outcome"] = None
    with pytest.raises(ValueError, match="identity.*before outcome exclusion"):
        weighting_preflight(frame, spec)


@pytest.mark.parametrize(
    "column,value,missing_column,match",
    [
        ("treatment", "Not recorded", "outcome", "Unmapped treatment"),
        ("outcome", "Lost to follow-up", "age", "Unmapped outcome"),
        ("group", "Unknown group", "outcome", "undeclared covariate"),
        ("age", "Not a number", "outcome", "numeric"),
    ],
)
def test_missing_another_role_cannot_hide_illegal_source_codes(
    column, value, missing_column, match
):
    frame, spec = fixture()
    frame[column] = frame[column].astype(object)
    frame.loc[3, column] = value
    frame.loc[3, missing_column] = None
    with pytest.raises(ValueError, match=match):
        weighting_preflight(frame, spec)


def test_rejects_post_outcome_roles_and_unsupported_design_changes():
    frame, spec = fixture()
    for replacement in [
        {"study_design": "case_control"},
        {"pretreatment_covariates": False},
        {"independent_rows": False},
        {"estimand": "choose_best_balance"},
        {"outcome": "age", "outcome_type": "continuous", "outcome_levels": []},
        {"cohort_filter": {"column": "outcome", "values": ["None"]}},
        {"covariates": [{**spec.covariates[0], "pre_exposure_basis": ""}]},
    ]:
        with pytest.raises(ValueError):
            weighting_preflight(frame, replace(spec, **replacement))
    for unknown in ["trim", "stabilize", "auto_select", "cluster"]:
        with pytest.raises(ValueError, match="Unknown weighting settings"):
            WeightingSpec.parse({**spec.to_dict(), unknown: True})


def test_lost_category_and_rank_deficiency_after_outcome_missingness_stop_preflight():
    frame, spec = fixture()
    frame.loc[frame.group == "M", "outcome"] = None
    with pytest.raises(ValueError, match="Every declared covariate level"):
        weighting_preflight(frame, spec)
    frame, spec = fixture()
    frame["copy_age"] = frame.age
    spec = replace(
        spec, covariates=[*spec.covariates, {**spec.covariates[0], "column": "copy_age"}]
    )
    with pytest.raises(ValueError, match="rank-deficient"):
        weighting_preflight(frame, spec)
