"""Source, coding and nonlinear-design boundaries before any model is fitted."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from patsy import dmatrix

from rde.infrastructure.clinical.regression_contract import (
    RegressionSpec,
    prepare_regression,
    regression_design,
    regression_preflight,
    restricted_cubic_basis,
)


def fixture():
    data = pd.DataFrame(
        {
            "patient": [f"P{i}" for i in range(40)],
            "age": np.linspace(10, 70, 40),
            "group": np.resize(["A", "B"], 40),
            "result": np.linspace(1, 4, 40) + np.sin(np.arange(40)),
            "duration": 2.0,
            "eligible": "yes",
        }
    )
    spec = RegressionSpec(
        outcome="result",
        outcome_unit="original measurement unit",
        context="Synthetic independent-case regression boundary fixture",
        independent_rows=True,
        study_design="cross_sectional",
        distribution="gaussian",
        subject="patient",
        predictors=[
            {
                "column": "age",
                "kind": "continuous",
                "label": "Age",
                "unit": "years",
                "reference": 40,
                "increment": 10,
                "knots": [20, 40, 60],
            },
            {
                "column": "group",
                "kind": "categorical",
                "label": "Group",
                "reference": "A",
                "levels": ["A", "B"],
            },
        ],
        interactions=[["age", "group"]],
    )
    return data, spec


def test_common_case_ledger_keeps_original_rows_and_preflight_does_not_fit(monkeypatch):
    import statsmodels.api as sm

    monkeypatch.setattr(sm, "OLS", lambda *args, **kwargs: pytest.fail("Preflight fitted a model"))
    data, spec = fixture()
    data.loc[2, "eligible"] = "no"
    data.loc[5, "result"] = np.nan
    data.loc[8, "age"] = np.nan
    spec = replace(spec, cohort_filter={"column": "eligible", "values": ["yes"]})
    result = regression_preflight(data, spec)
    assert result["n"] == 37 and result["input_rows"] == 40
    assert result["case_ledger"]["filter_excluded_data_rows"] == [3]
    assert result["case_ledger"]["missing_excluded_data_rows"] == [6, 9]
    assert result["case_ledger"]["complete_data_rows"] == [
        i for i in range(1, 41) if i not in [3, 6, 9]
    ]
    assert result["mean_parameters"] == 6
    assert result["study_design"] == "cross_sectional"
    reordered = regression_preflight(data.iloc[::-1], spec)
    assert reordered["n"] == 37
    assert reordered["dataframe_sha256"] != result["dataframe_sha256"]
    assert reordered["case_ledger"]["missing_excluded_data_rows"] == [32, 35]


@pytest.mark.parametrize(
    "fault", ["duplicate", "identity", "exposure", "negative", "fractional", "category"]
)
def test_missing_other_roles_cannot_hide_invalid_source_values(fault):
    data, spec = fixture()
    data["result"] = (np.arange(40) % 5).astype(float)
    spec = replace(spec, distribution="poisson", exposure="duration", exposure_unit="weeks")
    data.loc[39, "age"] = np.nan
    if fault == "duplicate":
        data.loc[39, "patient"] = "P0"
    elif fault == "identity":
        data.loc[39, "patient"] = None
    elif fault == "exposure":
        data.loc[39, "duration"] = 0
    elif fault in {"negative", "fractional"}:
        data.loc[39, "result"] = -1 if fault == "negative" else 1.5
    else:
        data.loc[39, "group"] = "Unmapped"
    with pytest.raises(ValueError):
        prepare_regression(data, spec)


def test_ordinal_source_order_is_not_alphabetical_and_thresholds_replace_intercept():
    data, spec = fixture()
    data["result"] = np.resize(["Marked", "None", "Some"], 40)
    spec = replace(spec, distribution="ordinal", outcome_levels=["None", "Some", "Marked"])
    frame, _, _ = prepare_regression(data, spec)
    np.testing.assert_array_equal(frame.outcome[:3], [2, 0, 1])
    matrix, terms, _ = regression_design(frame, spec)
    assert "intercept" not in matrix and all(t["role"] != "intercept" for t in terms)
    assert matrix.shape[1] == 5
    reversed_frame, _, _ = prepare_regression(
        data, replace(spec, outcome_levels=list(reversed(spec.outcome_levels)))
    )
    np.testing.assert_array_equal(reversed_frame.outcome, 2 - frame.outcome)
    data.loc[39, "age"] = np.nan
    data.loc[39, "result"] = "Unknown"
    with pytest.raises(ValueError, match="Unmapped outcome"):
        prepare_regression(data, spec)


def test_spline_matches_an_independent_natural_cubic_space_and_has_linear_tails():
    x = np.linspace(5, 75, 100)
    knots = [10, 30, 50, 70]
    basis = np.column_stack([np.ones(len(x)), restricted_cubic_basis(x, knots)])
    independent = np.asarray(
        dmatrix("cr(x, knots=(30,50), lower_bound=10, upper_bound=70) - 1", {"x": x})
    )
    # Different basis parameterizations must span the same functions, not just
    # reproduce the implementation's truncated-power formula.
    for a, b in [(basis, independent), (independent, basis)]:
        projection = a @ np.linalg.lstsq(a, b, rcond=None)[0]
        np.testing.assert_allclose(projection, b, rtol=1e-10, atol=1e-10)
    for tail in [[-15, -5, 5], [75, 85, 95]]:
        np.testing.assert_allclose(
            np.diff(restricted_cubic_basis(tail, knots), n=2, axis=0), 0, atol=1e-12
        )


def test_reference_increment_and_hierarchical_interactions_preserve_the_declared_scale():
    data, spec = fixture()
    frame, _, _ = prepare_regression(data, spec)
    matrix, _, groups = regression_design(frame, spec)
    assert groups[-1] == {
        "role": "interaction",
        "predictors": [0, 1],
        "terms": ["x0_b0:x1_l0", "x0_b1:x1_l0"],
    }
    assert matrix.x0_b0.iloc[0] == -3  # (10 years - 40 years) / 10 years
    anchor, _, _ = regression_design(
        pd.DataFrame({"x0": [40], "x1": ["A"]}), spec, check_rank=False
    )
    np.testing.assert_array_equal(anchor.iloc[0].to_numpy(), [1, 0, 0, 0, 0, 0])
    scaled = deepcopy(spec.to_dict())
    scaled["predictors"][0]["increment"] = 1
    changed, _, _ = regression_design(frame, RegressionSpec.parse(scaled))
    age_terms = [c for c in matrix if "x0_" in c]
    np.testing.assert_allclose(changed[age_terms], 10 * matrix[age_terms])
    np.testing.assert_array_equal(changed[["intercept", "x1_l0"]], matrix[["intercept", "x1_l0"]])


@pytest.mark.parametrize(
    "fault",
    [
        "reversed_interaction",
        "missing_main",
        "unordered_knots",
        "nonpositive_increment",
        "boolean_reference",
        "extra_key",
        "role_collision",
        "false_independence",
    ],
)
def test_ambiguous_or_unapproved_specs_fail_before_design_construction(fault):
    _, spec = fixture()
    options = spec.to_dict()
    if fault == "reversed_interaction":
        options["interactions"].append(["group", "age"])
    elif fault == "missing_main":
        options["interactions"] = [["age", "unknown"]]
    elif fault == "unordered_knots":
        options["predictors"][0]["knots"] = [40, 20, 60]
    elif fault == "nonpositive_increment":
        options["predictors"][0]["increment"] = 0
    elif fault == "boolean_reference":
        options["predictors"][0]["reference"] = True
    elif fault == "extra_key":
        options["predictors"][1]["auto_reference"] = True
    elif fault == "role_collision":
        options["subject"] = "age"
    else:
        options["independent_rows"] = False
    with pytest.raises(ValueError):
        RegressionSpec.parse(options)


def test_missing_reference_levels_and_rank_deficiency_are_not_silently_repaired():
    data, spec = fixture()
    data.loc[data.group == "A", "result"] = np.nan
    with pytest.raises(ValueError, match="Every declared predictor category"):
        regression_preflight(data, spec)
    data, spec = fixture()
    data["copy_of_age"] = data.age
    predictors = deepcopy(spec.predictors)
    predictors.append({**deepcopy(predictors[0]), "column": "copy_of_age"})
    with pytest.raises(ValueError, match="rank-deficient"):
        regression_preflight(data, replace(spec, predictors=predictors))
    data, spec = fixture()
    data["result"] = np.resize(["low", "medium", "high"], 40)
    frame, _, _ = prepare_regression(
        data, replace(spec, distribution="ordinal", outcome_levels=["low", "medium", "high"])
    )
    frame["x0"] = 41.0
    with pytest.raises(ValueError, match="ordinal intercept"):
        regression_design(
            frame, replace(spec, distribution="ordinal", outcome_levels=["low", "medium", "high"])
        )
