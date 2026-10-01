"""Prediction regressions prove holdout isolation, not just successful fitting."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from rde.infrastructure.prediction.contract import PredictionSpec
from rde.infrastructure.prediction.engine import PredictionFailure, run_prediction
from rde.infrastructure.prediction.metrics import bootstrap_intervals, score_metrics
from rde.infrastructure.prediction.splits import outer_split, prepare_population, training_folds


def sample(n=240):
    rng = np.random.default_rng(18)
    x = rng.normal(size=n)
    frame = pd.DataFrame(
        {
            "x": x,
            "noise": rng.normal(size=n),
            "category": np.where(x > 0, "a", "b"),
            "outcome": rng.binomial(1, 1 / (1 + np.exp(-x))),
            "continuous": 2 * x + rng.normal(size=n),
            "subject": np.repeat(np.arange((n + 1) // 2), 2)[:n],
            "date": pd.date_range("2020-01-01", periods=n).strftime("%Y-%m-%d"),
        }
    )
    frame.loc[::13, "x"] = np.nan
    return frame


def specification(**kwargs):
    return PredictionSpec.parse(
        {
            "target": "outcome",
            "predictors": ["x", "noise", "category"],
            "categorical_predictors": ["category"],
            "prediction_time_definition": "Admission, before treatment or outcome",
            "study_design": "observational_cohort",
            "sampling": "single_gate",
            "sampling_description": "Synthetic cohort with one common inclusion path",
            "target_definition": "Synthetic endpoint; no clinical claims",
            "features_available_at_prediction": True,
            "candidates": ["linear", "random_forest"],
            "bootstrap_samples": 20,
            **kwargs,
        }
    )


def decision_options(**changes):
    return {
        "thresholds": [0.2, 0.8, 0.95],
        "action": "Synthetic next-step assessment",
        "threshold_basis": "Prespecified engineering demonstration, no clinical utility claim",
        "independent_observations": True,
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"study_design": "case_control", "sampling": "single_gate"},
        {"study_design": "observational_cohort", "sampling": "two_gate"},
        {"study_design": "diagnostic_accuracy", "task": "regression"},
        {"sampling_description": ""},
        {"target_definition": ""},
        {"sampling": "unknown", "decision_curve": decision_options()},
        {"decision_curve": decision_options(independent_observations=False)},
        {"decision_curve": decision_options(thresholds=[0.8, 0.2])},
        {"decision_curve": decision_options(thresholds=[0.2, 0.2])},
        {"decision_curve": decision_options(thresholds=[0])},
        {"decision_curve": decision_options(thresholds=[True])},
    ],
)
def test_prediction_design_cannot_imply_population_risk_or_silently_pick_utilities(changes):
    with pytest.raises(ValueError):
        specification(**changes)


def test_selected_samples_retain_design_and_sample_performance_without_population_claims():
    from rde.infrastructure.prediction.report import markdown

    frame = sample()
    cohort = run_prediction(frame, specification(candidates=["linear"]))
    for design, sampling in [("diagnostic_accuracy", "unknown"), ("case_control", "two_gate")]:
        result = run_prediction(
            frame, specification(candidates=["linear"], study_design=design, sampling=sampling)
        )
        assert result["selection"] == cohort["selection"]
        assert result["final_fit"] == cohort["final_fit"]
        assert result["validation"]["metrics"] == cohort["validation"]["metrics"]
        assert result["validation"]["decision_curve"] is None
        assert result["validation"]["population_risk_validated"] is False
        assert "selected sample only" in result["validation"]["metric_interpretation"]
        assert "不能解讀為臨床母群風險" in markdown(result)
        assert (
            "病例對照研究" in markdown(result)
            if design == "case_control"
            else "診斷研究" in markdown(result)
        )


def test_decision_curve_manual_counts_and_paired_uncertainty():
    from rde.infrastructure.prediction.metrics import decision_curve_points

    points = decision_curve_points([1, 0, 1, 0, 1], [0.9, 0.8, 0.3, 0.1, 0.1], [0.2, 0.8, 0.95])
    assert [p["true_positives"] for p in points] == [2, 1, 0]
    assert [p["false_positives"] for p in points] == [1, 1, 0]
    assert [p["model"] for p in points] == pytest.approx([0.35, -0.6, 0])
    assert [p["treat_all"] for p in points] == pytest.approx([0.5, -1, -7])
    assert [p["difference_vs_all"] for p in points] == pytest.approx([-0.15, 0.4, 7])
    spec = specification(decision_curve=decision_options(thresholds=[0.2]), bootstrap_samples=200)
    y = np.asarray([0, 1] * 4)
    receipt = bootstrap_intervals(y, y, None, spec, lambda: None)
    curve = receipt["decision_curve"]["points"][0]
    # Perfect classification: improvement over treating all is 0.25 * the
    # negative fraction on EACH shared resample. Independent CI subtraction is wrong.
    draws = np.random.default_rng(spec.seed + 1).integers(0, 8, size=(200, 8))
    expected = 0.25 * (1 - y[draws].mean(axis=1))
    bounds = curve["intervals"]["difference_vs_all"]
    assert [bounds["lower"], bounds["upper"]] == pytest.approx(
        np.quantile(expected, [0.025, 0.975])
    )
    assert bounds["estimable_replicates"] == 200
    assert curve["model"] == 0.5 and curve["difference_vs_all"] == 0.125


def test_decision_curves_do_not_refit_select_or_mask_repeated_participants():
    frame = sample()
    frame["subject"] = range(len(frame))
    spec = specification(candidates=["linear"], split="group", subject_variable="subject")
    baseline = run_prediction(frame, spec)
    result = run_prediction(frame, replace(spec, decision_curve=decision_options()))
    for key in ["selection", "candidates", "final_fit", "outer_split", "cv_splits"]:
        assert result[key] == baseline[key]
    assert result["validation"]["uncertainty"] == baseline["validation"]["uncertainty"]
    frame.loc[0, "subject"] = frame.loc[1, "subject"]
    frame.loc[0, "outcome"] = np.nan
    with pytest.raises(PredictionFailure, match="one independent observation"):
        run_prediction(frame, replace(spec, decision_curve=decision_options()))


def test_heldout_features_cannot_change_cv_or_training_transform():
    frame = sample()
    original = frame.copy(deep=True)
    spec = specification()
    first = run_prediction(frame, spec)
    pd.testing.assert_frame_equal(frame, original)
    heldout = first["outer_split"]["validation_positions"]
    frame.loc[heldout, "x"] = 1_000_000
    frame.loc[heldout, "category"] = "never-seen-in-training"
    second = run_prediction(frame, spec)
    assert first["selection"] == second["selection"]
    assert first["candidates"] == second["candidates"]
    assert first["final_fit"] == second["final_fit"]
    assert first["validation"]["predictions"] != second["validation"]["predictions"]
    assert "never-seen-in-training" not in str(second["final_fit"])
    for candidate in first["candidates"]:
        assert not set(heldout).intersection(
            p["source_position"] for f in candidate["folds"] for p in f["predictions"]
        )
    pd.testing.assert_frame_equal(original, sample())
    json.dumps(first, allow_nan=False)


def test_subject_partition_and_ci_sample_whole_subjects():
    frame = sample()
    spec = specification(split="group", subject_variable="subject", candidates=["linear"])
    result = run_prediction(frame, spec)
    for split in [result["outer_split"], *result["cv_splits"]]:
        assert not set(frame.iloc[split["train_positions"]].subject).intersection(
            frame.iloc[split["validation_positions"]].subject
        )
        assert split["subject_overlap"] == 0
    assert result["validation"]["uncertainty"]["unit"] == "subject_cluster"
    assert (
        result["validation"]["uncertainty"]["units"] == result["outer_split"]["validation_subjects"]
    )


def test_temporal_boundary_purges_subject_and_preserves_tied_dates():
    frame = sample(320)
    frame.loc[238, "subject"] = frame.loc[260, "subject"]
    frame.loc[240, "date"] = frame.loc[239, "date"]
    cutoff = frame.loc[239, "date"]
    spec = specification(
        split="temporal",
        time_variable="date",
        cutoff=cutoff,
        subject_variable="subject",
        candidates=["linear"],
    )
    population = prepare_population(frame, spec)
    outer = outer_split(population, spec)
    assert 238 in outer["purged_train_positions"]
    assert 239 in outer["validation_positions"] and 240 in outer["validation_positions"]
    for partition in [outer, *training_folds(population, outer, spec)]:
        assert partition["train_time_max"] < partition["validation_time_min"]
        assert partition["subject_overlap"] == 0
    result = run_prediction(frame, spec)
    assert result["status"] == "completed"


def test_target_never_imputed_and_continuous_predictions_are_validated():
    frame = sample()
    frame.loc[4, "continuous"] = np.inf
    frame.loc[5, "continuous"] = np.nan
    before = frame.copy(deep=True)
    result = run_prediction(
        frame, specification(task="regression", target="continuous", candidates=["linear"])
    )
    assert result["exclusions"]["missing_or_invalid_target"] == [4, 5]
    assert result["selection"]["criterion"] == "rmse"
    assert (
        result["validation"]["metrics"]["rmse"]
        < result["validation"]["baseline"]["metrics"]["rmse"]
    )
    pd.testing.assert_frame_equal(frame, before)


def test_failed_candidate_does_not_become_fabricated_score_or_completed_study():
    frame = sample()
    spec = specification()
    population = prepare_population(frame, spec)
    training = outer_split(population, spec)["train_positions"]
    frame.loc[training, "x"] = np.nan
    with pytest.raises(PredictionFailure, match="No candidate") as caught:
        run_prediction(frame, spec)
    receipt = caught.value.receipt
    assert receipt["status"] == "failed"
    assert all(c["status"] == "failed" and c["cv_score"] is None for c in receipt["candidates"])
    assert "validation" not in receipt
    assert "Training-only feature" in receipt["candidates"][0]["error"]


def test_one_class_validation_and_zero_denominators_are_not_fabricated():
    spec = specification()
    score = score_metrics([0] * 15, [0.1] * 15, spec)
    assert score["auroc"] is None and score["sensitivity"] is None and score["ppv"] is None
    interval = bootstrap_intervals([0] * 15, [0.1] * 15, None, spec, lambda: None)
    assert interval["intervals"]["auroc"]["estimable_replicates"] == 0
    assert interval["intervals"]["auroc"]["lower"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"features_available_at_prediction": False},
        {"predictors": ["outcome"]},
        {"subject_variable": "subject"},
        {"split": "temporal"},
        {"cv_folds": True},
        {"candidates": [{"code": "arbitrary"}]},
        {"categorical_predictors": [{}]},
        {"time_variable": "date"},
        {"threshold": float("nan")},
        {"surprise": "unknown"},
    ],
)
def test_reject_ambiguous_or_unapproved_contract(change):
    with pytest.raises(ValueError):
        specification(**change)


def test_budget_exhaustion_retains_failure_receipt():
    with pytest.raises(PredictionFailure, match="budget") as caught:
        run_prediction(sample(), specification(), budget_seconds=0)
    assert caught.value.receipt["status"] == "failed"
    assert not caught.value.receipt["candidates"]


def test_binary_infinite_target_is_an_excluded_case():
    frame = sample()
    frame["outcome"] = frame.outcome.astype(float)
    frame.loc[4, "outcome"] = np.inf
    result = run_prediction(
        frame, replace(specification(candidates=["linear"]), bootstrap_samples=0)
    )
    assert result["exclusions"]["missing_or_invalid_target"] == [4]
    assert result["validation"]["uncertainty"]["replicates_requested"] == 0


def prediction_project(tmp_path, **options):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.pipeline import PipelinePhase
    from rde.application.session import get_session
    from rde.domain.models.dataset import Dataset

    project, store = _make_phase8_ready_project(tmp_path)
    frame, spec = sample(), specification(candidates=["linear"], **options)
    dataset = Dataset(row_count=len(frame))
    get_session().register_dataset(dataset, frame)
    project.dataset_ids = [dataset.id]
    store.save(
        PipelinePhase.PLAN_REGISTRATION,
        "analysis_plan.yaml",
        {
            "locked": True,
            "analyses": [
                {
                    "type": "run_prediction_study",
                    "variables": [spec.target, *spec.predictors],
                    "execution_arguments": {"prediction_options": spec.to_dict()},
                }
            ],
        },
    )
    store.save(PipelinePhase.SCHEMA_REGISTRY, "profile_summary.json", {"engine": "fixture"})
    store.save(
        PipelinePhase.SCHEMA_REGISTRY,
        "quality_report.json",
        {"is_analysis_ready": True, "issues": [], "critical_issue_count": 0},
    )
    return project, store, dataset, spec


@pytest.mark.parametrize("curve", [None, decision_options()])
def test_real_mcp_prediction_persists_evidence_collects_and_restores_without_refit(
    tmp_path, monkeypatch, curve
):
    import asyncio
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.server import create_server
    from rde.interface.mcp.tools.prediction_tools import (
        persisted_predictions,
        verify_prediction_artifacts,
    )
    from rde.interface.mcp.tools.report_tools import _evaluate_report_readiness
    from rde.infrastructure.prediction import engine

    project, store, dataset, spec = prediction_project(tmp_path, decision_curve=curve)

    async def call(name, args):
        return await create_server().call_tool(name, args)

    options = {"dataset_id": dataset.id, "prediction_options": spec.to_dict()}
    response = asyncio.run(call("run_prediction_study", options))
    assert not response.is_error, response.content
    record = persisted_predictions(store)[0]
    assert verify_prediction_artifacts(record, project.output_dir)
    assert len(record["figures"]) == (7 if curve else 6)
    from pathlib import Path
    from PIL import Image
    import xml.etree.ElementTree as ET

    for figure in record["figures"]:
        publication = figure["publication"]
        paths = publication["files"]
        assert publication["language"] == "en"
        assert publication["text_outside_canvas"] == []
        assert publication["source_receipt_sha256"] == record["result"]["receipt_sha256"]
        assert set(paths) == {"png", "pdf", "svg", "tiff", "caption", "data"}
        with Image.open(paths["png"]) as png, Image.open(paths["tiff"]) as tiff:
            assert png.width >= 2100
            assert png.size == tiff.size
            assert png.info["dpi"][0] == pytest.approx(300, abs=0.01)
            assert tiff.info["dpi"] == (300, 300)
            assert tiff.mode == "RGB"
        assert Path(paths["pdf"]).read_bytes().startswith(b"%PDF-")
        svg = ET.parse(paths["svg"]).getroot()
        assert svg.tag.endswith("svg")
        assert svg.findall(".//{http://www.w3.org/2000/svg}path")
        assert not svg.findall(".//{http://www.w3.org/2000/svg}image")
        assert "中文解釋" in Path(paths["caption"]).read_text()
        assert len(Path(paths["data"]).read_text().splitlines()) > 1
    if curve:
        assert record["result"]["validation"]["decision_curve"]["points"][0]["threshold"] == 0.2
        assert any(a["path"].endswith("_decision_curve.csv") for a in record["artifacts"])
    assert all((project.output_dir / item["path"]).is_file() for item in record["artifacts"])
    monkeypatch.setattr(
        engine, "run_prediction", lambda *a, **kw: pytest.fail("saved holdout refitted")
    )
    restored = asyncio.run(call("run_prediction_study", options))
    assert "No model was refitted" in restored.content[0].text
    collected = asyncio.run(call("collect_results", {"project_id": project.id}))
    assert not collected.is_error, collected.content
    summary = store.load(PipelinePhase.COLLECT_RESULTS, "results_summary.json")
    assert summary["predictions"][0]["receipt_sha256"] == record["result"]["receipt_sha256"]
    ready = _evaluate_report_readiness(summary, store, require_report_generation=False)
    assert ready["ready"], ready
    report = asyncio.run(call("assemble_report", {"project_id": project.id}))
    assert not report.is_error, report.content
    report_text = store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md")
    assert "Held-out performance" in report_text
    assert record["result"]["receipt_sha256"] in report_text
    assert "prediction_validation" in report_text
    assert _evaluate_report_readiness(summary, store)["ready"]


def test_real_mcp_changed_plan_cannot_reuse_an_inspected_holdout(tmp_path):
    import asyncio
    from rde.application.pipeline import PipelinePhase
    from rde.interface.mcp.server import create_server

    _, store, dataset, spec = prediction_project(tmp_path)

    async def call(options):
        return await create_server().call_tool(
            "run_prediction_study", {"dataset_id": dataset.id, "prediction_options": options}
        )

    assert not asyncio.run(call(spec.to_dict())).is_error
    changed = {**spec.to_dict(), "threshold": 0.2}
    denied = asyncio.run(call(changed))
    assert denied.is_error and "exactly match" in denied.content[0].text
    plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
    plan["analyses"][0]["execution_arguments"]["prediction_options"] = changed
    store.save(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml", plan)
    denied = asyncio.run(call(changed))
    assert denied.is_error and "inspected holdout" in denied.content[0].text


def test_render_failure_resumes_numeric_receipt_instead_of_refitting(tmp_path, monkeypatch):
    import asyncio
    from rde.interface.mcp.server import create_server
    from rde.infrastructure.prediction import engine, report

    _, _, dataset, spec = prediction_project(tmp_path)

    async def call():
        return await create_server().call_tool(
            "run_prediction_study", {"dataset_id": dataset.id, "prediction_options": spec.to_dict()}
        )

    real_figures = report.figures

    def broken(*args):
        raise OSError("simulated renderer failure")

    monkeypatch.setattr(report, "figures", broken)
    first = asyncio.run(call())
    assert first.is_error and "renderer failure" in first.content[0].text
    monkeypatch.setattr(report, "figures", real_figures)
    monkeypatch.setattr(
        engine,
        "run_prediction",
        lambda *a, **kw: pytest.fail("holdout refitted after rendering failed"),
    )
    second = asyncio.run(call())
    assert not second.is_error, second.content


def test_changed_source_bytes_cannot_silently_reuse_prediction_result(tmp_path):
    import asyncio
    from rde.application.session import get_session
    from rde.domain.models.dataset import DatasetMetadata
    from rde.interface.mcp.server import create_server

    _, _, dataset, spec = prediction_project(tmp_path)
    path = tmp_path / "source.csv"
    get_session().get_dataset_entry(dataset.id).dataframe.to_csv(path, index=False)
    dataset.metadata = DatasetMetadata(
        file_path=path, file_format="csv", file_size_bytes=path.stat().st_size
    )

    async def call():
        return await create_server().call_tool(
            "run_prediction_study", {"dataset_id": dataset.id, "prediction_options": spec.to_dict()}
        )

    assert not asyncio.run(call()).is_error
    # In-memory selected values are unchanged, but original source bytes are not.
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    rejected = asyncio.run(call())
    assert rejected.is_error and "inspected holdout" in rejected.content[0].text
