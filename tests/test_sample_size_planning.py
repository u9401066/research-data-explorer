"""Prospective design edge cases and independent R reference values."""

from copy import deepcopy
import json
from math import gcd
from pathlib import Path

import pytest

from rde.domain.models.sample_size import SampleSizeSpec
from rde.infrastructure.clinical.sample_size import calculate_sample_size, design_power


def planning_spec(design="independent_means"):
    refs = {f"{role}_source_ids": ["qa"] for role in ("effect", "nuisance", "loss")}
    numeric = (
        {"probabilities": [0.4, 0.55]}
        if design == "independent_proportions"
        else {"difference": 5, "sd": 10}
    )
    return SampleSizeSpec.parse(
        {
            "design": design,
            "population": "Synthetic planning fixture; not a clinical recommendation",
            "endpoint": "Prespecified test outcome",
            "time_horizon": "At 30 days",
            "outcome_unit": "probability"
            if design == "independent_proportions"
            else "score points",
            "contrast": "Group/measurement 1 minus group/measurement 2",
            "group_labels": ["Group 1", "Group 2"],
            "independent_units": True,
            "normal_model": {
                "paired_means": "normal_differences",
                "independent_means": "common_normal_sd",
                "independent_proportions": "not_applicable",
            }[design],
            "alpha": 0.05,
            "target_power": 0.8,
            "allocation": None if design == "paired_means" else [1, 1],
            "max_evaluable": 100000,
            "sources": [
                {
                    "id": "qa",
                    "kind": "engineering_fixture",
                    "citation": "Explicit synthetic QA specification",
                    "locator": "tests/test_sample_size_planning.py planning_spec",
                    "justification": "Chosen for computational verification only; not a clinically established important difference.",
                }
            ],
            "design_source_ids": ["qa"],
            "primary_scenario_id": "primary",
            "scenarios": [
                {"id": "primary", "label": "Primary", "loss_rate": 0.1, **refs, **numeric}
            ],
        }
    )


def test_matches_independent_r_both_tails_and_unequal_allocation():
    reference = json.loads(
        (Path(__file__).parent / "fixtures/sample-size/reference.json").read_text()
    )
    for row in reference["rows"]:
        spec = planning_spec(row["design"]).to_dict()
        spec["alpha"] = row["alpha"]
        if row["design"] == "paired_means":
            blocks = row["pairs"]
        else:
            blocks = gcd(row["n1"], row["n2"])
            spec["allocation"] = [row["n1"] // blocks, row["n2"] // blocks]
        scenario = spec["scenarios"][0]
        if "d" in row:
            scenario.update(difference=row["d"], sd=1)
        else:
            scenario["probabilities"] = [row["p1"], row["p2"]]
        spec = SampleSizeSpec.parse(spec)
        assert design_power(spec, scenario, blocks) == pytest.approx(row["power"], abs=2e-11)


@pytest.mark.parametrize("design", ["independent_means", "paired_means", "independent_proportions"])
def test_integer_minimality_sensitivity_primary_identity_and_expected_retention(design):
    raw = planning_spec(design).to_dict()
    if design != "paired_means":
        raw["allocation"] = [2, 3]
    raw["scenarios"].append(
        {
            **deepcopy(raw["scenarios"][0]),
            "id": "sensitivity",
            "label": "Sensitivity",
            "loss_rate": 0.2,
        }
    )
    raw["scenarios"].reverse()  # Primary must not be inferred from position or minimum n.
    result = calculate_sample_size(SampleSizeSpec.parse(raw))
    assert [r["primary"] for r in result["scenarios"]] == [False, True]
    for row in result["scenarios"]:
        assert row["achieved_power"] >= raw["target_power"] > row["previous_allocation"]["power"]
        assert row["expected_retained_units"] >= row["evaluable"]["total_units"]
        assert row["evaluable"]["total_units"] <= raw["max_evaluable"]
        if design == "paired_means":
            assert row["evaluable"]["pairs"] == row["evaluable"]["total_units"]
            assert row["evaluable"]["group_1"] is None
        else:
            for counts in (row["evaluable"], row["enrollment"]):
                assert counts["group_1"] * 3 == counts["group_2"] * 2
        assert any(
            point["total_units"] == row["evaluable"]["total_units"]
            and point["power"] == row["achieved_power"]
            for point in row["power_curve"]
        )
    assert (
        result["scenarios"][0]["enrollment"]["total_units"]
        > result["scenarios"][1]["enrollment"]["total_units"]
    )


def test_rescaling_and_opposite_mean_difference_preserve_sample_size():
    raw = planning_spec().to_dict()
    baseline = calculate_sample_size(SampleSizeSpec.parse(raw))["scenarios"]
    raw["scenarios"][0].update(difference=-5000, sd=10000)
    scaled = calculate_sample_size(SampleSizeSpec.parse(raw))["scenarios"]
    assert scaled[0]["evaluable"] == baseline[0]["evaluable"]
    assert scaled[0]["achieved_power"] == baseline[0]["achieved_power"]


@pytest.mark.parametrize(
    "path,value",
    [
        (("alpha",), True),
        (("target_power",), float("nan")),
        (("alpha",), "0.05"),
        (("allocation",), [2, 2]),
        (("allocation",), [False, 1]),
        (("independent_units",), False),
        (("normal_model",), "welch"),
        (("purpose",), "post_hoc"),
        (("alternative",), "one-sided"),
        (("primary_scenario_id",), "missing"),
        (("max_evaluable",), 1000001),
        (("scenarios", 0, "difference"), 0),
        (("scenarios", 0, "sd"), 0),
        (("scenarios", 0, "loss_rate"), 1),
        (("scenarios", 0, "effect_source_ids"), []),
        (("scenarios", 0, "nuisance_source_ids"), ["missing"]),
        (("scenarios", 0, "sd"), float("inf")),
    ],
)
def test_rejects_unsupported_or_unjustified_assumptions(path, value):
    raw = planning_spec().to_dict()
    parent = raw
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValueError):
        SampleSizeSpec.parse(raw)


def test_no_implicit_defaults_or_fractional_solution_on_failure():
    raw = planning_spec().to_dict()
    del raw["alpha"]
    with pytest.raises(ValueError, match="Missing"):
        SampleSizeSpec.parse(raw)
    raw = planning_spec().to_dict()
    raw["max_evaluable"] = 100
    with pytest.raises(ValueError, match="cannot reach"):
        calculate_sample_size(SampleSizeSpec.parse(raw))


def test_exact_decimal_inflation_and_minimum_boundary():
    raw = planning_spec("paired_means").to_dict()
    raw["scenarios"][0].update(difference=1000, sd=10, loss_rate=0.8)
    row = calculate_sample_size(SampleSizeSpec.parse(raw))["scenarios"][0]
    assert row["evaluable"]["pairs"] == 2
    assert row["previous_allocation"] is None
    assert row["enrollment"]["pairs"] == 10  # Binary-float 2/(1-.8) would ceil to 11.


def test_rare_event_approximation_is_identified_in_receipt():
    raw = planning_spec("independent_proportions").to_dict()
    raw["scenarios"][0]["probabilities"] = [0.001, 0.2]
    row = calculate_sample_size(SampleSizeSpec.parse(raw))["scenarios"][0]
    assert min(row["expected_cells"]["alternative"]) < 10
    assert "不是精確檢定" in row["warnings"][0]
