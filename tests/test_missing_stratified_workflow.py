"""Actual MCP dispatch: new clinical families must keep source-bound evidence."""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness


def call(name, arguments):
    response = asyncio.run(create_server().call_tool(name, arguments))
    assert not response.is_error, response.content
    return response.content[0].text


def fixture(tmp_path, family):
    from test_clinical_survival import clinical_project

    if family == "imputation":
        from test_clinical_imputation import fixture as numerical_fixture
    else:
        from test_clinical_stratified import fixture as numerical_fixture
    frame, spec = numerical_fixture()
    return clinical_project(tmp_path, frame=frame, options=spec)


@pytest.mark.parametrize("family", ["imputation", "stratified"])
def test_native_inspect_run_readiness_report_and_frozen_publication(tmp_path, monkeypatch, family):
    from rde.infrastructure.clinical import imputation, stratified
    from rde.interface.mcp.tools._shared.clinical_readiness import required_figures
    from PIL import Image

    project, store, dataset, spec = fixture(tmp_path, family)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    preflight = json.loads(call("inspect_clinical_study", args))
    assert preflight["spec"] == spec.to_dict()
    assert (
        preflight["source_sha256"]
        == hashlib.sha256(dataset.metadata.file_path.read_bytes()).hexdigest()
    )
    assert not clinical_records(store)
    changed = deepcopy(args)
    changed["clinical_options"]["confidence_level"] = 0.9
    denied = asyncio.run(create_server().call_tool("run_clinical_study", changed))
    assert denied.is_error and "locked" in denied.content[0].text
    call("run_clinical_study", args)
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["case_ledger"] == preflight["case_ledger"]
    assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert {figure["plot_type"] for figure in record["figures"]} == required_figures(result)
    for figure in record["figures"]:
        publication = figure["publication"]
        assert publication["source_receipt_sha256"] == result["receipt_sha256"]
        assert publication["text_outside_canvas"] == []
        assert publication["raster_dpi"] == 300
        assert set(publication["files"]) == {"png", "svg", "pdf", "tiff", "caption", "data"}
        with Image.open(publication["files"]["png"]) as png:
            assert png.width >= 2000 and png.height > 500
            assert png.info["dpi"][0] == pytest.approx(300, abs=0.1)
    if family == "imputation":
        assert result["n"] == 100
        assert len(record["derived_artifacts"]) >= spec.m + 6
        assert (
            sum(Path(item["path"]).name.startswith("completed-") for item in record["artifacts"])
            == spec.m
        )
        assert "complete_data_rows" not in result["case_ledger"]
        monkeypatch.setattr(
            imputation, "run_imputation", lambda *a, **k: pytest.fail("MI unexpectedly refitted")
        )
    else:
        monkeypatch.setattr(
            stratified, "run_stratified", lambda *a, **k: pytest.fail("CMH unexpectedly refitted")
        )
    assert "沒有重新估計" in call("run_clinical_study", args)
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    readiness = _evaluate_report_readiness(summary, store, require_report_generation=False)
    assert readiness["ready"], readiness
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert result["receipt_sha256"] in report
    assert (
        "標準多重插補與缺失資料分析" if family == "imputation" else "分層二元比較：CMH 與共同勝算比"
    ) in report
    assert "個案納入與排除" in report and "解讀與適用範圍" in report
    assert _evaluate_report_readiness(summary, store)["ready"]
    source = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen = source.read_bytes()
    edition = json.loads(
        call(
            "render_publication_figures",
            {
                "project_id": project.id,
                "study_artifact": source.name,
                "expected_record_sha256": hashlib.sha256(frozen).hexdigest(),
                "preset_id": "journal-neutral-english-v1",
                "edition_id": str(uuid.uuid4()),
            },
        )
    )
    assert source.read_bytes() == frozen
    for original, changed in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(original["publication"]["files"]["data"]).read_bytes()
            == Path(changed["publication"]["files"]["data"]).read_bytes()
        )
    original_source = dataset.metadata.file_path.read_bytes()
    dataset.metadata.file_path.write_bytes(original_source + b"\n")
    denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
    assert denied.is_error and "different source" in denied.content[0].text
    dataset.metadata.file_path.write_bytes(original_source)
    damaged = (
        project.output_dir
        / (record["derived_artifacts"][0] if family == "imputation" else record["artifacts"][0])[
            "path"
        ]
    )
    damaged.write_text("corrupted evidence", encoding="utf-8")
    denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
    assert denied.is_error and "integrity" in denied.content[0].text
    assert not _evaluate_report_readiness(summary, store)["ready"]


def unlocked_project(tmp_path, family):
    from test_exploration_branch_loop import _complete_phase
    from rde.application.pipeline import REQUIRED_ARTIFACTS
    from rde.application.session import get_session
    from rde.domain.models.project import Project
    from rde.infrastructure.persistence.artifact_store import ArtifactStore
    from rde.domain.models.dataset import Dataset, DatasetMetadata
    from test_clinical_imputation import fixture as mi_fixture
    from test_clinical_stratified import fixture as cmh_fixture

    project = Project(f"{family}-policy", f"{family}-policy", tmp_path, tmp_path / "output")
    store = ArtifactStore(project.artifacts_dir)
    get_session().register_project(project)
    pipeline = get_session().get_pipeline(project.id)
    for phase in list(PipelinePhase)[:5]:
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
    frame, spec = mi_fixture() if family == "imputation" else cmh_fixture()
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    dataset = Dataset(
        row_count=len(frame), metadata=DatasetMetadata(source, "csv", source.stat().st_size)
    )
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    return project, store, dataset, spec


