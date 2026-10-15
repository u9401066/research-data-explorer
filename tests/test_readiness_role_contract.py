"""Readiness uses reviewed research roles, never incidental column usage."""

from copy import deepcopy

import pytest

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.tools.report_tools import (
    _evaluate_analysis_depth,
    _evaluate_report_readiness,
)


def context(tmp_path, *, roles=None, analyses=None, locked=True):
    store = ArtifactStore(tmp_path / "artifacts")
    store.save(
        PipelinePhase.SCHEMA_REGISTRY,
        "schema.json",
        {
            "variables": [
                {"name": name, "variable_type": "continuous"}
                for name in ["lactate", "age", "sofa_score", "treatment", "mortality"]
            ]
        },
    )
    store.save(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json", roles or {})
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {"locked": locked, "analyses": analyses or []},
    )
    return store


def required(depth, name):
    return next(check for check in depth["checks"] if check["id"] == name)["required"]


def test_completed_field_scans_cannot_reassign_confirmed_outcome_or_covariates(tmp_path):
    roles = {
        "confirmed": True,
        "role_assignment_source": "user",
        "outcome": ["lactate"],
        "group": ["treatment"],
        "covariates": ["age", "sofa_score"],
        "unassigned": ["mortality"],
        "variable_roles": {
            "lactate": "outcome",
            "treatment": "group",
            "age": "covariate",
            "sofa_score": "covariate",
            "mortality": "unassigned",
        },
    }
    analyses = [
        {"type": kind, "variables": ["lactate", "treatment", "age", "sofa_score"]}
        for kind in ["analyze_variable", "visualization", "correlation_matrix"]
    ] + [
        {
            "type": "run_advanced_analysis",
            "analysis_type": "multiple_regression",
            "variables": ["lactate", "age", "sofa_score"],
            "target_variable": "lactate",
            "covariates": ["age", "sofa_score"],
        }
    ]
    store = context(tmp_path, roles=roles, analyses=analyses)
    original = deepcopy(store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json"))
    depth = _evaluate_analysis_depth({"total_analyses": 18}, store)
    assert depth["outcome_variables"] == ["lactate"]
    assert depth["group_variables"] == ["treatment"]
    assert depth["covariates"] == ["age", "sofa_score"]
    assert depth["role_evidence"]["unassigned_variables"] == ["mortality"]
    assert required(depth, "multivariable")
    assert "multivariable" in depth["missing_requirements"]
    assert store.load(PipelinePhase.CONCEPT_ALIGNMENT, "variable_roles.json") == original


@pytest.mark.parametrize("confirmed", [False, None, "true"])
def test_unconfirmed_roles_and_unlocked_proposals_do_not_authorize_inferred_models(
    tmp_path, confirmed
):
    store = context(
        tmp_path,
        roles={"confirmed": confirmed, "outcome": ["mortality"], "covariates": ["age"]},
        analyses=[
            {"type": "multiple_regression", "target_variable": "mortality", "covariates": ["age"]}
        ],
        locked=False,
    )
    depth = _evaluate_analysis_depth({}, store)
    assert depth["outcome_variables"] == depth["group_variables"] == depth["covariates"] == []
    assert not required(depth, "multivariable")
    assert depth["role_evidence"]["unassigned_variables"] == [
        "lactate",
        "age",
        "sofa_score",
        "treatment",
        "mortality",
    ]


@pytest.mark.parametrize(
    "kind",
    [
        "analyze_variable",
        "visualization",
        "correlation_matrix",
        "run_advanced_analysis",
        "unknown_method",
    ],
)
def test_generic_variables_never_mean_research_outcomes_or_predictors(tmp_path, kind):
    store = context(
        tmp_path, analyses=[{"type": kind, "variables": ["mortality", "treatment", "age"]}]
    )
    depth = _evaluate_analysis_depth({}, store)
    assert depth["outcome_variables"] == depth["group_variables"] == depth["covariates"] == []
    assert not required(depth, "multivariable")


def test_unused_schema_columns_do_not_create_unplanned_adjustment_requirement(tmp_path):
    store = context(
        tmp_path, roles={"confirmed": True, "outcome": ["lactate"], "group": ["treatment"]}
    )
    depth = _evaluate_analysis_depth({}, store)
    assert depth["covariates"] == []
    assert not required(depth, "multivariable")


def test_multiple_locked_outcomes_keep_predictors_that_are_another_models_outcome(tmp_path):
    store = context(
        tmp_path,
        analyses=[
            {
                "type": "compare_groups",
                "variables": ["lactate", "sofa_score"],
                "group_variable": "treatment",
            },
            {
                "type": "run_advanced_analysis",
                "execution_arguments": {
                    "target_variable": "lactate",
                    "covariates": ["sofa_score", "age"],
                },
            },
        ],
    )
    depth = _evaluate_analysis_depth({}, store)
    assert depth["outcome_variables"] == ["lactate", "sofa_score"]
    assert depth["group_variables"] == ["treatment"]
    assert depth["covariates"] == ["sofa_score", "age"]
    assert required(depth, "multivariable")


def test_role_prose_substrings_and_unassigned_map_are_not_bindings(tmp_path):
    store = context(
        tmp_path,
        roles={
            "confirmed": True,
            "not_an_outcome": ["mortality"],
            "covariate_notes": "age",
            "variable_roles": {"mortality": "not an outcome", "age": "unassigned"},
        },
    )
    depth = _evaluate_analysis_depth({}, store)
    assert depth["outcome_variables"] == depth["covariates"] == []


@pytest.mark.parametrize("family", ["imputation", "stratified", "noninferiority", "matching"])
def test_typed_clinical_readiness_ignores_generic_schema_depth_guessing(
    tmp_path, monkeypatch, family
):
    from test_clinical_evidence_inventory import setup
    import rde.interface.mcp.tools.report_tools as reports

    _, store, _, _ = setup(tmp_path, family)
    # This is an exact locked native family, not an untyped list of variables.
    # Missing its numerical receipt must remain blocked by its own contract.
    monkeypatch.setattr(
        reports,
        "_evaluate_analysis_depth",
        lambda *a, **k: pytest.fail("Typed clinical fell through to generic role inference"),
    )
    readiness = _evaluate_report_readiness({}, store, require_report_generation=False)
    assert readiness["ready"] is False
    assert readiness["scope"] == "clinical_study_report_evidence"
    assert "outcome_variables" not in readiness["analysis_depth"]
    assert any(
        "single_completed_clinical_receipt" in str(item)
        for item in readiness["missing_requirements"]
    )
