"""Actual MCP dispatch for locked Welch NI and immutable publication evidence."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import uuid

import pytest
from PIL import Image

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
from test_clinical_noninferiority import means_fixture
from test_clinical_survival import clinical_project


def call(name, arguments):
    response = asyncio.run(create_server().call_tool(name, arguments))
    assert not response.is_error, response.content
    return response.content[0].text


def deny(name, arguments, match=None):
    response = asyncio.run(create_server().call_tool(name, arguments))
    assert response.is_error, response.content
    if match:
        assert match in response.content[0].text
    return response.content[0].text


def fixture(tmp_path, passed=True):
    frame, spec = means_fixture()[:2]
    spec = replace(spec, margin=2 if passed else 0.05)
    return clinical_project(tmp_path, frame=frame, options=spec)


@pytest.mark.parametrize("passed", [True, False])
def test_native_ni_inspect_lock_execute_report_reuse_and_frozen_publication(
    tmp_path, monkeypatch, passed
):
    from rde.infrastructure.clinical import noninferiority
    from rde.interface.mcp.tools._shared.clinical_readiness import required_figures

    project, store, dataset, spec = fixture(tmp_path, passed)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    preflight = json.loads(call("inspect_clinical_study", args))
    assert preflight["schema"] == "noninferiority-preflight-v1"
    assert preflight["spec"] == spec.to_dict() and preflight["can_execute"]
    assert (
        preflight["source_sha256"]
        == hashlib.sha256(dataset.metadata.file_path.read_bytes()).hexdigest()
    )
    assert not clinical_records(store)
    changed = deepcopy(args)
    changed["clinical_options"]["margin"] += 1
    deny("run_clinical_study", changed, "locked")
    call("run_clinical_study", args)
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["status"] == "completed" and result["noninferiority"]["passed"] is passed
    assert result["case_ledger"] == preflight["case_ledger"]
    assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert {fig["plot_type"] for fig in record["figures"]} == required_figures(result)
    for figure in record["figures"]:
        publication = figure["publication"]
        assert publication["source_receipt_sha256"] == result["receipt_sha256"]
        assert publication["raster_dpi"] == 300 and publication["text_outside_canvas"] == []
        assert set(publication["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        with Image.open(publication["files"]["png"]) as image:
            assert image.width >= 2000 and image.height > 500
            assert image.info["dpi"][0] == pytest.approx(300, abs=0.1)
    effect = next(
        f for f in record["figures"] if f["plot_type"] == "clinical_noninferiority_effect"
    )
    svg = Path(effect["publication"]["files"]["svg"]).read_text()
    assert "97.5% one-sided" in svg and "Upper bound: +infinity" in svg
    assert ("Noninferiority demonstrated" if passed else "Noninferiority not demonstrated") in svg
    with Path(effect["publication"]["files"]["data"]).open() as stream:
        plotted = list(csv.DictReader(stream))[0]
    assert (
        float(plotted["lower_confidence_bound"])
        == result["noninferiority"]["lower_confidence_bound"]
    )
    assert plotted["upper_confidence_bound"] == "" and plotted["upper_bound_kind"] == "unbounded"
    monkeypatch.setattr(
        noninferiority,
        "run_noninferiority",
        lambda *a, **k: pytest.fail("NI unexpectedly refitted"),
    )
    assert "沒有重新估計" in call("run_clinical_study", args)
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    readiness = _evaluate_report_readiness(summary, store, require_report_generation=False)
    assert readiness["ready"], readiness
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "獨立兩組均差非劣性分析" in report
    assert "單側下限" in report and "不是執行失敗" in report
    assert result["receipt_sha256"] in report
    assert "預先指定的追蹤起點與事件編碼" not in report
    assert "## 臨床事件結果解讀" not in report
    if not passed:
        assert "保存數值未能證明非劣性" in report
        assert "保存數值支持預先指定界值下的非劣性" not in report
    assert _evaluate_report_readiness(summary, store)["ready"]
    original = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen = original.read_bytes()
    edition = json.loads(
        call(
            "render_publication_figures",
            {
                "project_id": project.id,
                "study_artifact": original.name,
                "expected_record_sha256": hashlib.sha256(frozen).hexdigest(),
                "preset_id": "journal-neutral-english-v1",
                "edition_id": str(uuid.uuid4()),
            },
        )
    )
    assert original.read_bytes() == frozen
    for first, second in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(first["publication"]["files"]["data"]).read_bytes()
            == Path(second["publication"]["files"]["data"]).read_bytes()
        )
    saved_source = dataset.metadata.file_path.read_bytes()
    dataset.metadata.file_path.write_bytes(saved_source + b"\n")
    deny("run_clinical_study", args, "different source")
    dataset.metadata.file_path.write_bytes(saved_source)
    (project.output_dir / record["artifacts"][0]["path"]).write_text(
        "changed evidence", encoding="utf-8"
    )
    deny("run_clinical_study", args, "integrity")
    assert not _evaluate_report_readiness(summary, store)["ready"]


def unlocked_project(tmp_path):
    from test_exploration_branch_loop import _complete_phase
    from rde.application.pipeline import REQUIRED_ARTIFACTS
    from rde.application.session import get_session
    from rde.domain.models.project import Project
    from rde.infrastructure.persistence.artifact_store import ArtifactStore
    from rde.domain.models.dataset import Dataset, DatasetMetadata

    project = Project("ni-policy", "ni-policy", tmp_path, tmp_path / "output")
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
    frame, spec = means_fixture()[:2]
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    dataset = Dataset(
        row_count=len(frame), metadata=DatasetMetadata(source, "csv", source.stat().st_size)
    )
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    return project, store, dataset, spec


def test_actual_registration_requires_matching_one_sided_alpha_and_listwise_none(tmp_path):
    from rde.application.session import get_session

    project, store, dataset, spec = unlocked_project(tmp_path)
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
        "alpha": spec.one_sided_alpha,
        "missing_strategy": "listwise",
        "multiple_comparison_method": "none",
    }
    for changes in [
        {"alpha": 0.05},
        {"missing_strategy": "pairwise"},
        {"missing_strategy": "multiple_imputation"},
        {"multiple_comparison_method": "holm"},
    ]:
        deny("register_analysis_plan", {**args, **changes})
        assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") is None
    for wrong in [
        {"confidence_level": 0.95},
        {"method": "binary_risk_difference"},
        {"confidence_sidedness": "two_sided"},
    ]:
        invalid = deepcopy(args)
        invalid["analyses"][0]["execution_arguments"]["clinical_options"].update(wrong)
        deny("register_analysis_plan", invalid)
        assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") is None
    call("register_analysis_plan", args)
    saved = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    assert saved["locked"] and saved["alpha"] == 0.025
    assert saved["missing_strategy"] == "listwise" and saved["multiple_comparison_method"] == "none"
    assert get_session().get_pipeline(project.id).plan_locked
    call("inspect_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()})


def test_native_ni_renderer_recovery_reuses_saved_numbers(tmp_path, monkeypatch):
    from rde.infrastructure.clinical import noninferiority, report

    project, store, dataset, spec = fixture(tmp_path)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    original_renderer = report.figures

    def failed_renderer(*args, **kwargs):
        raise RuntimeError("Test renderer unavailable after NI numerical receipt")

    monkeypatch.setattr(report, "figures", failed_renderer)
    deny("run_clinical_study", args, "renderer unavailable")
    record = clinical_records(store)[0]
    saved = deepcopy(record["result"])
    assert record["artifacts"] == [] and not verify_clinical_artifacts(record, project.output_dir)
    monkeypatch.setattr(
        noninferiority,
        "run_noninferiority",
        lambda *a, **k: pytest.fail("NI unexpectedly refitted"),
    )
    monkeypatch.setattr(report, "figures", original_renderer)
    call("run_clinical_study", args)
    restored = clinical_records(store)[0]
    assert restored["result"] == saved and restored["run_id"] == record["run_id"]
    assert verify_clinical_artifacts(restored, project.output_dir)


def test_source_change_during_ni_execution_cannot_complete_plan(tmp_path, monkeypatch):
    from rde.infrastructure.clinical import noninferiority

    project, store, dataset, spec = fixture(tmp_path)
    actual = noninferiority.run_noninferiority

    def source_changed(*args, **kwargs):
        result = actual(*args, **kwargs)
        dataset.metadata.file_path.write_bytes(dataset.metadata.file_path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(noninferiority, "run_noninferiority", source_changed)
    deny(
        "run_clinical_study",
        {"dataset_id": dataset.id, "clinical_options": spec.to_dict()},
        "source file changed during execution",
    )
    assert not clinical_records(store)


def test_ni_publication_preset_is_discoverable():
    assert "noninferiority" in json.loads(call("get_publication_presets", {}))["supported_studies"]


@pytest.mark.parametrize("tamper", ["receipt", "frame"])
def test_saved_ni_numerical_or_source_frame_tamper_is_rejected_before_reuse(tmp_path, tamper):
    from rde.application.session import get_session

    project, store, dataset, spec = fixture(tmp_path)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    call("run_clinical_study", args)
    if tamper == "receipt":
        record = clinical_records(store)[0]
        name = record.pop("artifact")
        record["result"]["noninferiority"]["lower_confidence_bound"] += 1
        store.save(PipelinePhase.EXECUTE_EXPLORATION, name, record)
        deny("run_clinical_study", args, "numerical evidence failed integrity")
    else:
        # Bytes unchanged but a changed loaded source frame must also block reuse.
        entry = get_session().get_dataset_entry(dataset.id)
        entry.dataframe.loc[0, "response"] += 1
        deny("run_clinical_study", args, "different source")


def test_exact_ni_decision_boundary_is_completed_and_reportable(tmp_path):
    from rde.infrastructure.clinical.noninferiority import run_noninferiority

    frame, spec = means_fixture()[:2]
    original = run_noninferiority(frame, spec)
    spec = replace(spec, margin=-original["noninferiority"]["lower_confidence_bound"])
    project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
    call("run_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()})
    result = clinical_records(store)[0]["result"]
    assert result["status"] == "completed"
    assert result["noninferiority"]["passed"] is False
    assert result["noninferiority"]["decision"] == "boundary_not_demonstrated"
    call("collect_results", {"project_id": project.id})
    readiness = _evaluate_report_readiness(
        store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json"),
        store,
        require_report_generation=False,
    )
    assert readiness["ready"], readiness
