"""Real MCP regressions for source-aware replay and non-shrinkable evidence."""

import asyncio
from copy import deepcopy
import json

import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools._shared.clinical_artifacts import CONTRACT
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
from test_missing_stratified_workflow import fixture as standard_fixture, unlocked_project


def invoke(name, args):
    return asyncio.run(create_server().call_tool(name, args))


def setup(tmp_path, family):
    if family == "matching":
        from test_matching_workflow import setup as build
    elif family == "noninferiority":
        from test_noninferiority_workflow import fixture as build
    elif family == "weighting":
        from test_weighting_workflow import project_fixture as build
    elif family == "survival":
        from test_clinical_survival import clinical_project as build
    else:
        return standard_fixture(tmp_path, family)
    return build(tmp_path)


@pytest.mark.parametrize(
    "family", ["imputation", "stratified", "noninferiority", "matching", "weighting", "survival"]
)
@pytest.mark.parametrize("damage", ["source", "frame"])
def test_inspection_replay_rechecks_exact_source_without_fit(tmp_path, monkeypatch, family, damage):
    project, store, dataset, spec = setup(tmp_path, family)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict(), "execution_key": "c" * 64}
    first = invoke("inspect_clinical_study", args)
    assert not first.is_error, first.content
    again = invoke("inspect_clinical_study", args)
    assert (
        not again.is_error
        and again.structured_content["invocation_id"] == first.structured_content["invocation_id"]
    )
    operation = project.output_dir / ".rde_operations" / args["execution_key"] / "result.json"
    frozen = operation.read_bytes()
    if damage == "source":
        dataset.metadata.file_path.write_bytes(dataset.metadata.file_path.read_bytes() + b"\n")
    else:
        # Same source bytes, changed live loaded representation, including a field
        # irrelevant to the fitted model: provenance still must not be reused.
        get_session().get_dataset_entry(dataset.id).dataframe["new_unreviewed_field"] = 17
    denied = invoke("inspect_clinical_study", args)
    assert denied.is_error and "CLINICAL_REPLAY_SOURCE" in denied.content[0].text
    assert operation.read_bytes() == frozen
    fresh = invoke(
        "inspect_clinical_study", {k: v for k, v in args.items() if k != "execution_key"}
    )
    assert not fresh.is_error, fresh.content
    assert (
        fresh.structured_content["data"]["source_identity"]
        != first.structured_content["data"]["source_identity"]
    )
    assert not clinical_records(store)


@pytest.mark.parametrize("family", ["imputation", "stratified"])
@pytest.mark.parametrize("damage", ["source", "frame", "plan"])
def test_locked_plan_replay_checks_its_original_source_and_bytes(tmp_path, family, damage):
    project, store, dataset, spec = unlocked_project(tmp_path, family)
    args = {
        "project_id": project.id,
        "analyses": [
            {
                "type": "run_clinical_study",
                "variables": spec.variables(),
                "execution_arguments": {"clinical_options": spec.to_dict()},
            }
        ],
        "confirm": True,
        "alpha": 0.05,
        "multiple_comparison_method": "none",
        "missing_strategy": "multiple_imputation" if family == "imputation" else "listwise",
        "execution_key": "d" * 64,
    }
    first = invoke("register_analysis_plan", args)
    assert not first.is_error, first.content
    again = invoke("register_analysis_plan", args)
    assert (
        not again.is_error
        and again.structured_content["invocation_id"] == first.structured_content["invocation_id"]
    )
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    assert plan["clinical_source_identity"]["dataset_id"] == dataset.id
    operation = project.output_dir / ".rde_operations" / args["execution_key"] / "result.json"
    original = operation.read_bytes()
    if damage == "source":
        dataset.metadata.file_path.write_bytes(dataset.metadata.file_path.read_bytes() + b"\n")
    elif damage == "frame":
        get_session().get_dataset_entry(dataset.id).dataframe["unreviewed"] = 19
    else:
        plan["research_question"] = "changed after approval"
        store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    rejected = invoke("register_analysis_plan", args)
    assert rejected.is_error and "CLINICAL_REPLAY_" in rejected.content[0].text
    assert operation.read_bytes() == original


