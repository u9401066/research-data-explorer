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
            "features_available_at_prediction": True,
            "candidates": ["linear", "random_forest"],
            "bootstrap_samples": 20,
            **kwargs,
        }
    )


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


def prediction_project(tmp_path):
    from test_exploration_branch_loop import _make_phase8_ready_project
    from rde.application.pipeline import PipelinePhase
    from rde.application.session import get_session
    from rde.domain.models.dataset import Dataset

    project, store = _make_phase8_ready_project(tmp_path)
    frame, spec = sample(), specification(candidates=["linear"])
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


def test_real_mcp_prediction_persists_evidence_collects_and_restores_without_refit(
    tmp_path, monkeypatch
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

    project, store, dataset, spec = prediction_project(tmp_path)

    async def call(name, args):
        return await create_server().call_tool(name, args)

    options = {"dataset_id": dataset.id, "prediction_options": spec.to_dict()}
    response = asyncio.run(call("run_prediction_study", options))
    assert not response.is_error, response.content
    record = persisted_predictions(store)[0]
    assert verify_prediction_artifacts(record, project.output_dir)
    assert len(record["figures"]) == 4
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
