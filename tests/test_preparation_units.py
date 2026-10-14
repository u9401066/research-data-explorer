"""Unit declarations are explicit even when numeric values need no conversion."""

import uuid
from copy import deepcopy
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from rde.domain.models.preparation import Feature
from rde.infrastructure.preparation import workflow
from test_preparation_engine import evaluate, source


def numeric_feature(**changes):
    return {
        "output": "average_value",
        "column": "value",
        "aggregate": "mean",
        "value_type": "number",
        **changes,
    }


def unit_case(tmp_path, units=("U", "U", "U"), values=(2, 4, 6)):
    inputs = [
        source(tmp_path, "roots", ["id"], [["R1"]]),
        source(
            tmp_path,
            "events",
            ["event_id", "root_id", "value", "unit"],
            [[f"E{i}", "R1", value, unit] for i, (value, unit) in enumerate(zip(values, units))],
        ),
    ]
    specification = {
        "unit": {"source_id": "roots", "kind": "event", "keys": ["id"], "subject_keys": ["id"]},
        "relations": [
            {
                "id": "measurements",
                "source_id": "events",
                "left_keys": ["id"],
                "right_keys": ["root_id"],
                "record_keys": ["event_id"],
                "kind": "events",
                "coverage": {"mode": "complete"},
                "features": [
                    numeric_feature(
                        unit_column="unit",
                        unit_conversions={"U": {"scale": 1, "offset": 0}},
                        output_unit="U",
                    )
                ],
                "reason": "Synthetic symbolic-unit arithmetic with an explicit mapping",
            }
        ],
        "definitions": {
            "unit": "One synthetic root record",
            "linkage": "Exact synthetic root IDs",
            "time": "All-time descriptive aggregation, no availability assertion",
            "missingness": "Missing values stay missing, undeclared units are not inferred",
        },
    }
    return inputs, specification


@pytest.mark.parametrize(
    "changes,accepted",
    [
        ({}, True),
        ({"unit_column": None}, True),
        ({"unit_column": ""}, True),  # Preserve the existing native truthiness boundary.
        ({"unit_column": "unit"}, False),
        ({"unit_column": "unit", "output_unit": "U"}, False),
        ({"unit_column": "unit", "unit_conversions": {"U": {}}}, False),
        ({"unit_column": "unit", "unit_conversions": {"U": {}}, "output_unit": ""}, False),
        (
            {
                "unit_column": "unit",
                "unit_conversions": {"U": {"scale": 1, "offset": 0}},
                "output_unit": "U",
            },
            True,
        ),
    ],
)
def test_discovered_unit_condition_matches_existing_native_validator(changes, accepted):
    feature = numeric_feature(**changes)
    contract = workflow.execute(None, {"op": "contract"})
    schemas = [contract["specification"]] + [
        contract["aggregation"][key]
        for key in ["operation_schema", "compose_schema", "patch_schema"]
    ]
    for schema in schemas:
        validator = Draft202012Validator({"$ref": "#/$defs/Feature", "$defs": schema["$defs"]})
        assert validator.is_valid(feature) is accepted
    if accepted:
        Feature.model_validate(feature)
    else:
        with pytest.raises(ValidationError, match="unit_column"):
            Feature.model_validate(feature)


def test_discovery_explains_identity_mappings_and_filters_without_inventing_factors():
    contract = workflow.execute(None, {"op": "contract"})
    assert (
        contract["execution_semantics"]["unit_conversion"]
        == contract["aggregation"]["execution_semantics"]["unit_conversion"]
    )
    semantics = contract["execution_semantics"]["unit_conversion"]
    assert '"U": {"scale": 1, "offset": 0}' in semantics
    assert "filters" in semantics and "never inferred" in semantics
    fields = contract["specification"]["$defs"]["Feature"]["properties"]
    for name in ["unit_column", "unit_conversions", "output_unit"]:
        assert fields[name]["description"]
    assert "identity" in fields["unit_conversions"]["description"]
    conversion = contract["specification"]["$defs"]["UnitConversion"]["properties"]
    assert conversion["scale"]["default"] == 1
    assert conversion["offset"]["default"] == 0


def test_explicit_identity_mapping_preserves_values_and_contributing_row_trace(tmp_path):
    inputs, specification = unit_case(tmp_path)
    result = evaluate(inputs, specification)
    assert result.summary()["ready_for_approval"], result.issues
    assert result.rows[0]["average_value"] == 4  # Independent arithmetic: (2 + 4 + 6) / 3.
    cell = result.trace[result.rows[0]["_rde_unit_id"]]["cells"]["average_value"]
    assert cell["rule"]["unit_conversions"] == {"U": {"scale": 1, "offset": 0}}
    assert [r["record_index"] for r in cell["sources"]] == [0, 1, 2]
    assert all(r["source_sha256"] == inputs[1].sha256 for r in cell["sources"])


