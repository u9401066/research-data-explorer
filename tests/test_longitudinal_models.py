"""Estimator invariants on synthetic observations; public studies use MCP separately."""

import numpy as np
import pandas as pd
import pytest

from rde.infrastructure.clinical.longitudinal import run_longitudinal
from rde.infrastructure.clinical.longitudinal_contract import LongitudinalSpec


def study(**updates):
    return LongitudinalSpec.parse(
        dict(
            outcome="y",
            subject="id",
            time="time",
            time_unit="year",
            time_origin="Centered observation time in the synthetic design",
            outcome_unit="source unit",
            context="Synthetic numerical regression fixture only",
            independent_subjects=True,
            method="gee",
            distribution="gaussian",
        )
        | updates
    )


def observations():
    rng = np.random.default_rng(94125)
    n, visits = 64, 6
    subjects = np.repeat(np.arange(n), visits)
    times = np.tile(np.arange(-2, 4), n)
    group = np.repeat(np.arange(n) % 2, visits)
    intercept = np.repeat(rng.normal(0, 2, n), visits)
    slope = np.repeat(rng.normal(0, 0.4, n), visits)
    means = 5 + 0.8 * times + 1.2 * group + 0.3 * times * group + intercept + slope * times
    return pd.DataFrame(
        dict(
            id=[f"person-{s}" for s in subjects],
            time=times,
            group=group,
            y=means + rng.normal(0, 0.5, n * visits),
            binary=rng.binomial(
                1, 1 / (1 + np.exp(-(0.2 + 0.2 * times + 0.3 * group + intercept / 4)))
            ),
            count=rng.poisson(np.exp(0.2 + 0.1 * times + 0.3 * group + intercept / 5)),
            exposure=np.exp(rng.normal(0, 0.2, n * visits)),
        )
    )


def points_by_row(result):
    return sorted(result["points"], key=lambda row: row["data_row"])


def test_balanced_categorical_time_group_gee_matches_cell_means_and_partial_visits():
    source = observations()
    source.loc[0, "y"] = np.nan
    spec = study(
        group="group",
        group_reference="0",
        time_mode="categorical",
        time_levels=[-2, -1, 0, 1, 2, 3],
        time_by_group=True,
        correlation="independence",
    )
    result = run_longitudinal(source, spec)
    assert result["n"] == 383 and result["n_subjects"] == 64
    assert result["case_ledger"]["missing_excluded_data_rows"] == [1]
    cell_means = source.groupby(["time", "group"]).y.mean()
    for point in result["points"]:
        assert point["fitted"] == pytest.approx(
            cell_means[point["time"], int(point["group"])], abs=1e-10
        )
        assert point["observed"] == source.iloc[point["data_row"] - 1].y
    interactions = [row for row in result["coefficients"] if row["role"] == "interaction"]
    assert len(interactions) == 5
    assert {row["effect_scale"] for row in interactions} == {"difference in time effects"}
    assert len(result["multiplicity"]["family"]) == 11
    assert all(r["p_adjusted"] >= r["p_value"] for r in result["coefficients"][1:])


def test_binomial_explicit_label_reversal_preserves_rows_and_inverts_odds():
    source = observations().drop(columns="y").rename(columns={"binary": "y"})
    options = dict(
        group="group",
        group_reference="0",
        time_by_group=True,
        distribution="binomial",
        positive="1",
        negative="0",
    )
    spec = study(**options)
    original = run_longitudinal(source, spec)
    reverse = run_longitudinal(
        source, LongitudinalSpec.parse({**spec.to_dict(), "positive": "0", "negative": "1"})
    )
    assert original["case_ledger"] == reverse["case_ledger"]
    for a, b in zip(original["coefficients"], reverse["coefficients"], strict=True):
        assert a["coefficient"] == pytest.approx(-b["coefficient"], abs=1e-9)
        assert a["lower"] == pytest.approx(1 / b["upper"], rel=1e-8)
        assert a["p_value"] == pytest.approx(b["p_value"], abs=1e-8)
    for a, b in zip(original["points"], reverse["points"], strict=True):
        assert a["fitted"] == pytest.approx(1 - b["fitted"], abs=1e-9)
    assert original["coefficients"][-1]["effect_scale"] == "ratio of odds ratios"
    assert original["coefficients"][0]["effect_scale"] == "reference odds"


def test_poisson_offset_unit_change_preserves_fitted_counts_and_rate_ratios():
    source = observations().drop(columns="y").rename(columns={"count": "y"})
    spec = study(distribution="poisson", exposure="exposure", exposure_unit="year")
    original = run_longitudinal(source, spec)
    converted = source.copy()
    converted.exposure *= 12
    changed = run_longitudinal(
        converted, LongitudinalSpec.parse({**spec.to_dict(), "exposure_unit": "month"})
    )
    assert changed["coefficients"][0]["coefficient"] == pytest.approx(
        original["coefficients"][0]["coefficient"] - np.log(12)
    )
    assert changed["coefficients"][1]["estimate"] == pytest.approx(
        original["coefficients"][1]["estimate"]
    )
    assert [p["fitted"] for p in changed["points"]] == pytest.approx(
        [p["fitted"] for p in original["points"]]
    )
    assert changed["coefficients"][1]["effect_scale"] == "rate ratio"
    no_offset = run_longitudinal(source, study(distribution="poisson"))
    assert no_offset["coefficients"][1]["effect_scale"] == "mean count ratio"


def test_mixed_random_slope_time_recentering_preserves_predictions_and_covariance_mapping():
    source = observations()
    spec = study(
        method="mixed",
        correlation=None,
        random_slope=True,
        group="group",
        group_reference="0",
        time_by_group=True,
    )
    original = run_longitudinal(source, spec)
    changed = run_longitudinal(
        source, LongitudinalSpec.parse({**spec.to_dict(), "time_reference": 1})
    )
    assert original["model"]["estimation"] == "REML"
    assert original["model"]["converged"] and changed["model"]["converged"]
    assert [r["fitted"] for r in points_by_row(original)] == pytest.approx(
        [r["fitted"] for r in points_by_row(changed)], abs=3e-5
    )
    transform = np.array([[1, 1], [0, 1]])
    assert np.array(changed["random_effects"]["covariance"]) == pytest.approx(
        transform @ np.array(original["random_effects"]["covariance"]) @ transform.T, abs=3e-4
    )
    assert len(original["random_effects"]["conditional_modes"]) == 64
    assert "person-" not in str(original["points"]) + str(original["random_effects"])
