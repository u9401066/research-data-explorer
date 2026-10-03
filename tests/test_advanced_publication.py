"""Complete-case/zero-cell/regularization and no-refit publication regressions."""

from copy import deepcopy
import asyncio
import csv
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from rde.application.session import DatasetEntry
from rde.domain.models.dataset import Dataset, DatasetMetadata
from rde.domain.models.project import Project
from rde.infrastructure.adapters.advanced_evidence import finite_evidence
from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator
from rde.infrastructure.adapters.dataframe_lineage import bind_source
from rde.infrastructure.adapters.pandas_loader import PandasLoader
from rde.infrastructure.prediction.splits import digest
from rde.infrastructure.visualization.advanced_publication import figures, publication_result, SCOPE


def saved(tmp_path, method, *, fast=False, zero_cell=False):
    rng = np.random.default_rng(394)
    n = 1204 if method == "propensity_score" else 220
    group = np.array([0, 1] * (n // 2))
    x = rng.normal(size=n)
    frame = pd.DataFrame(
        {
            "x": x,
            "category": rng.choice(["alpha", "beta", "gamma"], n),
            "group": group,
            "y": (3 + x + rng.normal(size=n))
            if method == "multiple_regression"
            else rng.binomial(1, 1 / (1 + np.exp(-x))),
        }
    )
    if zero_cell:
        frame.loc[frame.group == 0, "y"] = 0
    frame.loc[[2, 5], "x"] = None
    path = tmp_path / "original.csv"
    frame.to_csv(path, index=False)
    metadata = DatasetMetadata(path, "csv", path.stat().st_size)
    frame, variables, count, _ = PandasLoader().load(metadata)
    dataset = Dataset(id="test-dataset", metadata=metadata)
    dataset.mark_loaded(variables, count)
    project = Project(
        id="test-project",
        name="Synthetic publication edge",
        data_dir=tmp_path,
        output_dir=tmp_path / "project",
        dataset_ids=[dataset.id],
    )
    binding = bind_source(project, DatasetEntry(dataset, frame))
    engine = AnalysisDelegator()
    engine._automl_available = False
    config = {
        "target": "y",
        "group_var": "group",
        "covariates": ["x", "category"],
        "confidence_level": 0.9,
    }
    if fast:
        config["backend"] = "fast"
    analysis = engine.run_analysis(frame, method, config)["result"]
    assert "error" not in analysis, analysis
    record = finite_evidence(
        {
            "status": "completed",
            "schema": "advanced-branch-evidence-v1",
            "analysis_contract": {
                "tool": "run_advanced_analysis",
                "analysis_type": method,
                "target_variable": "y",
                "confidence_level": 0.9,
                "group_variable": "group",
                "covariates": [] if method == "risk_estimates" else ["x", "category"],
            },
            "analysis_result": analysis,
            "input_evidence": {"source_binding": binding},
        }
    )
    return project, record


@pytest.mark.parametrize(
    "method", ["logistic_regression", "multiple_regression", "risk_estimates", "propensity_score"]
)
def test_full_saved_rows_six_formats_and_no_fit_or_load(tmp_path, monkeypatch, method):
    project, record = saved(tmp_path, method, zero_cell=method == "risk_estimates")
    original = deepcopy(record)
    result = publication_result(record)
    monkeypatch.setattr(AnalysisDelegator, "run_analysis", lambda *a, **kw: pytest.fail("Refit"))
    monkeypatch.setattr(PandasLoader, "load", lambda *a, **kw: pytest.fail("Reloaded source"))
    bundle = figures(result, project.output_dir / "render", "edge")
    assert record == original
    assert len(bundle) >= 3
    for item in bundle:
        publication = item["publication"]
        assert set(publication["files"]) == {"png", "pdf", "svg", "tiff", "data", "caption"}
        assert publication["text_outside_canvas"] == []
        assert publication["source_receipt_sha256"] == result["receipt_sha256"]
        assert SCOPE in publication["caption_en"]
        for file in publication["files"].values():
            assert Path(file).stat().st_size > 0
        with Image.open(publication["files"]["png"]) as img:
            assert img.info["dpi"][0] >= 299
    flow = list(csv.DictReader(Path(bundle[0]["publication"]["files"]["data"]).open()))
    case = record["analysis_result"]["case_set"]
    assert len(flow) == case["n_input"]
    assert sum(row["included"] == "True" for row in flow) == case["n_analyzed"]
    if method == "propensity_score":
        pair_csv = Path(
            next(f for f in bundle if f["plot_type"] == "advanced_pairs")["publication"]["files"][
                "data"
            ]
        )
        pairs = list(csv.DictReader(pair_csv.open()))
        assert len(pairs) == 601
        assert "No outcome effect was estimated" in bundle[-1]["publication"]["caption_en"]
    elif method == "risk_estimates":
        ratio = next(f for f in bundle if f["plot_type"] == "advanced_risk_ratio")
        row = list(csv.DictReader(Path(ratio["publication"]["files"]["data"]).open()))[0]
        assert row["ci_upper"] == ""
        assert "not censoring-adjusted" in ratio["publication"]["caption_en"]


def test_regularized_no_interval_caption_override_retains_scope(tmp_path):
    project, record = saved(tmp_path, "logistic_regression", fast=True)
    result = publication_result(record)
    bundle = figures(
        result,
        project.output_dir / "render",
        "fast",
        edition={
            "start_number": 7,
            "captions": {"1": {"title": "Author caption", "caption_en": "Saved rows only."}},
        },
    )
    assert bundle[0]["publication"]["figure_number"] == 7
    assert SCOPE in bundle[0]["publication"]["caption_en"]
    assert "recorded cleaning batch" in bundle[0]["publication"]["caption_en"]
    coefficient = next(f for f in bundle if f["plot_type"].startswith("advanced_coefficients"))
    assert "Regularized fit" in coefficient["publication"]["caption_en"]
    assert "CI unavailable" in Path(coefficient["publication"]["files"]["svg"]).read_text()


@pytest.mark.parametrize("change", ["truncated", "rows", "duplicates", "source", "hash"])
def test_incomplete_or_inconsistent_numerical_source_rejected(tmp_path, change):
    _, record = saved(tmp_path, "propensity_score")
    if change == "truncated":
        record["analysis_result"]["propensity_scores_truncated"] = True
    elif change == "rows":
        record["analysis_result"]["propensity_scores"].pop()
    elif change == "duplicates":
        record["analysis_result"]["matched_pairs"].append(
            record["analysis_result"]["matched_pairs"][0]
        )
    elif change == "source":
        record["input_evidence"]["source_binding"]["status"] = "unavailable"
    else:
        record["analysis_result"]["propensity_model"]["model_evidence"]["rows"][0]["fitted"] = -1
    record["sha256"] = digest({k: v for k, v in record.items() if k != "sha256"})
    with pytest.raises(ValueError):
        publication_result(record)


def test_saved_figures_do_not_change_numeric_projection(tmp_path):
    _, record = saved(tmp_path, "multiple_regression")
    original = publication_result(record)
    record.update(publication_result=original, figures=[{"path": "figure.png"}], artifacts=[])
    record["sha256"] = digest({k: v for k, v in record.items() if k != "sha256"})
    assert publication_result(json.loads(json.dumps(record))) == original


@pytest.mark.skipif(
    not os.getenv("RDE_JOURNAL_TEST_FONT_DIR"), reason="Local journal font required"
)
@pytest.mark.parametrize("preset", ["nature-single-v1", "plos-column-v1"])
@pytest.mark.parametrize(
    "method", ["logistic_regression", "multiple_regression", "risk_estimates", "propensity_score"]
)
def test_narrow_journal_dictionary_and_author_caption_preserve_numerical_data(
    tmp_path, monkeypatch, preset, method
):
    from rde.infrastructure.visualization.dictionary import validate_dictionary

    monkeypatch.setenv("RDE_PUBLICATION_FONT_DIR", os.environ["RDE_JOURNAL_TEST_FONT_DIR"])
    project, record = saved(
        tmp_path, method, fast=method == "logistic_regression", zero_cell=method == "risk_estimates"
    )
    result = publication_result(record)
    source = result["source_binding"]["source"]
    dictionary = {
        "schema": "publication-dictionary-v1",
        "source_sha256": source["sha256"],
        "source_sheet": None,
        "dictionary_sha256": "a" * 64,
        "dictionary_revision": 1,
        "basis": {"kind": "reviewed_revision"},
        "reviewed_at": "2026-10-03T00:00:00.000Z",
        "no_conversion_confirmed": True,
        "entries": [
            {
                "column": "group" if method == "risk_estimates" else "x",
                "label_en": "An intentionally long reviewed description preserving the original source scale",
                "source": "Explicit synthetic QA annotation",
                "levels": [],
            }
        ],
    }
    validate_dictionary(dictionary, {"source": source}, result)
    before = deepcopy(result)
    original = figures(result, project.output_dir / "original", "baseline", preset_id=preset)
    edited = figures(
        result,
        project.output_dir / "edition",
        "edited",
        preset_id=preset,
        edition={
            "start_number": 9,
            "display_dictionary": dictionary,
            "captions": {
                str(i + 1): {"title": "Reviewed figure", "caption_en": "Author text."}
                for i in range(len(original))
            },
        },
    )
    assert result == before
    for first, second in zip(original, edited, strict=True):
        a, b = first["publication"], second["publication"]
        assert SCOPE in b["caption_en"]
        assert "original source scale" in b["caption_en"]
        assert "An intentionally long reviewed description" in b["caption_en"]
        assert b["text_outside_canvas"] == []
        if method == "propensity_score":
            assert "no outcome effect was estimated" in b["caption_en"]
        elif method == "logistic_regression":
            assert "regularized fit" in b["caption_en"]

        def rows(path):
            return [
                {k: v for k, v in row.items() if k != "display_label"}
                for row in csv.DictReader(Path(path).open())
            ]

        assert rows(a["files"]["data"]) == rows(b["files"]["data"])
    dictionary["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="different source"):
        validate_dictionary(dictionary, {"source": source}, result)


@pytest.mark.parametrize(
    "method", ["logistic_regression", "multiple_regression", "risk_estimates", "propensity_score"]
)
def test_native_mcp_execution_editions_and_corrupt_source_recovery(tmp_path, monkeypatch, method):
    from test_exploration_branch_loop import _make_phase8_ready_project, _textify_tool_result
    from rde.application.pipeline import PipelinePhase
    from rde.application.session import get_session
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.tools._shared.branch_publication import branch_publication_source
    import rde.infrastructure.adapters as adapters

    _, initial = saved(tmp_path, method)
    project, store = _make_phase8_ready_project(tmp_path)
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

    def call(name, args):
        response = asyncio.run(create_server().call_tool(name, args))
        text = _textify_tool_result(response)
        assert not response.is_error and "❌" not in text, text
        return text

    call(
        "start_autoresearch_run",
        {
            "project_id": project.id,
            "max_tasks": 1,
            "max_branches": 1,
            "include_builtin_suggestions": False,
            "agent_proposals": [
                {
                    "hypothesis": "Synthetic source and plot preservation QA",
                    "reason": "Engineering check only",
                    "variables": list(frame.columns),
                    "analysis_contract": {**initial["analysis_contract"], "create_figures": True},
                }
            ],
        },
    )
    call("run_autoresearch_next_task", {"project_id": project.id})
    event = store.load(PipelinePhase.EXECUTE_EXPLORATION, "branch_experiment_results.jsonl")[-1]
    wrapper_path = Path(event["artifact"])
    wrapper = json.loads(wrapper_path.read_text())
    execution = wrapper["contract_execution"]
    assert execution["executed"] and execution["status"] == "completed", execution
    source = Path(execution["artifact_path"])
    record = json.loads(source.read_text())
    args = {
        "project_id": project.id,
        "branch_id": record["branch_id"],
        "experiment_id": record["experiment_id"],
        "expected_record_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "preset_id": "journal-neutral-english-v1",
        "edition_id": str(uuid.uuid4()),
        "start_number": 7,
    }
    originals = {
        p: p.read_bytes()
        for p in [
            source,
            wrapper_path,
            *[project.output_dir / a["path"] for a in record["artifacts"]],
        ]
    }
    monkeypatch.setattr(
        AnalysisDelegator, "run_analysis", lambda *a, **kw: pytest.fail("Edition refit")
    )
    monkeypatch.setattr(PandasLoader, "load", lambda *a, **kw: pytest.fail("Edition parsed source"))
    # Historical figures depend on the retained original bytes, not a live upload.
    path.unlink()
    edition = json.loads(call("render_branch_publication", args))
    assert "primary_binding" not in edition
    assert edition["source_binding"] == record["input_evidence"]["source_binding"]
    assert len(edition["figures"]) == len(record["figures"])
    assert json.loads(call("render_branch_publication", args)) == edition
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    ledger = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "branch_experiment_results.jsonl")
    snapshot = project.output_dir / record["input_evidence"]["source_binding"]["source"]["snapshot"]
    for damaged in (
        source,
        wrapper_path,
        ledger,
        snapshot,
        project.output_dir / record["artifacts"][-1]["path"],
    ):
        original = damaged.read_bytes()
        damaged.write_bytes(b"invalid evidence QA")
        try:
            with pytest.raises((ValueError, KeyError, TypeError)):
                branch_publication_source(
                    project,
                    args["branch_id"],
                    args["experiment_id"],
                    args["expected_record_sha256"],
                )
        finally:
            damaged.write_bytes(original)
    original = ledger.read_bytes()
    ledger.write_bytes(original + original)
    with pytest.raises(ValueError, match="unique"):
        branch_publication_source(
            project, args["branch_id"], args["experiment_id"], args["expected_record_sha256"]
        )
    ledger.write_bytes(original)


@pytest.mark.parametrize(
    "method", ["logistic_regression", "multiple_regression", "risk_estimates", "propensity_score"]
)
def test_readable_full_report_preserves_saved_terms_and_undefined_values(
    tmp_path, monkeypatch, method
):
    from rde.infrastructure.clinical.advanced_report import markdown, cell, number
    from rde.interface.mcp.tools.analysis_tools import _format_advanced_analysis_output

    project, record = saved(tmp_path, method, zero_cell=method == "risk_estimates")
    original = deepcopy(record)
    monkeypatch.setattr(AnalysisDelegator, "run_analysis", lambda *a, **kw: pytest.fail("Refit"))
    monkeypatch.setattr(PandasLoader, "load", lambda *a, **kw: pytest.fail("Reload"))
    result = record["analysis_result"]
    text = _format_advanced_analysis_output(
        analysis_type=method,
        source=result["engine"],
        analysis_result=result,
        artifact_path=Path("/private/path/numerical.json"),
        automl_available=False,
        exploratory=True,
        source_binding=record["input_evidence"]["source_binding"],
    )
    assert record == original
    assert "個案納入與排除" in text and "未校正跨模型的多重探索" in text
    assert "numerical" in text and "/private/path" not in text
    assert "included_row_positions" not in text and "saved_count" not in text
    assert "predictor_coding" not in text and "diagnostic_policy" not in text
    assert "| 階段 | 資料列數 |\n|---|---|" in text
    if method == "risk_estimates":
        for item in result["estimates"].values():
            assert cell(number(item["estimate"])) in text
        assert "無可用區間" in text and "病例對照" in text
    else:
        model = result["propensity_model"] if method == "propensity_score" else result
        for term in model["model_evidence"]["design_columns"]:
            assert ("截距（Intercept）" if term == "const" else cell(term)) in text
        assert "參照 alpha" in text and "beta 對 alpha" in text
        if method == "propensity_score":
            assert "沒有另外估計臨床結果效果" in text and "不是零差異" in text
            for key in [
                "balance_diagnostics",
                "weighted_balance_diagnostics",
                "matched_balance_diagnostics",
            ]:
                for item in result[key].values():
                    assert cell(number(item["standardized_mean_difference"])) in text
    assert markdown(result, exploratory=False) is not None


def test_readable_regularized_model_and_hostile_names_do_not_invent_intervals(tmp_path):
    from rde.infrastructure.clinical.advanced_report import markdown, cell, p_text

    _, record = saved(tmp_path, "logistic_regression", fast=True)
    result = record["analysis_result"]
    text = markdown(result)
    assert "正則化" in text and "中心化及標準化" in text
    assert "無法估計／未提供" in text and "一般未懲罰模型" in text
    hostile = "x|<img src=x>\n# heading [link](javascript:x)"
    result["model_evidence"]["predictor_coding"][0]["source_column"] = hostile
    text = markdown(result)
    assert cell(hostile) in text and "<img" not in text and "\n# heading" not in text
    assert p_text(False) == "無法估計／未提供"
    assert p_text(None) == "無法估計／未提供"
    assert "不代表真實機率等於零" in p_text(0.0)


def test_publication_coding_is_readable_without_raw_policy_json(tmp_path):
    from rde.infrastructure.clinical.advanced_report import (
        binary_coding,
        predictor_coding,
        propensity_policy,
    )

    _, record = saved(tmp_path, "propensity_score")
    result = record["analysis_result"]
    coding = result["propensity_model"]["model_evidence"]["predictor_coding"]
    text = (
        predictor_coding(coding)
        + binary_coding(result["treatment_coding"])
        + propensity_policy(result["diagnostic_policy"])
    )
    assert "'beta' versus 'alpha'" in text and "'gamma' versus 'alpha'" in text
    assert "without replacement" in text and "No caliper" in text
    assert "p/e" in text and "No clinical outcome effect" in text
    assert '{"' not in text and "predictor_coding" not in text
