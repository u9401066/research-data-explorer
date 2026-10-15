"""True MCP Phase 4→6 dispatch for typed studies; no model or estimator calls."""

import asyncio
from copy import deepcopy

import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.server import create_server
from test_clinical_imputation import fixture as mi_fixture
from test_clinical_noninferiority import means_fixture
from test_clinical_stratified import fixture as cmh_fixture
from test_matching_candidate import matching_fixture


def call(name, args, denied=False):
    response = asyncio.run(create_server().call_tool(name, args))
    assert response.is_error is denied, response.content
    return response.content[0].text


def setup(tmp_path, family):
    frame, spec = {
        "matching": matching_fixture,
        "imputation": mi_fixture,
        "stratified": cmh_fixture,
        "noninferiority": lambda: means_fixture()[:2],
    }[family]()
    raw = tmp_path / "raw"
    raw.mkdir()
    frame.to_csv(raw / "synthetic.csv", index=False)
    call("init_project", {"name": "typed-proposal", "data_dir": str(raw)})
    project = get_session().get_project()
    call("run_intake", {"project_id": project.id, "directory": str(raw), "allow_pii": True})
    dataset_id = get_session().list_datasets()[0]
    base = {"project_id": project.id, "dataset_id": dataset_id}
    call("build_schema", base)
    call(
        "align_concept",
        {
            **base,
            "research_question": "Prespecified synthetic clinical contract validation only",
            "variable_roles": {"outcome": spec.outcome, "id": spec.subject},
            "confirm": True,
        },
    )
    return base, ArtifactStore(project.artifacts_dir), spec


def register(base, spec):
    return {
        "project_id": base["project_id"],
        "analyses": [
            {
                "type": "run_clinical_study",
                "variables": spec.variables(),
                "rationale": "Prespecified synthetic contract",
                "execution_arguments": {"clinical_options": spec.to_dict()},
            }
        ],
        "alpha": 1 - spec.confidence_level,
        "multiple_comparison_method": "none",
        "missing_strategy": "multiple_imputation" if spec.family == "imputation" else "listwise",
        "confirm": True,
    }


@pytest.mark.parametrize("family", ["imputation", "stratified", "noninferiority", "matching"])
def test_typed_proposal_draft_confirm_and_registration_match_exact_method(tmp_path, family):
    base, store, spec = setup(tmp_path, family)
    args = {**base, "clinical_options": spec.to_dict(), "max_analyses": 1}
    text = call("propose_analysis_plan", args)
    draft = store.load(PipelinePhase.CREATIVE_IDEATION, "greedy_analysis_candidates.json")
    assert draft["confirmed"] is False and draft["candidate_pool_size"] == 1
    assert draft["plan_blueprint"][0]["execution_arguments"]["clinical_options"] == spec.to_dict()
    assert [s["tool_name"] for s in draft["execution_schedule"]] == ["run_clinical_study"]
    assert draft["review"]["numerical_evidence"] == "not_executed"
    assert draft["review"]["clinical_validation"] == "not_performed"
    assert "樣本數與檢定力未由分析項目數量證明" in text
    assert "待審閱" in text and "尚未確認或鎖定" in text
    for unintended in ["underpowered", "apply_cleaning", "generate_table_one", "compare_groups"]:
        assert unintended not in text
        assert unintended not in str(draft)
    assert "confirmed" in call("register_analysis_plan", register(base, spec), denied=True)
    confirmed_text = call("propose_analysis_plan", {**args, "confirm": True})
    confirmed = store.load(PipelinePhase.CREATIVE_IDEATION, "greedy_analysis_candidates.json")
    assert confirmed["confirmed"] is True and "仍須登錄及鎖定" in confirmed_text
    assert {k: v for k, v in confirmed.items() if k not in {"confirmed", "confirmed_at"}} == {
        k: v for k, v in draft.items() if k != "confirmed"
    }
    call("register_analysis_plan", register(base, spec))
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    assert plan["locked"] is True and len(plan["analyses"]) == 1
    assert plan["analyses"][0]["execution_arguments"]["clinical_options"] == spec.to_dict()
    schedule = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_execution_schedule.json")
    assert [step["tool_name"] for step in schedule] == ["run_clinical_study"]


@pytest.mark.parametrize("family", ["imputation", "stratified", "noninferiority", "matching"])
def test_typed_confirmation_and_registration_reject_changed_or_missing_contract(tmp_path, family):
    base, store, spec = setup(tmp_path, family)
    args = {**base, "clinical_options": spec.to_dict()}
    assert "existing unconfirmed draft" in call(
        "propose_analysis_plan", {**args, "confirm": True}, denied=True
    )
    call("propose_analysis_plan", args)
    path = store.get_path(PipelinePhase.CREATIVE_IDEATION, "greedy_analysis_candidates.json")
    before = path.read_bytes()
    assert "same clinical_options" in call(
        "propose_analysis_plan", {**base, "confirm": True}, denied=True
    )
    changed = deepcopy(args)
    if family == "noninferiority":
        changed["clinical_options"]["margin"] += 1
    elif family == "matching":
        changed["clinical_options"]["caliper_sd"] = 0.5
    elif family == "imputation":
        changed["clinical_options"]["seed"] += 1
    else:
        changed["clinical_options"]["treatment_levels"].reverse()
    assert "draft and review again" in call(
        "propose_analysis_plan", {**changed, "confirm": True}, denied=True
    )
    assert path.read_bytes() == before
    call("propose_analysis_plan", {**args, "confirm": True})
    registration = register(base, spec)
    registration["analyses"][0]["execution_arguments"]["clinical_options"] = changed[
        "clinical_options"
    ]
    assert "differ from the confirmed proposal" in call(
        "register_analysis_plan", registration, denied=True
    )
    registration["analyses"] = [{"type": "compare_groups", "variables": [spec.outcome]}]
    # Generic policy does not authorize replacement of a reviewed typed study.
    registration["missing_strategy"] = "listwise"
    registration["multiple_comparison_method"] = "holm"
    assert "cannot replace" in call("register_analysis_plan", registration, denied=True)
    assert not store.exists(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")


@pytest.mark.parametrize("invalid", ["unknown_option", "unknown_column", "unsupported_method"])
def test_invalid_typed_proposal_does_not_fall_back_to_generic_or_write_success(tmp_path, invalid):
    base, store, spec = setup(tmp_path, "noninferiority")
    options = spec.to_dict()
    if invalid == "unknown_option":
        options["pretend_success"] = True
    elif invalid == "unknown_column":
        options["outcome"] = "not_in_source"
    else:
        options["method"] = "binary_risk_difference"
    call("propose_analysis_plan", {**base, "clinical_options": options}, denied=True)
    assert not store.exists(PipelinePhase.CREATIVE_IDEATION, "greedy_analysis_candidates.json")