@pytest.mark.parametrize("units", [("V", "V", "V"), ("U", "", "U"), ("U", "V", "U")])
def test_unknown_missing_and_unmapped_mixed_units_still_block(tmp_path, units):
    inputs, specification = unit_case(tmp_path, units=units)
    result = evaluate(inputs, specification)
    assert not result.summary()["ready_for_approval"]
    assert result.rows[0]["average_value"] is None
    issues = [issue for issue in result.issues if issue["severity"] == "blocker"]
    assert len(issues) == 1
    assert issues[0]["code"] == "RELATION_VALUE_ERROR"
    assert issues[0]["relation_id"] == "measurements"
    assert issues[0]["feature_output"] == "average_value"
    assert "unmapped unit" in issues[0]["message"]


def test_explicit_reviewed_mixed_mapping_is_not_prohibited(tmp_path):
    inputs, specification = unit_case(tmp_path, units=("U", "V", "U"))
    specification["relations"][0]["features"][0]["unit_conversions"]["V"] = {
        "scale": 2,
        "offset": 0,
    }
    result = evaluate(inputs, specification)
    assert result.summary()["ready_for_approval"], result.issues
    assert result.rows[0]["average_value"] == 16 / 3  # (2 + 4*2 + 6) / 3, declared factors only.


def test_filter_selects_records_but_does_not_supply_mapping(tmp_path):
    inputs, specification = unit_case(tmp_path, units=("U", "V", "U"))
    specification["relations"][0]["filters"] = [{"column": "unit", "op": "eq", "value": "U"}]
    result = evaluate(inputs, specification)
    assert result.summary()["ready_for_approval"], result.issues
    assert result.rows[0]["average_value"] == 4  # Only values 2 and 6 remain.
    specification["relations"][0]["features"][0]["unit_conversions"] = {}
    with pytest.raises(ValidationError, match="filters do not supply a mapping"):
        evaluate(inputs, specification)


@pytest.mark.parametrize("missing", ["unit_conversions", "output_unit", "both"])
def test_atomic_patch_rejection_names_missing_fields_and_keeps_exact_candidate(tmp_path, missing):
    inputs, specification = unit_case(tmp_path)
    project = SimpleNamespace(id="symbolic-unit-test", output_dir=tmp_path / "out")
    candidate = workflow.execute(
        project,
        {
            "op": "aggregation_compose",
            "candidate_id": str(uuid.uuid4()),
            "revision_id": str(uuid.uuid4()),
            "sources": [s.model_dump() for s in inputs],
            "from_specification": specification,
            "author": "synthetic-reviewer",
            "reason": "Declared synthetic identity mapping",
        },
    )
    feature = deepcopy(specification["relations"][0]["features"][0])
    for name in ["unit_conversions", "output_unit"]:
        if missing in (name, "both"):
            feature.pop(name)
    result = workflow.execute(
        project,
        {
            "op": "aggregation_patch",
            "candidate_ref": candidate["candidate_ref"],
            "revision_id": str(uuid.uuid4()),
            "author": "synthetic-reviewer",
            "reason": "Intentional invalid rule to verify atomic rejection",
            "operations": [
                {
                    "op": "filters_set",
                    "relation_id": "measurements",
                    "filters": [{"column": "unit", "op": "eq", "value": "U"}],
                },
                {"op": "feature_set", "relation_id": "measurements", "feature": feature},
            ],
        },
    )
    assert result["status"] == "rejected"
    assert result["candidate_ref"] == candidate["candidate_ref"]
    assert len(result["diagnostics"]) == 1
    issue = result["diagnostics"][0]
    assert issue["code"] == "INVALID_RULE" and issue["errorStage"] == "schema"
    assert issue["relation_id"] == "measurements" and issue["feature_output"] == "average_value"
    assert issue["rule_path"] == ["operations", "1", "feature_set", "feature"]
    names = ["unit_conversions", "output_unit"] if missing == "both" else [missing]
    assert f"Missing: {', '.join(names)}." in issue["message"]
    assert '"U": {"scale": 1, "offset": 0}' in issue["message"]
    assert (
        workflow.execute(
            project, {"op": "aggregation_read", "candidate_ref": candidate["candidate_ref"]}
        )
        == candidate
    )