@pytest.mark.parametrize("family", ["stratified", "matching"])
def test_complete_inventory_cannot_shrink_or_duplicate_on_any_replay(tmp_path, monkeypatch, family):
    from rde.infrastructure.clinical import stratified, matching, report

    project, store, dataset, spec = setup(tmp_path, family)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict(), "execution_key": "e" * 64}
    first = invoke("run_clinical_study", args)
    assert not first.is_error, first.content
    record = clinical_records(store)[0]
    assert record["artifact_contract"] == CONTRACT
    manifest = record["artifact_manifest"]
    assert manifest in record["artifacts"]
    retained = first.structured_content["artifacts"]
    assert any(ref["relative_path"].endswith(manifest["path"]) for ref in retained)
    assert any(ref["relative_path"].endswith(record["artifact"]) for ref in retained)
    assert not invoke("collect_results", {"project_id": project.id}).is_error
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    record_path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen = record_path.read_bytes()
    operation = project.output_dir / ".rde_operations" / args["execution_key"] / "result.json"
    sealed_operation = operation.read_bytes()

    def forbidden(*a, **kw):
        pytest.fail("Validation refitted or rebuilt immutable evidence")

    monkeypatch.setattr(stratified, "run_stratified", forbidden)
    monkeypatch.setattr(matching, "run_matching", forbidden)
    monkeypatch.setattr(report, "figures", forbidden)
    for damage in ["table", "figure", "report", "manifest", "duplicate", "legacy", "empty"]:
        changed = json.loads(frozen)
        removed = None
        if damage in {"table", "figure", "report", "manifest"}:
            role = {"table": "tables", "figure": "figures", "report": "report"}.get(damage)
            path = changed["artifact_roles"][role][0] if role else manifest["path"]
            removed = project.output_dir / path
            contents = removed.read_bytes()
            removed.unlink()
            changed["artifacts"] = [a for a in changed["artifacts"] if a["path"] != path]
            if role:
                changed["artifact_roles"][role].remove(path)
        elif damage == "duplicate":
            changed["artifacts"].append(deepcopy(manifest))
        elif damage == "legacy":
            changed.pop("artifact_contract")
        else:
            changed["artifacts"] = []
        record_path.write_text(json.dumps(changed), encoding="utf-8")
        assert not verify_clinical_artifacts(changed, project.output_dir), damage
        for replay_args in [args, {k: v for k, v in args.items() if k != "execution_key"}]:
            denied = invoke("run_clinical_study", replay_args)
            assert denied.is_error, (damage, denied.content)
        assert not _evaluate_report_readiness(summary, store, require_report_generation=False)[
            "ready"
        ], damage
        assert operation.read_bytes() == sealed_operation
        if removed:
            assert not removed.exists(), "Missing evidence was silently regenerated"
            removed.write_bytes(contents)
        record_path.write_bytes(frozen)
    assert not invoke("run_clinical_study", args).is_error
    assert record_path.read_bytes() == frozen


def test_source_change_after_new_approval_is_rejected_before_first_fit(tmp_path, monkeypatch):
    from rde.infrastructure.clinical import stratified
    from rde.interface.mcp.tools._shared.target_trial_replay import source_identity

    project, store, dataset, spec = setup(tmp_path, "stratified")
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan["clinical_source_identity"] = source_identity(get_session().get_dataset_entry(dataset.id))
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    dataset.metadata.file_path.write_bytes(dataset.metadata.file_path.read_bytes() + b"\n")
    monkeypatch.setattr(
        stratified, "run_stratified", lambda *a, **kw: pytest.fail("Unapproved data was fitted")
    )
    denied = invoke(
        "run_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    )
    assert denied.is_error and "CLINICAL_LOCKED_SOURCE" in denied.content[0].text
    assert not clinical_records(store)
