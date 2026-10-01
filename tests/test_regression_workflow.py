"""Real MCP tool boundaries, reports, immutable plots and failure evidence."""

import asyncio
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import uuid

import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness


def call(name, args):
    response = asyncio.run(create_server().call_tool(name, args))
    assert not response.is_error, response.content
    return response.content[0].text


def project_fixture(tmp_path, distribution):
    from test_clinical_survival import clinical_project
    from test_regression_models import source, study

    frame = source(distribution)
    options = dict(distribution=distribution)
    if distribution in {"gaussian", "binary"}:
        predictors = deepcopy(study().predictors)
        predictors[0]["knots"] = [-1.7, -0.5, 0.5, 1.7]
        options.update(predictors=predictors, interactions=[["x", "group"]])
        frame.loc[7, "x"] = float("nan")
    if distribution == "binary":
        options.update(distribution="binomial", outcome_levels=["0", "1"])
    if distribution == "ordinal":
        options["outcome_levels"] = ["Low", "Middle", "High", "Highest"]
    if distribution in {"poisson", "negative_binomial"}:
        options.update(exposure="exposure", exposure_unit="year")
    return clinical_project(tmp_path, frame=frame, options=study(**options))


@pytest.mark.parametrize(
    "distribution", ["gaussian", "binary", "poisson", "negative_binomial", "ordinal"]
)
def test_mcp_all_regression_families_publish_complete_reports_and_reuse_frozen_results(
    tmp_path, monkeypatch, distribution
):
    from rde.infrastructure.clinical import regression
    from rde.infrastructure.clinical.regression_report import required_figures

    project, store, dataset, spec = project_fixture(tmp_path, distribution)
    args = dict(dataset_id=dataset.id, clinical_options=spec.to_dict())
    before = json.loads(call("inspect_clinical_study", args))
    assert before["schema"] == "regression-preflight-v1"
    assert (
        before["source_sha256"]
        == hashlib.sha256(dataset.metadata.file_path.read_bytes()).hexdigest()
    )
    assert not clinical_records(store)
    altered = deepcopy(args)
    altered["clinical_options"]["predictors"][0]["increment"] = 2
    denied = asyncio.run(create_server().call_tool("run_clinical_study", altered))
    assert denied.is_error and "locked" in denied.content[0].text
    call("run_clinical_study", args)
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["case_ledger"] == before["case_ledger"]
    assert result["dataframe_sha256"] == before["dataframe_sha256"]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert {f["plot_type"] for f in record["figures"]} == required_figures(result)
    figure_coefficients = []
    for figure in record["figures"]:
        pub = figure["publication"]
        assert pub["source_receipt_sha256"] == result["receipt_sha256"]
        assert pub["text_outside_canvas"] == []
        assert set(pub["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        assert "中文解釋" in Path(pub["files"]["caption"]).read_text()
        with open(pub["files"]["data"], newline="") as stream:
            rows = list(csv.DictReader(stream))
        if "_effects_" in figure["plot_type"] or "_basis_" in figure["plot_type"]:
            figure_coefficients += [row["term"] for row in rows]
        if figure["plot_type"].endswith("_residuals"):
            assert [int(r["data_row"]) for r in rows] == result["case_ledger"]["complete_data_rows"]
        if figure["plot_type"].endswith("_categories"):
            assert [r["label"] for r in rows] == spec.outcome_levels
            assert sum(int(r["n"]) for r in rows) == result["n"]
        if "_curve_" in figure["plot_type"]:
            curve = result["conditional_curves"][0]
            assert [float(r["estimate"]) for r in rows] == [r["estimate"] for r in curve["points"]]
            if distribution == "gaussian":
                assert (
                    "Mean difference (original source unit)"
                    in Path(pub["files"]["svg"]).read_text()
                )
    assert sorted(figure_coefficients) == sorted(
        r["term"] for r in result["coefficients"] if r["role"] != "intercept"
    )
    monkeypatch.setattr(
        regression, "run_regression", lambda *a, **kw: pytest.fail("Saved regression refitted")
    )
    assert "沒有重新估計" in call("run_clinical_study", args)
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "多因素關聯、計數與序位迴歸" in report and "迴歸結果解讀" in report
    assert "聯合檢定" in report and "第二個 Holm 家族" in report
    assert "臨床事件結果解讀" not in report and "Cox" not in report
    assert "本計畫為生存／事件研究" not in report
    assert "本核准計畫未另外產生組間基線表" in report
    assert result["receipt_sha256"] in report
    assert all(Path(f["path"]).name in report for f in record["figures"])
    assert _evaluate_report_readiness(summary, store)["ready"]
    record_path = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    frozen = record_path.read_bytes()
    edition = json.loads(
        call(
            "render_publication_figures",
            dict(
                project_id=project.id,
                study_artifact=record_path.name,
                expected_record_sha256=hashlib.sha256(frozen).hexdigest(),
                preset_id="journal-neutral-english-v1",
                edition_id=str(uuid.uuid4()),
                start_number=12,
            ),
        )
    )
    assert record_path.read_bytes() == frozen
    for primary, image in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(primary["publication"]["files"]["data"]).read_bytes()
            == Path(image["publication"]["files"]["data"]).read_bytes()
        )
    damaged = project.output_dir / record["artifacts"][0]["path"]
    damaged.write_text("changed evidence")
    denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
    assert denied.is_error and "integrity" in denied.content[0].text
    assert not _evaluate_report_readiness(summary, store)["ready"]


def test_separation_failure_preserves_locked_spec_without_completed_artifacts(tmp_path):
    from test_clinical_survival import clinical_project
    from test_regression_models import source, study

    frame = source("poisson")
    frame.loc[frame.group == "A", "y"] = 0
    project, store, dataset, spec = clinical_project(
        tmp_path, frame=frame, options=study(distribution="poisson")
    )
    before = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    response = asyncio.run(
        create_server().call_tool(
            "run_clinical_study", dict(dataset_id=dataset.id, clinical_options=spec.to_dict())
        )
    )
    assert response.is_error and "Count separation" in response.content[0].text
    assert not clinical_records(store)
    assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") == before
    log = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl")
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(row["action"] == "run_clinical_study_failed" for row in entries)


def test_narrow_forest_retains_separation_between_wrapped_predictor_labels(tmp_path, monkeypatch):
    import numpy as np

    from test_regression_models import source, study
    from rde.infrastructure.clinical import regression_publication as renderer
    from rde.infrastructure.clinical.regression import run_regression

    frame = source("gaussian")
    rng = np.random.default_rng(91042)
    predictors = []
    for index in range(5):
        column = f"field{index}"
        frame[column] = rng.normal(size=len(frame))
        predictors.append(
            dict(
                column=column,
                kind="continuous",
                label=f"Questionnaire {index + 1}",
                unit="original units",
                reference=0,
                increment=1,
                knots=[],
            )
        )
    result = run_regression(frame, study(predictors=predictors))
    original = renderer.save_publication_figure
    forests_checked = []

    def inspect(fig, *args, **kwargs):
        saved = original(fig, *args, **kwargs)
        if any("Coefficient beta" in ax.get_xlabel() for ax in fig.axes):
            for ax in fig.axes:
                boxes = [
                    tick.get_window_extent(fig.canvas.get_renderer())
                    for tick in ax.get_yticklabels()
                ]
                assert len(boxes) == 5
                assert all(not a.overlaps(b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
                forests_checked.append(boxes)
        return saved

    monkeypatch.setattr(renderer, "save_publication_figure", inspect)
    # Exercise narrow physical geometry without depending on licensed Arial files.
    with renderer.publication_style() as profile:
        profile.update(profile="test-narrow", width_mm=85, font_size=7, font_min=5, font_max=7)
        renderer._figures(result, tmp_path, "wrapped", profile)
    assert len(forests_checked) == 1
