"""Main MCP analyses retain original figures, source closure and no-refit editions."""

import asyncio
import hashlib
import json
import uuid

import pytest

from rde.application.pipeline import PipelinePhase
from rde.application.session import DatasetEntry, get_session
from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.interface.mcp.server import create_server
from rde.interface.mcp.tools._shared.advanced_study import advanced_study_source
from rde.infrastructure.visualization.advanced_publication import PRIMARY_SCOPE, SCOPE
from test_advanced_publication import saved
from test_exploration_branch_loop import _make_phase8_ready_project, _textify_tool_result


def call(name, arguments, *, error=False):
    response = asyncio.run(create_server().call_tool(name, arguments))
    text = _textify_tool_result(response)
    if not error:
        assert not response.is_error and "❌" not in text, text
    return text


def setup(tmp_path, monkeypatch, method):
    import rde.infrastructure.adapters as adapters

    _, initial = saved(tmp_path, method, zero_cell=method == "risk_estimates")
    project, store = _make_phase8_ready_project(tmp_path)
    from rde.domain.models.dataset import Dataset, DatasetMetadata

    path = tmp_path / "original.csv"
    metadata = DatasetMetadata(path, "csv", path.stat().st_size)
    frame, variables, count, _ = PandasLoader().load(metadata)
    dataset = Dataset(id="demo-dataset", metadata=metadata)
    dataset.mark_loaded(variables, count)
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    engine = AnalysisDelegator()
    engine._automl_available = False
    monkeypatch.setattr(adapters, "get_analysis_delegator", lambda: engine)
    args = {k: v for k, v in initial["analysis_contract"].items() if k != "tool"}
    return project, store, DatasetEntry(dataset, frame), {**args, "dataset_id": dataset.id}


@pytest.mark.parametrize(
    "method", ["logistic_regression", "multiple_regression", "risk_estimates", "propensity_score"]
)
def test_main_mcp_figures_history_no_refit_and_retained_evidence(tmp_path, monkeypatch, method):
    project, store, entry, args = setup(tmp_path, monkeypatch, method)
    text = call("run_advanced_analysis", args)
    phase = project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value
    paths = list(phase.glob("advanced_study_*.json"))
    assert len(paths) == 1
    path = paths[0]
    record = json.loads(path.read_text())
    assert record["result"]["spec"]["family"] == "advanced_analysis"
    assert record["publication_scope"] == "main_analysis"
    assert "保存計畫及偏離紀錄" in text and "個案納入與排除" in text
    assert text.count("![advanced_") == len(record["figures"])
    for figure in record["figures"]:
        assert PRIMARY_SCOPE in figure["publication"]["caption_en"]
        assert SCOPE not in figure["publication"]["caption_en"]
        assert figure["publication"]["text_outside_canvas"] == []
    originals = {
        p: p.read_bytes()
        for p in [path, *[project.output_dir / a["path"] for a in record["artifacts"]]]
    }
    if method == "logistic_regression":
        # Identical roles may be rerun: neither old bytes nor old manifest entries disappear.
        call("run_advanced_analysis", args)
        assert len(list(phase.glob("advanced_study_*.json"))) == 2
        manifest = store.load(PipelinePhase.EXECUTE_EXPLORATION, "visualization_manifest.json")
        assert len(manifest) == len(record["figures"]) * 2
        assert all(p.read_bytes() == raw for p, raw in originals.items())
    monkeypatch.setattr(AnalysisDelegator, "run_analysis", lambda *a, **kw: pytest.fail("Refit"))
    monkeypatch.setattr(PandasLoader, "load", lambda *a, **kw: pytest.fail("Reload"))
    # Historical editing must use retained evidence even when the live upload/plan changes.
    entry.dataset.metadata.file_path.unlink()
    plan = project.artifacts_dir / PipelinePhase.PLAN_REGISTRATION.value / "analysis_plan.yaml"
    plan.write_text("later unrelated plan revision")
    edition_args = {
        "project_id": project.id,
        "study_artifact": path.name,
        "expected_record_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "preset_id": "journal-neutral-english-v1",
        "edition_id": str(uuid.uuid4()),
        "start_number": 9,
        "captions": {"1": {"caption_en": "Author-reviewed figure caption."}},
    }
    edition = json.loads(call("render_publication_figures", edition_args))
    assert edition["publication_scope"] == "main_analysis"
    assert edition["source_binding"] == record["input_evidence"]["source_binding"]
    assert edition["figures"][0]["publication"]["figure_number"] == 9
    assert PRIMARY_SCOPE in edition["figures"][0]["publication"]["caption_en"]
    assert json.loads(call("render_publication_figures", edition_args)) == edition
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    source_snapshot = project.output_dir / record["source"]["snapshot"]
    for damaged in [path, source_snapshot, *originals.keys()]:
        original = damaged.read_bytes()
        damaged.write_bytes(b"corrupted saved evidence")
        try:
            with pytest.raises((ValueError, KeyError, TypeError)):
                advanced_study_source(project, path.name, edition_args["expected_record_sha256"])
        finally:
            damaged.write_bytes(original)


def test_render_failure_keeps_complete_numerical_evidence(tmp_path, monkeypatch):
    import rde.interface.mcp.tools._shared.advanced_study as study

    project, _, _, args = setup(tmp_path, monkeypatch, "logistic_regression")

    def fail(*a, **kw):
        raise RuntimeError("Synthetic renderer failure")

    monkeypatch.setattr(study, "figures", fail)
    text = call("run_advanced_analysis", args, error=True)
    assert "Synthetic renderer failure" in text
    phase = project.artifacts_dir / PipelinePhase.EXECUTE_EXPLORATION.value
    assert not list(phase.glob("advanced_study_*.json"))
    numerical = list(phase.glob("advanced_studies/*/numerical-evidence.json"))
    assert len(numerical) == 1
    record = json.loads(numerical[0].read_text())
    assert record["analysis_result"]["model_evidence"]["rows"]
    attempt = json.loads(numerical[0].with_name("render-attempt.json").read_text())
    assert attempt["status"] == "failed"
    assert "Synthetic renderer failure" in attempt["error"]