@pytest.mark.parametrize("family", ["imputation", "stratified"])
def test_actual_plan_registration_enforces_family_policy(tmp_path, family):
    from rde.application.session import get_session

    project, store, dataset, spec = unlocked_project(tmp_path, family)
    preflight = json.loads(
        call(
            "inspect_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
        )
    )
    assert preflight["n"] > 0
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
    }
    bad = {
        **args,
        "missing_strategy": "listwise" if family == "imputation" else "multiple_imputation",
    }
    denied = asyncio.run(create_server().call_tool("register_analysis_plan", bad))
    assert denied.is_error
    assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") is None
    call("register_analysis_plan", args)
    saved = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    assert saved["locked"] is True
    assert saved["missing_strategy"] == args["missing_strategy"]
    assert get_session().get_pipeline(project.id).plan_locked


def test_failed_imputation_saves_native_and_derived_failure_evidence(tmp_path):
    import numpy as np
    from test_clinical_imputation import fixture as mi_fixture
    from test_clinical_survival import clinical_project

    frame, spec = mi_fixture()
    frame["x"] = np.linspace(-2, 2, len(frame))
    frame["b"] = np.where(frame.x > 0, "yes", "no").astype(object)
    frame.loc[[4, 14, 63, 74], "b"] = None
    project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
    denied = asyncio.run(
        create_server().call_tool(
            "run_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
        )
    )
    assert denied.is_error and "separation" in denied.content[0].text
    assert not clinical_records(store)
    failures = list(project.output_dir.rglob("imputation_*/failure.json"))
    assert len(failures) == 1
    logs = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl").read_text()
    assert "run_clinical_study_failed" in logs and "failure.json" in logs


@pytest.mark.parametrize("tamper", [False, True])
def test_imputation_renderer_failure_recovers_without_refit_and_requires_full_inventory(
    tmp_path, monkeypatch, tamper
):
    from rde.infrastructure.clinical import imputation, report

    project, store, dataset, spec = fixture(tmp_path, "imputation")
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    original_renderer = report.figures

    def unavailable(*args, **kwargs):
        raise RuntimeError("Test renderer unavailable after completed numerical evidence")

    monkeypatch.setattr(report, "figures", unavailable)
    denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
    assert denied.is_error and "renderer unavailable" in denied.content[0].text
    record = clinical_records(store)[0]
    frozen_result = deepcopy(record["result"])
    assert record["artifacts"] == [] and len(record["derived_artifacts"]) > spec.m
    assert not verify_clinical_artifacts(record, project.output_dir)
    monkeypatch.setattr(
        imputation, "run_imputation", lambda *a, **k: pytest.fail("MI unexpectedly refitted")
    )
    monkeypatch.setattr(report, "figures", original_renderer)
    if tamper:
        # Deleting an inventory entry cannot conceal a damaged completed dataset.
        removed = record["derived_artifacts"].pop(0)
        (project.output_dir / removed["path"]).write_text("damaged", encoding="utf-8")
        store.save(PipelinePhase.EXECUTE_EXPLORATION, record.pop("artifact"), record)
        denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
        assert denied.is_error and "inventory failed integrity" in denied.content[0].text
    else:
        call("run_clinical_study", args)
        recovered = clinical_records(store)[0]
        assert recovered["result"] == frozen_result
        assert recovered["run_id"] == record["run_id"]
        assert verify_clinical_artifacts(recovered, project.output_dir)


@pytest.mark.parametrize("boundary", ["zero", "unbounded"])
def test_native_stratified_boundary_has_no_fabricated_interval_and_remains_reportable(
    tmp_path, boundary
):
    from test_clinical_stratified import fixture as cmh_fixture
    from test_clinical_survival import clinical_project

    counts = [[[0, 15], [10, 8]], [[0, 12], [6, 14]]]
    if boundary == "unbounded":
        counts = [table[::-1] for table in counts]
    frame, spec = cmh_fixture(counts)
    project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
    call("run_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()})
    record = clinical_records(store)[0]
    assert record["result"]["common_odds_ratio"]["boundary"] == boundary
    assert record["result"]["common_odds_ratio"]["ci_lower"] is None
    effect = next(
        fig for fig in record["figures"] if fig["plot_type"] == "clinical_stratified_effect"
    )
    svg = Path(effect["publication"]["files"]["svg"]).read_text()
    assert (
        "OR = 0 (log scale undefined); CI unavailable"
        if boundary == "zero"
        else "Unbounded OR; finite estimate/CI unavailable"
    ) in svg
    assert effect["publication"]["text_outside_canvas"] == []
    call("collect_results", {"project_id": project.id})
    readiness = _evaluate_report_readiness(
        store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json"),
        store,
        require_report_generation=False,
    )
    assert readiness["ready"], readiness


def test_source_change_during_imputation_cannot_complete_native_plan(tmp_path, monkeypatch):
    from rde.infrastructure.clinical import imputation

    project, store, dataset, spec = fixture(tmp_path, "imputation")
    actual = imputation.run_imputation

    def source_changed(*args, **kwargs):
        result = actual(*args, **kwargs)
        dataset.metadata.file_path.write_bytes(dataset.metadata.file_path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(imputation, "run_imputation", source_changed)
    denied = asyncio.run(
        create_server().call_tool(
            "run_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
        )
    )
    assert denied.is_error and "source file changed during execution" in denied.content[0].text
    assert not clinical_records(store)
    assert list(project.output_dir.rglob("imputation_*/result.json"))
    logs = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl").read_text()
    assert "run_clinical_study_failed" in logs and "result.json" in logs
