"""MCP comparison bundles: fixed plans, unbounded effects, editions and readiness."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import csv
import hashlib
import json
import os
from pathlib import Path
import uuid

import pandas as pd
import pytest

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools.clinical_tools import clinical_records, verify_clinical_artifacts
from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
from rde.infrastructure.clinical.comparison_report import required_figures
from test_clinical_survival import clinical_project
from test_comparison_study_contract import fixture


def call(name, args):
    response = asyncio.run(create_server().call_tool(name, args))
    assert not response.is_error, response.content
    return response.content[0].text


@pytest.mark.parametrize("method", ["welch_mean", "rank", "binary"])
def test_mcp_comparison_keeps_full_family_report_and_saved_data(tmp_path, monkeypatch, method):
    from rde.infrastructure.clinical import comparison

    frame, spec = fixture()
    if method == "rank":
        spec = replace(
            spec,
            method="rank",
            primary_effect="rank_biserial",
            bootstrap={"resamples": 999, "seed": 21},
        )
    if method == "binary":
        frame["response"] = ["event" if i % 4 == 0 else "non-event" for i in range(len(frame))]
        spec = replace(
            spec,
            method="binary",
            primary_effect="proportion_ratio",
            outcome_levels=["non-event", "event"],
            omnibus=False,
        )
    project, store, dataset, spec = clinical_project(tmp_path, frame=frame, options=spec)
    args = dict(dataset_id=dataset.id, clinical_options=spec.to_dict())
    preflight = json.loads(call("inspect_clinical_study", args))
    assert preflight["schema"] == "comparison-preflight-v1" and not clinical_records(store)
    altered = deepcopy(args)
    altered["clinical_options"]["contrasts"][0].reverse()
    denied = asyncio.run(create_server().call_tool("run_clinical_study", altered))
    assert denied.is_error and "locked" in denied.content[0].text
    call("run_clinical_study", args)
    record = clinical_records(store)[0]
    result = record["result"]
    assert result["case_ledger"] == preflight["case_ledger"]
    assert verify_clinical_artifacts(record, project.output_dir)
    assert {f["plot_type"] for f in record["figures"]} == required_figures(result)
    for figure in record["figures"]:
        pub = figure["publication"]
        assert pub["text_outside_canvas"] == []
        assert pub["source_receipt_sha256"] == result["receipt_sha256"]
        assert set(pub["files"]) == {"png", "pdf", "svg", "tiff", "caption", "data"}
    monkeypatch.setattr(
        comparison, "run_comparison", lambda *a, **k: pytest.fail("Saved comparison refitted")
    )
    assert "沒有重新估計" in call("run_clinical_study", args)
    call("collect_results", {"project_id": project.id})
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert _evaluate_report_readiness(summary, store, require_report_generation=False)["ready"]
    call("assemble_report", {"project_id": project.id})
    report = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "獨立組比較結果解讀" in report and "未作多重校正" in report
    assert "Cox" not in report and "迴歸結果解讀" not in report
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
                start_number=7,
            ),
        )
    )
    assert source.read_bytes() == frozen
    for old, new in zip(record["figures"], edition["figures"], strict=True):
        assert (
            Path(old["publication"]["files"]["data"]).read_bytes()
            == Path(new["publication"]["files"]["data"]).read_bytes()
        )
    damaged = project.output_dir / record["artifacts"][0]["path"]
    damaged.write_text("altered evidence")
    denied = asyncio.run(create_server().call_tool("run_clinical_study", args))
    assert denied.is_error and "integrity" in denied.content[0].text
    assert not _evaluate_report_readiness(summary, store)["ready"]


def boundary_fixture():
    frame, base = fixture()
    levels = [f"組別 {i} / source raw label" for i in range(8)]
    frame = pd.DataFrame(
        {
            "arm": [label for label in levels for _ in range(10)],
            "response": [
                "event" if i < count else "none"
                for count in [0, 0, 10, 10, 2, 4, 8, 1]
                for i in range(10)
            ],
            "subject": list(range(80)),
        }
    )
    spec = replace(
        base,
        group_levels=levels,
        contrasts=[[label, levels[0]] for label in levels[1:]],
        method="binary",
        primary_effect="odds_ratio",
        outcome_levels=["none", "event"],
        omnibus=False,
        cohort_filter=None,
    )
    return frame, spec


def test_boundary_figures_keep_all_contrasts_and_never_place_nonfinite_ratio_points(
    tmp_path, monkeypatch
):
    from rde.infrastructure.clinical.comparison import run_comparison
    from rde.infrastructure.clinical import comparison_publication as publication

    frame, spec = boundary_fixture()
    result = run_comparison(frame, spec)
    inspected = []
    original = publication.save_publication_figure

    def capture(fig, directory, stem, **kwargs):
        if "odds_ratio" in stem or "proportion_ratio" in stem:
            points = [line for line in fig.axes[0].lines if line.get_marker() == "o"]
            assert not points  # Every point is undefined or +infinity in this fixture.
            rows = kwargs["data"]
            assert all(r["upper_status"] == "positive_infinity" for r in rows)
            inspected.extend(r["contrast_id"] for r in rows)
        return original(fig, directory, stem, **kwargs)

    monkeypatch.setattr(publication, "save_publication_figure", capture)
    figures = publication.figures(result, tmp_path, "boundary")
    assert len(figures) == 8
    assert len(inspected) == 14 and set(inspected) == {f"contrast_{i}" for i in range(1, 8)}
    rows = []
    for f in figures:
        if "odds_ratio" in f["plot_type"]:
            with Path(f["publication"]["files"]["data"]).open() as stream:
                rows += list(csv.DictReader(stream))
    assert len(rows) == 7 and rows[0]["estimate_status"] == "undefined"
    assert all(r["estimate"] == "" for r in rows)
    assert all(f["publication"]["text_outside_canvas"] == [] for f in figures)


@pytest.mark.skipif(
    not os.environ.get("RDE_JOURNAL_TEST_FONT_DIR"), reason="Authorized local Arial required"
)
@pytest.mark.parametrize("preset", ["nature-single-v1", "plos-column-v1"])
def test_boundary_journal_editions_keep_all_states_and_canvas(tmp_path, monkeypatch, preset):
    from rde.infrastructure.clinical.comparison import run_comparison
    from rde.infrastructure.clinical.comparison_publication import figures

    monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", os.environ["RDE_JOURNAL_TEST_FONT_DIR"])
    frame, spec = boundary_fixture()
    result = run_comparison(frame, spec)
    saved = deepcopy(result)
    rendered = figures(result, tmp_path, "boundary", preset_id=preset)
    assert result == saved and len(rendered) == 8
    assert all(f["publication"]["text_outside_canvas"] == [] for f in rendered)


@pytest.mark.parametrize(
    "policy",
    [
        {"alpha": 0.1, "multiple_comparison_method": "bonferroni"},
        {"missing_strategy": "pairwise", "multiple_comparison_method": "bonferroni"},
        {"multiple_comparison_method": "holm"},
    ],
)
def test_plan_rejects_mismatched_comparison_policies_before_lock(tmp_path, policy):
    from test_exploration_branch_loop import _complete_phase
    from rde.application.pipeline import REQUIRED_ARTIFACTS
    from rde.application.session import get_session
    from rde.domain.models.project import Project
    from rde.infrastructure.persistence.artifact_store import ArtifactStore

    project = Project("comparison-policy", "comparison-policy", tmp_path, tmp_path / "output")
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
    _, spec = fixture()
    spec = replace(spec, multiplicity="bonferroni")
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
    assert (
        response.is_error
        and "matching alpha, listwise cases and the bonferroni" in response.content[0].text
    )
    assert not pipeline.plan_locked and not project.plan_locked
    assert store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml") is None
