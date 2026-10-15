"""Actual MCP matching workflow, frozen deliverables, policy and tamper checks."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re
import uuid

from docx import Document
from PIL import Image
import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import get_session
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
from test_clinical_survival import clinical_project
from test_matching_candidate import matching_fixture
from test_noninferiority_workflow import call, deny, unlocked_project


def setup(tmp_path, outcome="continuous"):
    frame, spec = matching_fixture(outcome)
    spec = replace(spec, context="工程核對：比較預先指定配對後的研究結果")
    return clinical_project(tmp_path, frame=frame, options=spec)


@pytest.mark.parametrize("outcome", ["continuous", "binary"])
def test_actual_matching_inspect_execute_frozen_publication_docx_and_reuse(
    tmp_path, monkeypatch, outcome
):
    from rde.infrastructure.clinical import matching
    from rde.infrastructure.clinical.matching_report import required_figures

    project, store, dataset, spec = setup(tmp_path, outcome)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    preflight = json.loads(call("inspect_clinical_study", args))
    assert preflight["schema"] == "matching-preflight-v1"
    assert preflight["n"] == 200 and preflight["propensity_parameters"] == 2
    assert preflight["estimand"] == "matched_treated" and preflight["can_execute"]
    assert (
        preflight["source_sha256"]
        == hashlib.sha256(dataset.metadata.file_path.read_bytes()).hexdigest()
    )
    assert not clinical_records(store)
    wrong = deepcopy(args)
    wrong["clinical_options"]["caliper_sd"] *= 2
    deny("run_clinical_study", wrong, "locked")
    call("run_clinical_study", args)
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["method_schema"] == "matching-study-v1"
    assert result["n"] == 140 and result["matching_population"]["matched_pairs"] == 70
    assert result["matching_population"]["complete_cases"] == preflight["n"]
    assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert {f["plot_type"] for f in record["figures"]} == required_figures(result)
    for figure in record["figures"]:
        publication = figure["publication"]
        assert publication["source_receipt_sha256"] == result["receipt_sha256"]
        assert set(publication["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        assert not publication["text_outside_canvas"] and publication["raster_dpi"] == 300
        assert not re.search(r"[\u3400-\u9fff]", publication["caption_en"])
        assert publication["source_context"]["context"] == spec.context
        with Image.open(publication["files"]["png"]) as image:
            assert image.info["dpi"][0] == pytest.approx(300, abs=0.1)
    original = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen = original.read_bytes()
    monkeypatch.setattr(matching, "run_matching", lambda *a, **kw: pytest.fail("Unexpected refit"))
    assert "沒有重新估計" in call("run_clinical_study", args)
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    ready = _evaluate_report_readiness(summary, store, require_report_generation=False)
    assert ready["ready"], ready
    call("assemble_report", {"project_id": project.id})
    assert _evaluate_report_readiness(summary, store)["ready"]
    call("export_report", {"project_id": project.id, "formats": "docx"})
    docx = project.artifacts_dir / "exports/eda_report.docx"
    text = "\n".join(p.text for p in Document(docx).paragraphs)
    assert "傾向分數配對與配對群聚推論" in text and "matched-treated" in text
    assert "本核准研究契約不另外產生 Table 1" in text
    assert (
        "interpretation type not mapped" not in text
        and "所有結果應視為早期探索與假說生成" not in text
    )
    assert result["receipt_sha256"] in text
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
    for old, new in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(old["publication"]["files"]["data"]).read_bytes()
            == Path(new["publication"]["files"]["data"]).read_bytes()
        )
    assert original.read_bytes() == frozen
    source_bytes = dataset.metadata.file_path.read_bytes()
    dataset.metadata.file_path.write_bytes(source_bytes + b"\n")
    deny("run_clinical_study", args, "different source")
    dataset.metadata.file_path.write_bytes(source_bytes)
    (project.output_dir / record["artifacts"][0]["path"]).write_text("changed")
    deny("run_clinical_study", args, "integrity")
    assert not _evaluate_report_readiness(summary, store)["ready"]


def test_actual_registration_rejects_wrong_population_policy_or_method(tmp_path):
    project, store, dataset, _ = unlocked_project(tmp_path)
    frame, spec = matching_fixture()
    frame.to_csv(dataset.metadata.file_path, index=False)
    entry = get_session().get_dataset_entry(dataset.id)
    loaded = PandasLoader().load(dataset.metadata)
    entry.dataframe, dataset.variables = loaded[:2]
    dataset.row_count = len(frame)
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
        "missing_strategy": "listwise",
        "multiple_comparison_method": "none",
    }
    for wrong in [
        {"alpha": 0.01},
        {"missing_strategy": "pairwise"},
        {"multiple_comparison_method": "holm"},
    ]:
        deny("register_analysis_plan", {**args, **wrong})
        assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") is None
    for change in [{"estimand": "ATT"}, {"method": "nearest_with_replacement"}, {"subject": None}]:
        invalid = deepcopy(args)
        invalid["analyses"][0]["execution_arguments"]["clinical_options"].update(change)
        deny("register_analysis_plan", invalid)
    call("register_analysis_plan", args)
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    assert (
        plan["locked"]
        and plan["missing_strategy"] == "listwise"
        and plan["multiple_comparison_method"] == "none"
    )
    assert plan["analyses"][0]["execution_arguments"]["clinical_options"] == spec.to_dict()


@pytest.mark.parametrize("tamper", ["receipt", "frame"])
def test_matching_rejects_changed_numbers_or_source_frame(tmp_path, tamper):
    project, store, dataset, spec = setup(tmp_path)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    call("run_clinical_study", args)
    if tamper == "receipt":
        record = clinical_records(store)[0]
        artifact = record.pop("artifact")
        record["result"]["effect"]["estimate"] += 1
        store.save(PipelinePhase.EXECUTE_EXPLORATION, artifact, record)
        deny("run_clinical_study", args, "numerical evidence failed integrity")
    else:
        get_session().get_dataset_entry(dataset.id).dataframe.loc[0, "outcome"] += 1
        deny("run_clinical_study", args, "different source")


def test_renderer_recovery_keeps_exact_matching_numbers(tmp_path, monkeypatch):
    from rde.infrastructure.clinical import matching, report

    project, store, dataset, spec = setup(tmp_path)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    original = report.figures

    def fail(*a, **kw):
        raise RuntimeError("fixture matching renderer failed")

    monkeypatch.setattr(report, "figures", fail)
    deny("run_clinical_study", args, "renderer failed")
    record = clinical_records(store)[0]
    saved = deepcopy(record["result"])
    assert record["artifacts"] == []
    monkeypatch.setattr(matching, "run_matching", lambda *a, **kw: pytest.fail("Unexpected refit"))
    monkeypatch.setattr(report, "figures", original)
    call("run_clinical_study", args)
    assert clinical_records(store)[0]["result"] == saved
    assert verify_clinical_artifacts(clinical_records(store)[0], project.output_dir)


def test_matching_publication_discovery():
    assert "matching" in json.loads(call("get_publication_presets", {}))["supported_studies"]
