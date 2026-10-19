"""Render saved evidence only; the opt-in fixture never loads or fits a dataset."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

import pytest

from rde.application.pipeline import PipelinePhase
from rde.infrastructure.adapters.docx_exporter import DocxExporter
from rde.infrastructure.adapters.markdown_renderer import MarkdownReportRenderer
from rde.infrastructure.persistence.artifact_store import ArtifactStore
from rde.interface.mcp.tools import report_tools


@pytest.fixture(scope="module")
def saved_report(tmp_path_factory):
    index_path = os.environ.get("RDE_SAVED_GENERIC_REPORT_INDEX")
    if not index_path:
        pytest.skip("opt-in immutable synthetic saved-artifact index required")
    index = json.loads(Path(index_path).read_text())
    workspace = next(a for a in index if a["filename"] == "analysis-workspace.json")
    context = json.loads(Path(workspace["path"]).read_text())
    native = context["native"]
    root = Path(native["rdeDir"])
    project = SimpleNamespace(
        id=native["rdeProjectId"],
        dataset_ids=[native["rdeDatasetId"]],
        output_dir=root,
        artifacts_dir=root / "artifacts",
        data_dir=root / "rawdata",
    )
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    for artifact in index:
        path = Path(artifact["path"])
        assert not path.is_symlink()
        assert path.stat().st_size == artifact["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    store = ArtifactStore(project.artifacts_dir)
    store.save = lambda *_a, **_k: pytest.fail(
        "report projection must not mutate original evidence"
    )
    report = report_tools._build_formal_research_report(
        project, store, store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    )
    out = tmp_path_factory.mktemp("saved-generic-report")
    rendered = MarkdownReportRenderer().render_markdown(report)
    (out / "formal.md").write_text(rendered)
    docx = DocxExporter().export_docx(report, out / "formal.docx", figures_dir=root / "figures")
    with zipfile.ZipFile(docx) as package:
        xml = ET.fromstring(package.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = "\n".join(
            "".join(t.text or "" for t in p.findall(".//w:t", ns))
            for p in xml.findall(".//w:p", ns)
        )
        drawings = xml.findall(".//w:drawing", ns)
    yield SimpleNamespace(
        project=project,
        store=store,
        report=report,
        rendered=rendered,
        text=text,
        drawings=drawings,
        out=out,
    )
    assert before == {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }


def test_saved_docx_embeds_all_sixteen_figures_without_literal_image_paths(saved_report):
    assert len(saved_report.drawings) == 16
    assert "![Figure" not in saved_report.text


def test_saved_docx_keeps_full_main_and_sensitivity_estimates(saved_report):
    for value in [
        "-0.090516",
        "-0.589548",
        "0.408516",
        "0.720616",
        "-0.0962016",
        "-0.598571",
        "0.406168",
        "0.705763",
    ]:
        assert value in saved_report.text
    assert "br_094811048a" in saved_report.text
    assert "exp_b97cac4318" in saved_report.text
    assert "ar_54cb5805f4" in saved_report.text
    assert "不取代主要分析" in saved_report.text
    assert "未作多重比較校正" in saved_report.text
    assert "160" in saved_report.text


def test_saved_focus_does_not_promote_unselected_schema_column(saved_report):
    for key in ["data_overview", "recommendations"]:
        section = next(s for s in saved_report.report.sections if s.section_id == key)
        assert "mortality" not in section.content


def test_saved_table_one_display_distinguishes_optional_from_absent(saved_report):
    results = saved_report.store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert results["deliverables"]["table_one_present"] is True
    assert "**Table 1:** 已提供" in report_tools._format_analyses(results)


def test_saved_sensitivity_section_uses_exact_completed_branch(saved_report):
    from rde.interface.mcp.tools._shared.generic_report import branch_reports_markdown

    section = branch_reports_markdown(saved_report.project, saved_report.store)
    assert "exp_b97cac4318" in section
    assert "-0\\.0962016" in section
    assert "No data available" not in section


def test_figure_resolution_preserves_subdirectory_and_rejects_basename_substitution(tmp_path):
    figures = tmp_path / "figures"
    nested = figures / "study"
    nested.mkdir(parents=True)
    (figures / "same.png").write_bytes(b"wrong sibling")
    right = nested / "same.png"
    right.write_bytes(b"correct nested source")
    assert DocxExporter._resolve_figure_path("../../figures/study/same.png", figures) == right
    assert DocxExporter._resolve_figure_path("../../figures/missing/same.png", figures) is None
    assert DocxExporter._resolve_figure_path("../../outside.png", figures) is None


def test_confirmed_roles_do_not_pad_with_unused_variables():
    schema = {"variables": [{"name": "outcome"}, {"name": "age"}, {"name": "unused"}]}
    roles = {"outcome": "outcome", "covariates": ["age"]}
    assert report_tools._select_focus_variables(schema, roles, {}, limit=8) == ["outcome", "age"]


def test_present_optional_table_is_not_inapplicable():
    output = report_tools._format_analyses(
        {"deliverables": {"table_one_required": False, "table_one_present": True}}
    )
    assert "**Table 1:** 已提供" in output


@pytest.mark.parametrize("method", ["multiple_regression", "logistic_regression"])
def test_native_numerical_only_branch_reports_verify_sources_without_creating_figures(
    tmp_path, monkeypatch, method
):
    import asyncio
    from test_advanced_publication import saved
    from test_exploration_branch_loop import _make_phase8_ready_project, _textify_tool_result
    from rde.application.session import get_session
    from rde.domain.models.dataset import Dataset, DatasetMetadata
    from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator
    from rde.infrastructure.adapters.pandas_loader import PandasLoader
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.tools._shared.branch_publication import (
        branch_publication_source,
        branch_report_source,
    )
    from rde.interface.mcp.tools._shared.generic_report import branch_reports_markdown
    import rde.infrastructure.adapters as adapters

    _, initial = saved(tmp_path, method)
    project, store = _make_phase8_ready_project(tmp_path)
    source_path = tmp_path / "original.csv"
    metadata = DatasetMetadata(source_path, "csv", source_path.stat().st_size)
    frame, variables, count, _ = PandasLoader().load(metadata)
    dataset = Dataset(id="numerical-report-dataset", metadata=metadata)
    dataset.mark_loaded(variables, count)
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    engine = AnalysisDelegator()
    engine._automl_available = False
    monkeypatch.setattr(adapters, "get_analysis_delegator", lambda: engine)

    def call(name, args):
        response = asyncio.run(create_server().call_tool(name, args))
        text = _textify_tool_result(response)
        assert not response.is_error and "❌" not in text, text

    call(
        "start_autoresearch_run",
        {
            "project_id": project.id,
            "max_tasks": 1,
            "max_branches": 1,
            "include_builtin_suggestions": False,
            "agent_proposals": [
                {
                    "hypothesis": "Synthetic numerical report regression",
                    "reason": "Retain full sensitivity evidence without requesting figures",
                    "variables": list(frame.columns),
                    "analysis_contract": {**initial["analysis_contract"], "create_figures": False},
                }
            ],
        },
    )
    call("run_autoresearch_next_task", {"project_id": project.id})
    phase = PipelinePhase.EXECUTE_EXPLORATION
    event = store.load(phase, "branch_experiment_results.jsonl")[-1]
    wrapper_path = Path(event["artifact"])
    wrapper = json.loads(wrapper_path.read_text())
    execution = wrapper["contract_execution"]
    source = Path(execution["artifact_path"])
    record = json.loads(source.read_text())
    assert record["status"] == "completed"
    assert "publication_result" not in record
    args = (project, record["branch_id"], record["experiment_id"], execution["artifact_sha256"])
    original_tree = {p: p.read_bytes() for p in project.output_dir.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        AnalysisDelegator, "run_analysis", lambda *_a, **_kw: pytest.fail("Report refit")
    )
    monkeypatch.setattr(PandasLoader, "load", lambda *_a, **_kw: pytest.fail("Report parsed data"))
    source_path.unlink()  # The immutable snapshot, not the upload, is authoritative.
    assert branch_report_source(*args)[0] == source
    text = branch_reports_markdown(project, store)
    assert all(
        value in text for value in [record["branch_id"], record["experiment_id"], wrapper["run_id"]]
    )
    assert "不取代主要分析" in text
    assert "未作多重比較校正" in text
    with pytest.raises(ValueError, match="no complete publication figure bundle"):
        branch_publication_source(*args)
    assert original_tree == {
        p: p.read_bytes() for p in project.output_dir.rglob("*") if p.is_file()
    }

    snapshot = project.output_dir / record["input_evidence"]["source_binding"]["source"]["snapshot"]
    ledger = store.get_path(phase, "branch_experiment_results.jsonl")
    for damaged in [source, wrapper_path, ledger, snapshot]:
        before = damaged.read_bytes()
        damaged.write_bytes(b"broken saved evidence")
        try:
            with pytest.raises((ValueError, KeyError, TypeError)):
                branch_report_source(*args)
        finally:
            damaged.write_bytes(before)
    before = ledger.read_bytes()
    ledger.write_bytes(before + before)
    try:
        with pytest.raises(ValueError, match="unique"):
            branch_reports_markdown(project, store)
    finally:
        ledger.write_bytes(before)
