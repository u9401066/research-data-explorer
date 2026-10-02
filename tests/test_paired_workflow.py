"""Actual MCP pairing, immutable rendering recovery, reports and artifact checks."""

import asyncio
import csv
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
from test_clinical_survival import clinical_project
from test_paired_study_contract import fixture, specification


def paired_project(tmp_path, method="signed_rank"):
    options = (
        {}
        if method == "signed_rank"
        else {
            "method": "paired_mean",
            "primary_effect": "mean_difference",
            "omnibus": False,
            "bootstrap": None,
            "case_strategy": "complete",
        }
    )
    return clinical_project(tmp_path, frame=fixture(), options=specification(**options))


def call(name, args):
    return asyncio.run(create_server().call_tool(name, args))


@pytest.mark.parametrize("method", ["paired_mean", "signed_rank"])
def test_mcp_paired_numerical_receipt_report_and_drawing_rows_survive_reuse(
    tmp_path, monkeypatch, method
):
    from rde.infrastructure.clinical import repeated

    project, store, dataset, spec = paired_project(tmp_path, method)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    changed = {
        **args,
        "clinical_options": {
            **spec.to_dict(),
            "contrasts": [list(reversed(p)) for p in spec.contrasts],
        },
    }
    assert call("run_clinical_study", changed).is_error
    preflight = call("inspect_clinical_study", args)
    assert not preflight.is_error, preflight.content
    response = call("run_clinical_study", args)
    assert not response.is_error, response.content
    record = clinical_records(store)[0]
    assert len(record["figures"]) == (5 if method == "signed_rank" else 4)
    assert verify_clinical_artifacts(record, project.output_dir)
    for figure in record["figures"]:
        publication = figure["publication"]
        assert publication["text_outside_canvas"] == []
        assert publication["source_receipt_sha256"] == record["result"]["receipt_sha256"]
        assert set(publication["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        with Image.open(publication["files"]["png"]) as image:
            assert image.info["dpi"][0] == pytest.approx(300, abs=0.01)
        with Path(publication["files"]["data"]).open() as handle:
            rows = list(csv.DictReader(handle))
        if figure["plot_type"] == "clinical_repeated_trajectory":
            points = [r for r in rows if r["record"] == "observation"]
            assert [int(p["data_row"]) for p in points] == record["result"]["case_ledger"][
                "complete_data_rows"
            ]
        if figure["plot_type"] == "clinical_repeated_pairs_1":
            for contrast in record["result"]["contrasts"]:
                points = [r for r in rows if r["contrast_id"] == contrast["id"]]
                assert [int(p["data_row"]) for p in points] == contrast["data_rows"]
                assert [float(p["difference"]) for p in points] == [
                    p["difference"] for p in contrast["observations"]
                ]
    frozen = {str(project.output_dir / a["path"]): a["sha256"] for a in record["artifacts"]}
    monkeypatch.setattr(
        repeated, "run_repeated", lambda *a: pytest.fail("Saved paired estimate was recomputed")
    )
    assert not call("run_clinical_study", args).is_error
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
        for path, expected in frozen.items()
    )
    assert not call("collect_results", {"project_id": project.id}).is_error
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    assembled = call("assemble_report", {"project_id": project.id})
    assert not assembled.is_error, assembled.content
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "配對與重複量測結果解讀" in report and record["result"]["receipt_sha256"] in report
    assert "臨床事件結果解讀" not in report
    assert "未估計治療組差異、時間×治療交互作用或效應量信賴區間" not in report
    assert _evaluate_report_readiness(summary, store)["ready"]
    artifact = Path(next(iter(frozen)))
    artifact.write_text("tampered evidence")
    refused = call("run_clinical_study", args)
    assert refused.is_error and "integrity" in refused.content[0].text
    assert artifact.read_text() == "tampered evidence"


def test_renderer_failure_recovers_saved_paired_numbers_without_second_bootstrap(
    tmp_path, monkeypatch
):
    from rde.infrastructure.clinical import repeated, repeated_publication

    _, store, dataset, spec = paired_project(tmp_path)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    original = repeated_publication.figures

    def broken(*args):
        raise OSError("Synthetic paired renderer failure")

    monkeypatch.setattr(repeated_publication, "figures", broken)
    response = call("run_clinical_study", args)
    assert response.is_error and "renderer failure" in response.content[0].text
    before = clinical_records(store)[0]["result"]
    monkeypatch.setattr(
        repeated, "run_repeated", lambda *a: pytest.fail("Bootstrap repeated after drawing failure")
    )
    monkeypatch.setattr(repeated_publication, "figures", original)
    recovered = call("run_clinical_study", args)
    assert not recovered.is_error, recovered.content
    assert clinical_records(store)[0]["result"] == before


def test_source_column_names_cannot_overwrite_row_identity_in_exports(tmp_path):
    from rde.infrastructure.clinical.repeated import run_repeated
    from rde.infrastructure.clinical.repeated_contract import RepeatedSpec
    from rde.infrastructure.clinical.repeated_report import tables
    from rde.infrastructure.clinical.repeated_publication import figures

    spec = specification(
        method="paired_mean", primary_effect="mean_difference", omnibus=False, bootstrap=None
    )
    renamed = {"baseline": "data_row", "day7": "record", "day28": "values"}
    options = spec.to_dict()
    options["measurements"] = [{**m, "column": renamed[m["column"]]} for m in spec.measurements]
    options["contrasts"] = [[renamed[c] for c in pair] for pair in spec.contrasts]
    result = run_repeated(fixture().rename(columns=renamed), RepeatedSpec.parse(options))
    tables(result, tmp_path, "collision")
    with (tmp_path / "collision_observations.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == result["n"] * 3
    assert sorted({int(r["data_row"]) for r in rows}) == result["case_ledger"]["complete_data_rows"]
    assert {r["measurement_column"] for r in rows} == set(renamed.values())
    exported = figures(result, tmp_path, "collision")
    trajectory = next(f for f in exported if f["plot_type"] == "clinical_repeated_trajectory")
    with Path(trajectory["publication"]["files"]["data"]).open() as handle:
        rows = [r for r in csv.DictReader(handle) if r["record"] == "observation"]
    assert [int(r["data_row"]) for r in rows] == result["case_ledger"]["complete_data_rows"]
    assert [[float(row[f"T{i+1}"]) for i in range(3)] for row in rows] == [
        p["values"] for p in result["observations"]
    ]
