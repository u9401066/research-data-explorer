"""Prediction-specific tables and figures; no in-sample inference claims."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.metrics import precision_recall_curve, roc_curve


def number(value):
    return f"{value:.5g}" if isinstance(value, (float, int)) else "not estimable"


def markdown(result: dict) -> str:
    spec, split, selection, validation = (
        result[key] for key in ["spec", "outer_split", "selection", "validation"]
    )
    lines = [
        "## Prediction validation",
        "",
        "Internal held-out validation; this is not external or clinical deployment validation.",
        "",
        f"- Target: `{spec['target']}` ({spec['task']}); encoding: `{result['target_encoding']}`.",
        f"- Prediction time: {spec['prediction_time_definition']}",
        f"- Researcher attests predictor availability at prediction time: {spec['features_available_at_prediction']}.",
        f"- Prespecified predictors: {', '.join(spec['predictors'])}. Categorical: {', '.join(spec['categorical_predictors']) or 'none'}.",
        f"- Source / eligible / training / held-out observations: {result['n_source']} / {result['n_eligible']} / {split['n_train']} / {split['n_validation']}.",
        f"- Split: {spec['split']}; seed={spec['seed']}; requested holdout fraction={spec['test_fraction']} (group split is a fraction of groups; temporal split uses the cutoff).",
        f"- Subject key: {spec['subject_variable'] or 'none (independent observations assumed)'}; time: {spec['time_variable'] or 'not used'}; cutoff: {spec['cutoff'] or 'not used'}.",
        f"- Purged training observations for subjects crossing the holdout boundary: {len(split['purged_train_positions'])}.",
        f"- Exclusion counts (reasons can overlap): { {key: len(rows) for key, rows in result['exclusions'].items()} }.",
        f"- Invalid nonmissing numeric predictor values converted to missing: {result['invalid_predictor_values']}.",
        "- Missing predictors: training median / category mode; numeric missing indicators; scaling and category vocabulary fitted within each training fold. Outcomes and split keys are never imputed.",
        f"- Selection: {selection['criterion']} ({selection['direction']}), {spec['cv_folds']} training CV folds, {selection['aggregation']}. Tie break: {selection['tie_break']}.",
        "- Only the selected model was evaluated on the outer holdout; candidates never use holdout performance for selection.",
        "",
        "### Training-only candidate comparison",
        "",
        "| Candidate | Status | CV score | Selected | Failure |",
        "|---|---|---:|---|---|",
    ]
    for candidate in result["candidates"]:
        lines.append(
            f"| {candidate['name']} | {candidate['status']} | {number(candidate.get('cv_score'))} | {'yes' if candidate['name'] == selection['selected'] else 'no'} | {candidate.get('error', '').replace('|', '/')} |"
        )
    lines += [
        "",
        "### Held-out performance",
        "",
        f"Selected model: **{selection['selected']}**. Validation n={validation['n']}. Classification threshold={validation['threshold'] if spec['task'] == 'binary' else 'not applicable'}.",
        "",
        "| Metric | Estimate | Lower | Upper | Estimable bootstrap replicates |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, value in validation["metrics"].items():
        ci = validation["uncertainty"]["intervals"].get(key, {})
        lines.append(
            f"| {key} | {number(value)} | {number(ci.get('lower'))} | {number(ci.get('upper'))} | {ci.get('estimable_replicates', 'not bootstrapped')} |"
        )
    uncertainty = validation["uncertainty"]
    lines += [
        "",
        f"CI: {uncertainty['confidence_level']:.1%}, {uncertainty['method']}; unit={uncertainty['unit']}; units={uncertainty['units']}; requested replicates={uncertainty['replicates_requested']}.",
        uncertainty["limitations"],
        "",
        "Training-derived constant baseline (for context, not a competing holdout-selected model): "
        + str(validation["baseline"]),
        "",
        "### Interpretation and limitations",
        "",
        "Discrimination, calibration and threshold-specific performance answer different questions. Compare the selected model with the constant baseline and inspect the calibration/error plots; none of these estimates establishes clinical benefit. An unavailable estimate is retained as missing, never replaced with a favorable value.",
        "For binary outcomes, average precision summarizes precision across recall increments and is not a trapezoidal PR area. Calibration bins show observed and predicted proportions with bin counts; sparse bins are unstable.",
        "For continuous outcomes, RMSE emphasizes larger errors and MAE gives absolute-error magnitude in outcome units. R² can be negative and is undefined for a constant validation outcome.",
        *[f"- {item}" for item in result["limitations"]],
        "- After inspecting this holdout, further model revisions require new validation data or explicitly exploratory labeling. Reusing it does not create an unseen validation set.",
        "- Next review: verify predictor timing, patient sampling, outcome ascertainment, event/sample-size adequacy, intended-use thresholds, subgroup performance and independent external validation.",
        "",
        "### Reproducibility",
        "",
        f"- Receipt SHA256: `{result['receipt_sha256']}`",
        f"- Dataframe SHA256: `{result['dataframe_sha256']}`",
        f"- Specification SHA256: `{result['spec_sha256']}`",
        f"- Fitted model SHA256: `{result['final_fit']['fit_sha256']}`",
        f"- Versions: `{result['versions']}`; Python {result['python']}.",
        "- Full receipt contains source row positions (zero-based), every training fold, fitted transformations, candidate predictions, fixed hyperparameters, validation predictions, exclusions and bootstrap sampling provenance.",
    ]
    return "\n".join(lines) + "\n"


def figures(result: dict, directory: Path, prefix: str) -> list[dict]:
    import matplotlib.pyplot as plt

    directory.mkdir(parents=True, exist_ok=True)
    records = []

    def save(fig, kind, caption):
        path = directory / f"{prefix}_{kind}.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        records.append({"path": str(path), "plot_type": f"prediction_{kind}", "caption": caption})

    rows = result["validation"]["predictions"]
    y, prediction = (
        np.asarray([r["observed"] for r in rows]),
        np.asarray([r["prediction"] for r in rows]),
    )
    n = len(y)
    spec, scores = result["spec"], result["validation"]["metrics"]
    candidates = [c for c in result["candidates"] if c["status"] == "completed"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    criterion = result["selection"]["criterion"]
    ax.bar([c["name"] for c in candidates], [c["cv_score"] for c in candidates], color="#227c7a")
    ax.set(ylabel=f"Mean CV {criterion}", title="Model selection: training folds only")
    save(
        fig,
        "cv",
        f"Training-only mean {criterion}; {len(result['cv_splits'])} folds. Holdout performance is not used in this comparison.",
    )
    if spec["task"] == "binary":
        fig, ax = plt.subplots(figsize=(6, 5))
        if len(np.unique(y)) == 2:
            fpr, tpr, _ = roc_curve(y, prediction)
            ax.plot(fpr, tpr, color="#227c7a", label=f"AUROC={number(scores['auroc'])}")
            ax.legend(loc="lower right")
        else:
            ax.text(0.5, 0.5, "ROC not estimable: one outcome class", ha="center", wrap=True)
        ax.plot([0, 1], [0, 1], "--", color="gray")
        ax.set(
            xlabel="False positive rate",
            ylabel="Sensitivity",
            title=f"Held-out ROC (n={n})",
            xlim=(0, 1),
            ylim=(0, 1),
        )
        save(
            fig,
            "roc",
            f"Held-out ROC, n={n}, AUROC={number(scores['auroc'])}; discrimination alone does not establish calibration or clinical benefit.",
        )
        fig, ax = plt.subplots(figsize=(6, 5))
        if len(np.unique(y)) == 2:
            precision, recall, _ = precision_recall_curve(y, prediction)
            ax.step(
                recall,
                precision,
                where="post",
                color="#227c7a",
                label=f"AP={number(scores['average_precision'])}",
            )
            ax.legend()
        else:
            ax.text(0.5, 0.5, "PR not estimable: one outcome class", ha="center", wrap=True)
        ax.axhline(y.mean(), linestyle="--", color="gray")
        ax.set(
            xlabel="Recall",
            ylabel="Precision",
            title=f"Held-out precision–recall (n={n})",
            xlim=(0, 1),
            ylim=(0, 1.02),
        )
        save(
            fig,
            "pr",
            f"Held-out precision–recall, n={n}; average precision={number(scores['average_precision'])}; dashed line is held-out outcome prevalence.",
        )
        fig, ax = plt.subplots(figsize=(6, 5))
        bins = result["validation"]["calibration_bins"]
        ax.plot([0, 1], [0, 1], "--", color="gray")
        ax.plot(
            [b["mean_prediction"] for b in bins],
            [b["observed_fraction"] for b in bins],
            "o-",
            color="#227c7a",
        )
        for b in bins:
            ax.annotate(
                f"n={b['n']}",
                (b["mean_prediction"], b["observed_fraction"]),
                xytext=(3, 6),
                textcoords="offset points",
                fontsize=8,
            )
        ax.set(
            xlabel="Mean predicted probability",
            ylabel="Observed fraction",
            title=f"Held-out calibration (n={n})",
            xlim=(-0.03, 1.03),
            ylim=(-0.03, 1.1),
        )
        save(
            fig,
            "calibration",
            f"Held-out calibration in fixed-width probability bins, n={n}; counts label each nonempty bin. Sparse bins are unstable; no curve was fitted on the holdout.",
        )
    else:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.scatter(prediction, y, alpha=0.5, s=16, color="#227c7a", rasterized=True)
        low, high = min(y.min(), prediction.min()), max(y.max(), prediction.max())
        ax.plot([low, high], [low, high], "--", color="gray")
        ax.set(
            xlabel="Predicted outcome",
            ylabel="Observed outcome",
            title=f"Held-out predictions (n={n})",
        )
        save(
            fig,
            "observed",
            f"Held-out observed versus predicted, n={n}; RMSE={number(scores['rmse'])}, MAE={number(scores['mae'])}. Dashed line indicates perfect agreement.",
        )
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.scatter(prediction, y - prediction, alpha=0.5, s=16, color="#227c7a", rasterized=True)
        ax.axhline(0, linestyle="--", color="gray")
        ax.set(
            xlabel="Predicted outcome",
            ylabel="Observed − predicted",
            title=f"Held-out residuals (n={n})",
        )
        save(
            fig,
            "residual",
            f"Held-out residuals, n={n}; inspect nonlinearity, outliers and nonconstant error spread. This plot does not refit the model.",
        )
    return records
