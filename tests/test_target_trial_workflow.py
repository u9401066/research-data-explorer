"""Actual MCP target-trial plan/run/reuse/report gates over approved three-table sources."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import shutil
from pathlib import Path
import uuid

import pytest

from rde.application.pipeline import PipelinePhase, REQUIRED_ARTIFACTS
from rde.application.session import get_session
from rde.domain.models.project import Project
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.infrastructure.clinical.survival import digest
from rde.infrastructure.clinical.target_trial_contract import TargetTrialProtocol
from rde.infrastructure.clinical.target_trial_study import (
    TargetTrialSpec,
    run_target_trial,
    verify_target_trial_result,
)
from rde.infrastructure.clinical.target_trial_source import validate_target_trial_source
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
from test_exploration_branch_loop import _complete_phase
from test_target_trial_source import case


def call(name, args, *, error=None):
    response = asyncio.run(create_server().call_tool(name, args))
    text = response.content[0].text
    if error:
        assert response.is_error and error in text, text
    else:
        assert not response.is_error, text
    return text


def native_fixture(tmp_path, *, outcome="binary", mutate=None):
    c = case(tmp_path, outcome=outcome, mutate=mutate)
    raw = tmp_path / "native-intake"
    raw.mkdir()
    shutil.copyfile(c.release["dataset"]["path"], raw / "analysis.csv")
    project = Project(c.project.id, "Target trial native test", raw, c.project.output_dir)
    session = get_session()
    session.register_project(project)
    store = ArtifactStore(project.artifacts_dir)
    pipeline = session.get_pipeline(project.id)
    pipeline.mark_completed(
        _complete_phase(
            store, PipelinePhase.PROJECT_SETUP, {"project.yaml": {}}, user_confirmed=True
        )
    )
    call(
        "run_intake",
        {
            "directory": str(raw),
            "project_id": project.id,
            "prepared_source": {
                "bundle_path": c.bundle["path"],
                "bundle_sha256": c.bundle["sha256"],
                "release_sha256": c.release["receipt_sha256"],
            },
        },
    )
    entry = session.get_dataset_entry(project.dataset_ids[-1])
    dataset, frame = entry.dataset, entry.dataframe
    call("profile_dataset", {"dataset_id": dataset.id})
    call("assess_quality", {"dataset_id": dataset.id})
    call("build_schema", {"project_id": project.id, "dataset_id": dataset.id})
    for phase in [PipelinePhase.CONCEPT_ALIGNMENT]:
        pipeline.mark_completed(
            _complete_phase(
                store,
                phase,
                {
                    name: {"confirmed": True} if name.endswith((".json", ".yaml")) else ""
                    for name in REQUIRED_ARTIFACTS[phase]
                },
                user_confirmed=True,
            )
        )
    spec = TargetTrialSpec(c.spec, TargetTrialProtocol.parse(c.protocol))
    proposal_arguments = {
        "project_id": project.id,
        "dataset_id": dataset.id,
        "clinical_options": spec.to_dict(),
        "max_analyses": 1,
    }
    call("propose_analysis_plan", proposal_arguments)
    call("propose_analysis_plan", {**proposal_arguments, "confirm": True})
    return project, store, dataset, frame, spec


def args(dataset, spec):
    return {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}


def plan_args(project, spec, **policy):
    return {
        "project_id": project.id,
        "confirm": True,
        "alpha": 1 - spec.confidence_level,
        "missing_strategy": "listwise",
        "multiple_comparison_method": "none",
        "analyses": [
            {
                "type": "run_clinical_study",
                "variables": spec.variables(),
                "execution_arguments": {"clinical_options": spec.to_dict()},
            }
        ],
        **policy,
    }


def lock(project, spec):
    call("register_analysis_plan", plan_args(project, spec))
    call("check_readiness", {"project_id": project.id})


@pytest.mark.parametrize("outcome", ["binary", "continuous"])
def test_real_mcp_protocol_lock_weighting_equivalence_frozen_report_and_reuse(
    tmp_path, monkeypatch, outcome
):
    from rde.infrastructure.clinical import weighting
    from rde.infrastructure.clinical.target_trial_report import required_figures

    project, store, dataset, frame, spec = native_fixture(tmp_path, outcome=outcome)
    original_csv = dataset.metadata.file_path.read_bytes()
    direct = weighting.run_weighting(frame, spec.weighting)
    preflight = json.loads(call("inspect_clinical_study", args(dataset, spec)))
    assert preflight["schema"] == "target-trial-preflight-v1"
    assert preflight["spec"] == spec.to_dict()
    assert preflight["n"] == 60 and preflight["source_check"]["population"]["root_records"] == 61
    assert "rows" not in preflight["source_check"]
    preflight_path = project.output_dir / preflight["source_check"]["artifact"]["path"]
    assert len(json.loads(preflight_path.read_text())["rows"]) == 61
    assert not clinical_records(store)
    lock(project, spec)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    assert (
        plan["target_trial_source_check"]["receipt_sha256"]
        == preflight["source_check"]["receipt_sha256"]
    )
    changed = deepcopy(args(dataset, spec))
    changed["clinical_options"]["protocol"]["assignment"]["selection_basis"] = (
        "Changed source-assignment interpretation after locking"
    )
    call("run_clinical_study", changed, error="locked")
    call("run_clinical_study", args(dataset, spec))
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["weighting_result"] == direct
    assert result["case_ledger"] == preflight["case_ledger"]
    assert verify_target_trial_result(result) and verify_clinical_artifacts(
        record, project.output_dir
    )
    assert {f["plot_type"] for f in record["figures"]} == required_figures(result)
    for figure in record["figures"]:
        publication = figure["publication"]
        assert publication["source_receipt_sha256"] == (
            result["receipt_sha256"]
            if figure["plot_type"] == "clinical_target_trial_flow"
            else direct["receipt_sha256"]
        )
        assert set(publication["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        assert publication["text_outside_canvas"] == [] and publication["raster_dpi"] == 300
    assert dataset.metadata.file_path.read_bytes() == original_csv
    monkeypatch.setattr(
        weighting, "run_weighting", lambda *a, **k: pytest.fail("Cached/frozen evidence refitted")
    )
    assert "沒有重新估計" in call("run_clinical_study", args(dataset, spec))
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "基線目標試驗模擬" in report and "基線目標試驗結果解讀" in report
    assert "Eligibility" in report and "Assignment" in report and "不證明因果識別" in report
    assert result["receipt_sha256"] in report and direct["receipt_sha256"] in report
    assert _evaluate_report_readiness(summary, store)["ready"]
    from rde.interface.mcp.tools.report_tools import _figure_interpretation_harness_entry

    flow = _figure_interpretation_harness_entry(
        figure_no=1,
        plot_type="clinical_target_trial_flow",
        variables=[],
        stats_summary="",
        group_var="",
    )
    assert flow["evidence_role"] == "Source-verified baseline target-trial population flow"
    assert "do not prove" in flow["validity_caveat"]
    assert "zero additional" in flow["reportable_claim"]
    assert "separately linked original weighting" in flow["next_analysis"]
    if outcome == "binary":
        from zipfile import ZipFile
        from lxml import etree

        call(
            "export_report",
            {"project_id": project.id, "formats": "docx", "title": "Baseline target trial"},
        )
        documents = list(project.output_dir.rglob("*.docx"))
        assert documents
        with ZipFile(documents[-1]) as package:
            xml = etree.fromstring(package.read("word/document.xml"))
            text = "".join(
                xml.xpath(
                    "//w:t/text()",
                    namespaces={
                        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                    },
                )
            )
            assert "基線目標試驗" in text and "Eligibility" in text and "Assignment" in text
            assert "不證明因果識別" in text
            assert not any(
                term in text for term in ["Cox 比例風險", "Kaplan–Meier", "臨床事件結果解讀"]
            )
    artifact = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    original = artifact.read_bytes()
    edition = json.loads(
        call(
            "render_publication_figures",
            {
                "project_id": project.id,
                "study_artifact": artifact.name,
                "expected_record_sha256": hashlib.sha256(original).hexdigest(),
                "preset_id": "journal-neutral-english-v1",
                "edition_id": str(uuid.uuid4()),
                "start_number": 4,
            },
        )
    )
    assert artifact.read_bytes() == original
    for old, new in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(old["publication"]["files"]["data"]).read_bytes()
            == Path(new["publication"]["files"]["data"]).read_bytes()
        )
    source_folder = Path(dataset.metadata.preparation["folder"])
    raw = next((source_folder / "sources").glob("*.csv"))
    raw.write_bytes(raw.read_bytes() + b" ")
    call("run_clinical_study", args(dataset, spec), error="CORRUPT_PREPARATION")
    assert artifact.read_bytes() == original
    assert not _evaluate_report_readiness(summary, store)["ready"]
    failures = [
        store.load(PipelinePhase.EXECUTE_EXPLORATION, name)
        for name in store.list_phase_artifacts(PipelinePhase.EXECUTE_EXPLORATION)
        if name.startswith("clinical_attempt_")
    ]
    assert any(
        f.get("status") == "failed" and "CORRUPT_PREPARATION" in f.get("error", "")
        for f in failures
    )


@pytest.mark.parametrize("estimand", ["ATE", "ATT", "ATO"])
@pytest.mark.parametrize("outcome", ["binary", "continuous"])
def test_wrapper_does_not_change_any_weighting_number_or_covariance(tmp_path, estimand, outcome):
    from rde.infrastructure.clinical.weighting import run_weighting
    from rde.infrastructure.clinical.target_trial_contract import TargetTrialProtocol

    c = case(tmp_path, outcome=outcome)
    weighted = replace(c.spec, estimand=estimand)
    c.protocol["estimand"]["kind"] = estimand
    c.protocol["analysis"]["weighting_spec_sha256"] = digest(weighted.to_dict())
    spec = TargetTrialSpec(weighted, TargetTrialProtocol.parse(c.protocol))
    check = validate_target_trial_source(c.project, c.metadata, c.frame, weighted, spec.protocol)
    result = run_target_trial(c.frame, spec, check)
    assert result["weighting_result"] == run_weighting(c.frame, weighted)
    assert verify_target_trial_result(result)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("age_known", "2025-01-02T00:00:00Z", "TTE_FUTURE_BASELINE"),
        ("coverage_end", "2025-01-30T00:00:00Z", "TTE_INCOMPLETE_FOLLOWUP"),
        ("exported", "unknown", "TTE_UNKNOWN_EXPORT"),
        ("intercurrent", "death", "TTE_INTERCURRENT_EVENT"),
        ("treatment", "", "TTE_ANALYSIS_EXCLUSION"),
    ],
)
def test_real_mcp_inspect_and_plan_reject_invalid_last_person(
    tmp_path, monkeypatch, field, value, error
):
    from rde.infrastructure.clinical import weighting

    project, store, dataset, frame, spec = native_fixture(
        tmp_path, mutate=lambda roots, labs, events, preparation: roots[-1].update({field: value})
    )
    monkeypatch.setattr(
        weighting, "run_weighting", lambda *a, **k: pytest.fail("Invalid protocol fitted")
    )
    call("inspect_clinical_study", args(dataset, spec), error=error)
    call("register_analysis_plan", plan_args(project, spec), error=error)
    assert not store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    assert not get_session().get_pipeline(project.id).plan_locked
    assert not clinical_records(store)


@pytest.mark.parametrize(
    "policy",
    [
        {"multiple_comparison_method": "holm"},
        {"missing_strategy": "pairwise"},
        {"alpha": 0.1},
    ],
)
def test_target_trial_plan_policy_is_not_generic_or_optional(tmp_path, policy):
    project, store, dataset, frame, spec = native_fixture(tmp_path)
    response = asyncio.run(
        create_server().call_tool("register_analysis_plan", plan_args(project, spec, **policy))
    )
    assert response.is_error, response.content
    assert not store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")


def test_existing_weighting_rejects_protocol_instead_of_ignoring_it(tmp_path):
    from rde.interface.mcp.tools.clinical_tools import parse_clinical_spec

    c = case(tmp_path)
    with pytest.raises(ValueError, match="Unknown weighting settings"):
        parse_clinical_spec({**c.spec.to_dict(), "protocol": c.protocol})


def test_target_trial_exact_phase4_proposal_prevents_method_or_protocol_substitution(tmp_path):
    project, store, dataset, frame, spec = native_fixture(tmp_path)
    proposal = store.load(PipelinePhase.CREATIVE_IDEATION, "greedy_analysis_candidates.json")
    assert proposal["strategy"] == "prespecified_clinical_contract" and proposal["confirmed"]
    assert len(proposal["plan_blueprint"]) == 1
    assert (
        proposal["plan_blueprint"][0]["execution_arguments"]["clinical_options"] == spec.to_dict()
    )
    assert [step["tool_name"] for step in proposal["execution_schedule"]] == ["run_clinical_study"]
    assert any("完整核准 preparation" in warning for warning in proposal["warnings"])
    assert proposal["review"]["numerical_evidence"] == "not_executed"
    changed = plan_args(project, spec)
    changed["analyses"][0]["execution_arguments"]["clinical_options"]["protocol"]["assignment"][
        "selection_basis"
    ] = "A changed assignment definition"
    call("register_analysis_plan", changed, error="differ from the confirmed proposal")
    changed["analyses"][0]["execution_arguments"]["clinical_options"] = spec.weighting.to_dict()
    call("register_analysis_plan", changed, error="differ from the confirmed proposal")
    assert not store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    lock(project, spec)


def test_discovery_uses_server_binding_and_metadata_without_rows(tmp_path):
    project, store, dataset, frame, spec = native_fixture(tmp_path)
    before = list(project.output_dir.rglob("*"))
    response = json.loads(
        call(
            "get_target_trial_contract",
            {
                "dataset_id": dataset.id,
                "weighting_options": spec.weighting.to_dict(),
            },
        )
    )
    assert response["source_binding"] == spec.protocol.binding.model_dump()
    assert response["weighting"] == spec.weighting.to_dict()
    assert response["weighting_spec_sha256"] == digest(spec.weighting.to_dict())
    assert response["clinical_validation"] == "synthetic_only"
    assert response["preparation_review_kind"] == "synthetic_oracle"
    assert len(response["sources"]) == 3
    for source in response["sources"]:
        assert set(source) == {"id", "sha256", "bytes", "columns"}
        assert all(isinstance(name, str) for name in source["columns"])
    assert "rows" not in response and "trace" not in response
    assert str(tmp_path) not in json.dumps(response)
    assert list(project.output_dir.rglob("*")) == before


@pytest.mark.parametrize(
    "tool", ["inspect_clinical_study", "register_analysis_plan", "run_clinical_study"]
)
def test_same_execution_key_rechecks_full_preparation_source(tmp_path, monkeypatch, tool):
    from rde.infrastructure.clinical import weighting
    from rde.interface.mcp.runtime import CLINICAL_REPLAY_ONLY

    project, store, dataset, frame, spec = native_fixture(tmp_path)
    if tool == "run_clinical_study":
        lock(project, spec)
    arguments = (
        plan_args(project, spec) if tool == "register_analysis_plan" else args(dataset, spec)
    )
    arguments["execution_key"] = "c" * 64
    first = call(tool, arguments)
    with monkeypatch.context() as patch:
        patch.setattr(
            weighting, "run_weighting", lambda *a, **k: pytest.fail("Replay fitted weighting")
        )
        assert call(tool, arguments) == first
        raw = next((Path(dataset.metadata.preparation["folder"]) / "sources").glob("*.csv"))
        raw.write_bytes(raw.read_bytes() + b" ")
        call(tool, arguments, error="CORRUPT_PREPARATION")
    assert not CLINICAL_REPLAY_ONLY.get()


@pytest.mark.parametrize("damage", ["plan_source", "run_source", "implementation"])
def test_cached_run_never_heals_missing_source_receipts(tmp_path, monkeypatch, damage):
    from rde.infrastructure.clinical import weighting, target_trial_source

    project, store, dataset, frame, spec = native_fixture(tmp_path)
    lock(project, spec)
    call("run_clinical_study", args(dataset, spec))
    record = clinical_records(store)[0]
    frozen = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"]).read_bytes()
    monkeypatch.setattr(
        weighting, "run_weighting", lambda *a, **k: pytest.fail("Damaged evidence refitted")
    )
    if damage == "implementation":
        original = target_trial_source.implementation()
        monkeypatch.setattr(
            target_trial_source, "implementation", lambda: {**original, "schema": "changed-version"}
        )
        missing = None
    else:
        item = (
            store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")[
                "target_trial_source_check"
            ]["artifact"]
            if damage == "plan_source"
            else record["target_trial_source_artifact"]
        )
        missing = project.output_dir / item["path"]
        missing.unlink()
    call("run_clinical_study", args(dataset, spec), error="TTE_")
    if missing:
        assert not missing.exists()
    assert (
        store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"]).read_bytes() == frozen
    )


def test_restart_recovers_exact_prepared_sources_and_reuses_without_fitting(tmp_path, monkeypatch):
    import rde.application.session as session_module
    from rde.infrastructure.persistence import (
        FileSystemProjectRepository,
        resolve_projects_base_dir,
    )
    from rde.infrastructure.clinical import weighting

    project, store, dataset, frame, spec = native_fixture(tmp_path)
    lock(project, spec)
    arguments = {**args(dataset, spec), "execution_key": "d" * 64}
    first = call("run_clinical_study", arguments)
    FileSystemProjectRepository(resolve_projects_base_dir()).save(project)
    session_module._session = None
    get_session().get_project(project.id)
    monkeypatch.setattr(
        weighting, "run_weighting", lambda *a, **k: pytest.fail("Restart refitted weighting")
    )
    assert call("run_clinical_study", arguments) == first
    assert (
        json.loads(call("get_target_trial_contract", {"dataset_id": dataset.id}))["source_binding"]
        == spec.protocol.binding.model_dump()
    )


@pytest.mark.parametrize("state", ["pending", "expired-lease", "stopped"])
def test_target_trial_old_autoresearch_queue_cannot_replace_locked_method(
    tmp_path, monkeypatch, state
):
    import test_standard_autoresearch_scope as queue
    import rde.application.session as session_module
    from rde.infrastructure.persistence import (
        FileSystemProjectRepository,
        resolve_projects_base_dir,
    )

    project, store, dataset, frame, spec = native_fixture(tmp_path)
    lock(project, spec)
    proposal = queue.proposal()
    proposal["variables"] = [spec.weighting.outcome, spec.weighting.covariates[0]["column"]]
    proposal["analysis_contract"].update(
        target_variable=proposal["variables"][0], covariates=proposal["variables"][1:]
    )
    monkeypatch.setattr(queue, "proposal", lambda: proposal)
    queue.historical_queue(
        project, store, monkeypatch, stopped=state == "stopped", leased=state == "expired-lease"
    )
    FileSystemProjectRepository(resolve_projects_base_dir()).save(project)
    session_module._session = None
    queue.prohibit_numerical_dispatch(monkeypatch)
    before = queue.files(project.artifacts_dir)
    for name in ["resume_autoresearch_run", "run_autoresearch_next_task", "run_autoresearch_queue"]:
        call(name, {"project_id": project.id}, error=queue.CODE)
        assert queue.files(project.artifacts_dir) == before
