"""Locked MCP execution, complete figures, no-refit editions and evidence integrity."""

import asyncio
import csv
import hashlib
import json
from pathlib import Path
import uuid
from xml.etree import ElementTree as ET

import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness


def longitudinal_project(tmp_path, family="longitudinal_gaussian"):
    from test_clinical_survival import clinical_project
    from test_longitudinal_models import observations, study

    frame = observations()
    spec = {"group": "group", "group_reference": "0", "time_by_group": True}
    if family == "longitudinal_gaussian":
        spec.update(
            time_mode="categorical", time_levels=[-2, -1, 0, 1, 2, 3], correlation="independence"
        )
        frame.loc[0, "y"] = float("nan")
    elif family == "longitudinal_mixed":
        spec.update(method="mixed", correlation=None, random_slope=True)
    elif family == "longitudinal_binomial":
        spec.update(distribution="binomial", positive="1", negative="0")
        frame = frame.drop(columns="y").rename(columns={"binary": "y"})
    elif family == "longitudinal_poisson":
        spec.update(distribution="poisson", exposure="exposure", exposure_unit="years")
        frame = frame.drop(columns="y").rename(columns={"count": "y"})
    else:
        raise AssertionError(family)
    return clinical_project(tmp_path, frame=frame, options=study(**spec))


def call(name, args):
    response = asyncio.run(create_server().call_tool(name, args))
    assert not response.is_error, response.content
    return response.content[0].text


def test_linear_observed_figure_labels_the_actual_visits_including_endpoints(tmp_path):
    from test_clinical_survival import clinical_project
    from test_longitudinal_models import observations, study

    frame = observations()
    frame = frame[frame["time"].isin([-2, -1, 0, 1])].copy()
    frame["time"] = frame["time"] * 2 + 12
    project, store, dataset, spec = clinical_project(
        tmp_path, frame=frame, options=study(time_reference=8)
    )
    call("run_clinical_study", {"dataset_id": dataset.id, "clinical_options": spec.to_dict()})
    record = clinical_records(store)[0]
    figure = next(f for f in record["figures"] if f["plot_type"].endswith("_observed"))
    # Inspect the exported tick text, not an internal plotting helper. Automatic
    # ticks previously showed 9, 10.5, 12, 13.5 instead of the four actual visits.
    root = ET.fromstring(
        Path(figure["publication"]["files"]["svg"]).read_text(),
        parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)),
    )
    axis = root.find(".//{http://www.w3.org/2000/svg}g[@id='matplotlib.axis_1']")
    assert axis is not None
    text = [node.text.strip() for node in axis.iter() if node.tag is ET.Comment]
    assert text[:4] == ["8", "10", "12", "14"]


@pytest.mark.parametrize(
    "family",
    [
        "longitudinal_gaussian",
        "longitudinal_mixed",
        "longitudinal_binomial",
        "longitudinal_poisson",
    ],
)
def test_mcp_longitudinal_cases_figures_report_and_evidence_reuse(tmp_path, monkeypatch, family):
    from rde.infrastructure.clinical import longitudinal
    from rde.infrastructure.clinical.longitudinal_report import required_figures

    project, store, dataset, spec = longitudinal_project(tmp_path, family)
    args = {"dataset_id": dataset.id, "clinical_options": spec.to_dict()}
    preflight = json.loads(call("inspect_clinical_study", args))
    assert preflight["n_subjects"] == 64 and preflight["n"] == (
        383 if family == "longitudinal_gaussian" else 384
    )
    assert (
        preflight["source_sha256"]
        == hashlib.sha256(dataset.metadata.file_path.read_bytes()).hexdigest()
    )
    assert not clinical_records(store)
    call("run_clinical_study", args)
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
    assert result["case_ledger"] == preflight["case_ledger"]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert {f["plot_type"] for f in record["figures"]} == required_figures(result)
    for figure in record["figures"]:
        publication = figure["publication"]
        assert publication["source_receipt_sha256"] == result["receipt_sha256"]
        assert publication["text_outside_canvas"] == []
        assert set(publication["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        assert "中文解釋" in Path(publication["files"]["caption"]).read_text()
        with open(publication["files"]["data"], newline="") as stream:
            rows = list(csv.DictReader(stream))
        if figure["plot_type"].endswith("_residuals"):
            assert (
                sorted(int(row["data_row"]) for row in rows)
                == result["case_ledger"]["complete_data_rows"]
            )
        if figure["plot_type"].endswith("_observed"):
            assert sum(int(row["observations"]) for row in rows) == result["n"]
    if family == "longitudinal_gaussian":
        assert len(record["figures"]) == 6  # 11 non-intercept terms need two complete panels
    monkeypatch.setattr(
        longitudinal, "run_longitudinal", lambda *a, **kw: pytest.fail("Saved study refitted")
    )
    assert "沒有重新估計" in call("run_clinical_study", args)
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "縱向追蹤與重複觀察" in report and "縱向結果解讀" in report
    assert "Cox" not in report and "臨床事件結果解讀" not in report
    assert result["receipt_sha256"] in report
    assert all(Path(f["path"]).name in report for f in record["figures"])
    assert _evaluate_report_readiness(summary, store)["ready"]
    source = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen = source.read_bytes()
    edition = json.loads(
        call(
            "render_publication_figures",
            dict(
                project_id=project.id,
                study_artifact=source.name,
                expected_record_sha256=hashlib.sha256(frozen).hexdigest(),
                preset_id="journal-neutral-english-v1",
                edition_id=str(uuid.uuid4()),
                start_number=9,
            ),
        )
    )
    assert source.read_bytes() == frozen
    assert len(edition["figures"]) == len(record["figures"])
    for primary, image in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(primary["publication"]["files"]["data"]).read_bytes()
            == Path(image["publication"]["files"]["data"]).read_bytes()
        )
    corrupted = project.output_dir / record["artifacts"][0]["path"]
    corrupted.write_text("altered evidence")
    denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
    assert denied.is_error and "integrity" in denied.content[0].text
    assert corrupted.read_text() == "altered evidence"
    assert not _evaluate_report_readiness(summary, store)["ready"]
