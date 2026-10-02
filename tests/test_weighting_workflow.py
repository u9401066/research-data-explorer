"""MCP plan guards, complete weighting deliverables and immutable rerendering."""

import asyncio
from copy import deepcopy
import csv
from dataclasses import replace
import hashlib
import json
import os
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


def project_fixture(tmp_path, estimand="ATE", outcome_type="binary"):
    from test_clinical_survival import clinical_project
    from test_weighting_models import cell_fixture

    frame, spec, _, _ = cell_fixture(outcome_type)
    if outcome_type == "binary" and estimand == "ATT":
        # A real negative contrast must retain a difference scale in figures.
        spec = replace(spec, outcome_levels=list(reversed(spec.outcome_levels)))
    frame["eligible"] = "yes"
    frame.loc[0, "eligible"] = "no"
    frame.loc[1, "outcome"] = None
    return clinical_project(
        tmp_path,
        frame=frame,
        options=replace(
            spec, estimand=estimand, cohort_filter={"column": "eligible", "values": ["yes"]}
        ),
    )


@pytest.mark.parametrize("estimand", ["ATE", "ATT", "ATO"])
@pytest.mark.parametrize("outcome_type", ["continuous", "binary"])
def test_mcp_weighting_keeps_full_reports_case_ledger_and_frozen_evidence(
    tmp_path, monkeypatch, estimand, outcome_type
):
    from rde.infrastructure.clinical import weighting
    from rde.infrastructure.clinical.weighting_report import required_figures

    project, store, dataset, spec = project_fixture(tmp_path, estimand, outcome_type)
    args = dict(dataset_id=dataset.id, clinical_options=spec.to_dict())
    preflight = json.loads(call("inspect_clinical_study", args))
    assert preflight["schema"] == "weighting-preflight-v1"
    assert (
        preflight["source_sha256"]
        == hashlib.sha256(dataset.metadata.file_path.read_bytes()).hexdigest()
    )
    assert not clinical_records(store)
    altered = deepcopy(args)
    altered["clinical_options"]["estimand"] = "ATT" if estimand == "ATE" else "ATE"
    denied = asyncio.run(create_server().call_tool("run_clinical_study", altered))
    assert denied.is_error and "locked" in denied.content[0].text
    call("run_clinical_study", args)
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["case_ledger"] == preflight["case_ledger"]
    assert result["dataframe_sha256"] == preflight["dataframe_sha256"]
    assert result["design_sha256"] == preflight["design_sha256"]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert {f["plot_type"] for f in record["figures"]} == required_figures(result)
    for figure in record["figures"]:
        pub = figure["publication"]
        assert pub["source_receipt_sha256"] == result["receipt_sha256"]
        assert pub["text_outside_canvas"] == []
        assert set(pub["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        assert "中文解釋" in Path(pub["files"]["caption"]).read_text()
        if figure["plot_type"] == "clinical_weighting_effect":
            caption = Path(pub["files"]["caption"]).read_text()
            assert f"Study context: {spec.context}" in caption
            assert "independent-case working model" in caption
            if spec.time_origin.endswith("."):
                assert f"{spec.time_origin}." not in caption
            if outcome_type == "binary":
                assert result["effect"]["unit"] == "proportion"
                assert "negative difference is possible" in caption
                assert "0–1 scale" not in caption
                svg = Path(pub["files"]["svg"]).read_text()
                assert "Probability difference" in svg and "difference (0–1)" not in svg
                if estimand == "ATT":
                    assert result["effect"]["estimate"] < 0
            with open(pub["files"]["data"], newline="") as stream:
                effect = list(csv.DictReader(stream))[0]
            for key in ["estimate", "standard_error", "lower", "upper", "p_value"]:
                assert float(effect[key]) == result["effect"][key]
    observations = next(
        project.output_dir / item["path"]
        for item in record["artifacts"]
        if item["path"].endswith("_observations.csv")
    )
    with observations.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == preflight["input_rows"]
    assert [row["status"] for row in rows[:2]] == ["outside_cohort", "missing_required"]
    assert [int(row["data_row"]) for row in rows if row["status"] == "included"] == preflight[
        "case_ledger"
    ]["complete_data_rows"]
    monkeypatch.setattr(
        weighting, "run_weighting", lambda *a, **k: pytest.fail("Saved weighting refitted")
    )
    assert "沒有重新估計" in call("run_clinical_study", args)
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "觀察性研究的傾向加權" in report and "傾向加權結果解讀" in report
    assert "處置前依據" in report and "固定未加權" in report
    assert "Holm" not in report and "Cox" not in report and "迴歸結果解讀" not in report
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
                start_number=8,
            ),
        )
    )
    assert source.read_bytes() == frozen
    for original, image in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(original["publication"]["files"]["data"]).read_bytes()
            == Path(image["publication"]["files"]["data"]).read_bytes()
        )
    damaged = project.output_dir / record["artifacts"][0]["path"]
    damaged.write_text("modified evidence")
    denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
    assert denied.is_error and "integrity" in denied.content[0].text
    assert not _evaluate_report_readiness(summary, store)["ready"]


