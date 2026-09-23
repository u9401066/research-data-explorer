"""Evidence gates for a prediction report, independent of generic EDA method counts."""

from __future__ import annotations

import math

from rde.application.pipeline import PipelinePhase
from rde.interface.mcp.tools.prediction_tools import (
    persisted_predictions,
    planned_spec,
    prediction_plan,
    verify_prediction_artifacts,
)


def prediction_readiness(store, *, data_quality: dict, require_report_generation=True) -> dict:
    plan = prediction_plan(store)
    spec = planned_spec(plan).to_dict()
    records = persisted_predictions(store)
    checks = []

    def check(key, passed, evidence):
        checks.append({"id": key, "passed": bool(passed), "evidence": evidence})

    check(
        "single_completed_prediction_receipt", len(records) == 1, [r["artifact"] for r in records]
    )
    result = records[0]["result"] if len(records) == 1 else {}
    check(
        "locked_specification",
        result.get("spec") == spec,
        ["phase_06_plan_registration/analysis_plan.yaml"],
    )
    root = store.get_path(PipelinePhase.EXECUTE_EXPLORATION, "unused").parents[2]
    check(
        "artifact_integrity",
        len(records) == 1 and verify_prediction_artifacts(records[0], root),
        [r["artifact"] for r in records],
    )
    outer = result.get("outer_split", {})
    train, valid = set(outer.get("train_positions", [])), set(outer.get("validation_positions", []))
    check(
        "disjoint_outer_partition",
        train and valid and not train.intersection(valid),
        ["outer_split"],
    )
    folds = result.get("cv_splits", [])
    check(
        "cv_uses_training_only",
        len(folds) == spec["cv_folds"]
        and all(
            set(f["train_positions"]).issubset(train)
            and set(f["validation_positions"]).issubset(train)
            and not set(f["train_positions"]).intersection(f["validation_positions"])
            for f in folds
        ),
        ["cv_splits"],
    )
    if spec["subject_variable"]:
        check(
            "subject_separation",
            outer.get("subject_overlap") == 0 and all(f.get("subject_overlap") == 0 for f in folds),
            ["outer_split", "cv_splits"],
        )
    if spec["split"] == "temporal":
        check(
            "strict_time_order",
            bool(folds)
            and all(
                f.get("train_time_max", "z") < f.get("validation_time_min", "")
                for f in [outer, *folds]
            ),
            ["outer_split", "cv_splits"],
        )
    selection = result.get("selection", {})
    selected = next(
        (c for c in result.get("candidates", []) if c["name"] == selection.get("selected")), {}
    )
    check(
        "complete_training_selection",
        selected.get("status") == "completed"
        and len(selected.get("folds", [])) == spec["cv_folds"]
        and selection.get("outer_validation_used") is False,
        ["candidates", "selection"],
    )
    validation = result.get("validation", {})
    scores = validation.get("metrics", {})
    needed = (
        ["auroc", "average_precision", "brier", "log_loss"]
        if spec["task"] == "binary"
        else ["mae", "rmse"]
    )
    check(
        "heldout_metrics_estimable",
        all(
            isinstance(scores.get(key), (float, int)) and math.isfinite(scores[key])
            for key in needed
        ),
        ["validation.metrics"],
    )
    check(
        "prediction_row_coverage",
        [p["source_position"] for p in validation.get("predictions", [])]
        == outer.get("validation_positions"),
        ["validation.predictions"],
    )
    check(
        "data_quality_review",
        not data_quality.get("missing_requirements"),
        [
            "phase_02_schema_registry/quality_report.json",
            "phase_07_pre_explore_check/readiness_checklist.json",
        ],
    )
    expected_plots = (
        {"prediction_cv", "prediction_roc", "prediction_pr", "prediction_calibration"}
        if spec["task"] == "binary"
        else {"prediction_cv", "prediction_observed", "prediction_residual"}
    )
    actual_plots = (
        {f["plot_type"] for f in records[0].get("figures", [])} if len(records) == 1 else set()
    )
    check("task_specific_figures", expected_plots == actual_plots, sorted(expected_plots))
    if require_report_generation:
        report = str(store.load(PipelinePhase.REPORT_ASSEMBLY, "eda_report.md") or "")
        check(
            "report_contains_validation_and_limits",
            all(
                part in report
                for part in [
                    "Prediction validation",
                    "Held-out performance",
                    "Interpretation and limitations",
                    result.get("receipt_sha256") or "missing receipt",
                ]
            ),
            ["phase_10_report_assembly/eda_report.md"],
        )
    missing = [c["id"] for c in checks if not c["passed"]]
    return {
        "ready": not missing,
        "scope": "prediction_report_evidence",
        "target_tier": "prediction_validation",
        "current_tier": "prediction_validation"
        if not missing
        else "incomplete_prediction_validation",
        "review_status": "pass" if not missing else "incomplete",
        "publication_bundle_met": not missing,
        "data_quality": data_quality,
        "analysis_depth": {"ready": not missing, "checks": checks, "missing_requirements": missing},
        "semantic_report_quality": {
            "ready": not any(key.startswith("report_") for key in missing),
            "scope": "prediction-specific numerical evidence and interpretation",
            "missing_requirements": [key for key in missing if key.startswith("report_")],
        },
        "core_goal_audit": {
            "scope": "prediction_report_evidence",
            "ready": not missing,
            "checks": checks,
            "missing_goals": missing,
        },
        "missing_requirements": missing,
        "applicability": "Report evidence completeness only; no clinical deployment readiness or external validation claim.",
    }


def prediction_deliverables(project, store) -> dict:
    records = persisted_predictions(store)
    complete = len(records) == 1 and verify_prediction_artifacts(records[0], project.output_dir)
    figures = records[0].get("figures", []) if records else []
    needed = 4 if planned_spec(prediction_plan(store)).task == "binary" else 3
    return {
        "scope": "prediction_validation",
        "minimum_publication_bundle_met": complete and len(figures) == needed,
        "total_figures": len(figures),
        "analytical_figures": len(figures),
        "required_analytical_figures": needed,
        "required_descriptive_figures": 0,
        "descriptive_figures": 0,
        "table_one_required": False,
        "figure_files": [f["path"] for f in figures],
        "missing_components": []
        if complete and len(figures) == needed
        else ["prediction receipt, task-specific figures and validation predictions"],
    }