def test_separated_treatment_saves_failure_without_completed_study(tmp_path):
    from test_clinical_survival import clinical_project
    from test_weighting_models import cell_fixture

    frame, spec, _, _ = cell_fixture()
    frame["treatment"] = frame.stratum.map({"Low": "Control", "High": "Treated"})
    project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
    original_plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    response = asyncio.run(
        create_server().call_tool(
            "run_clinical_study", dict(dataset_id=dataset.id, clinical_options=spec.to_dict())
        )
    )
    assert response.is_error and "separation" in response.content[0].text
    assert not clinical_records(store)
    assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") == original_plan
    logs = [
        json.loads(line)
        for line in store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "decision_log.jsonl")
        .read_text()
        .splitlines()
    ]
    assert any(row["action"] == "run_clinical_study_failed" for row in logs)


@pytest.mark.parametrize(
    "policy,message",
    [
        ({"multiple_comparison_method": "holm"}, "multiplicity=none"),
        ({"multiple_comparison_method": "none", "alpha": 0.1}, "matching alpha"),
        (
            {"multiple_comparison_method": "none", "missing_strategy": "pairwise"},
            "listwise cases",
        ),
    ],
)
def test_weighting_plan_rejects_misleading_multiplicity_or_population_policy(
    tmp_path, policy, message
):
    from test_exploration_branch_loop import _complete_phase
    from test_weighting_models import cell_fixture
    from rde.application.pipeline import REQUIRED_ARTIFACTS
    from rde.application.session import get_session
    from rde.domain.models.project import Project
    from rde.infrastructure.persistence.artifact_store import ArtifactStore

    # Start before plan registration; an existing locked plan must never be
    # "unlocked" by changing only the in-memory pipeline flag.
    project = Project("weighting-policy", "weighting-policy", tmp_path, tmp_path / "output")
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
    _, spec, _, _ = cell_fixture()
    response = asyncio.run(
        create_server().call_tool(
            "register_analysis_plan",
            dict(
                project_id=project.id,
                analyses=[
                    dict(
                        type="run_clinical_study",
                        variables=spec.variables(),
                        execution_arguments={"clinical_options": spec.to_dict()},
                    )
                ],
                confirm=True,
                **policy,
            ),
        )
    )
    assert response.is_error and message in response.content[0].text
    assert not get_session().get_pipeline(project.id).plan_locked
    assert not project.plan_locked
    assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") is None


@pytest.mark.skipif(
    not os.environ.get("RDE_JOURNAL_TEST_FONT_DIR"), reason="Authorized local Arial required"
)
@pytest.mark.parametrize(
    "preset", ["nature-single-v1", "nature-double-v1", "plos-column-v1", "plos-full-v1"]
)
def test_weighting_journal_editions_preserve_numbers_and_source(tmp_path, monkeypatch, preset):
    from PIL import Image
    from rde.infrastructure.visualization.publication import resolve_preset
    from rde.infrastructure.clinical import weighting_publication

    original_save = weighting_publication.save_publication_figure
    inspected = []

    def reviewed_save(fig, directory, stem, **kwargs):
        saved = original_save(fig, directory, stem, **kwargs)
        if stem.endswith("_weighting_overlap"):
            renderer = fig.canvas.get_renderer()
            for ax in fig.axes:
                legend = ax.get_legend().get_window_extent(renderer)
                # A narrow-column peak previously touched G0's legend text.
                assert not legend.overlaps(ax.get_window_extent(renderer))
                titles = [
                    text
                    for text in fig.findobj()
                    if hasattr(text, "get_text")
                    and text.get_text() in ["Before weighting", "After weighting"]
                ]
                assert titles and all(
                    not legend.overlaps(t.get_window_extent(renderer)) for t in titles
                )
                inspected.append(saved["profile"])
        return saved

    monkeypatch.setattr(weighting_publication, "save_publication_figure", reviewed_save)

    monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", os.environ["RDE_JOURNAL_TEST_FONT_DIR"])
    project, store, dataset, spec = project_fixture(tmp_path, "ATO")
    call("run_clinical_study", dict(dataset_id=dataset.id, clinical_options=spec.to_dict()))
    record = clinical_records(store)[0]
    source = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, record["artifact"])
    original = source.read_bytes()
    edition = json.loads(
        call(
            "render_publication_figures",
            dict(
                project_id=project.id,
                study_artifact=source.name,
                expected_record_sha256=hashlib.sha256(original).hexdigest(),
                preset_id=preset,
                edition_id=str(uuid.uuid4()),
            ),
        )
    )
    profile = resolve_preset(preset)
    assert inspected.count(preset) == 2
    assert source.read_bytes() == original
    for first, rendered in zip(record["figures"], edition["figures"], strict=True):
        pub = rendered["publication"]
        assert (
            Path(pub["files"]["data"]).read_bytes()
            == Path(first["publication"]["files"]["data"]).read_bytes()
        )
        assert pub["text_outside_canvas"] == []
        assert pub["dimensions_mm"][0] == profile["width_mm"]
        with Image.open(pub["files"]["tiff"]) as raster:
            assert raster.mode == "RGB" and raster.n_frames == 1
            assert raster.info["dpi"] == (profile["raster_dpi"],) * 2
