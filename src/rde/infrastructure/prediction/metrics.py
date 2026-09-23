"""Held-out metrics and conditional (fixed-model) bootstrap intervals."""

from __future__ import annotations

import hashlib
import math

import numpy as np
from sklearn import metrics

from .contract import PredictionSpec


def finite(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def score_metrics(y, prediction, spec: PredictionSpec) -> dict:
    y, prediction = np.asarray(y, dtype=float), np.asarray(prediction, dtype=float)
    if not np.isfinite(y).all() or not np.isfinite(prediction).all():
        raise ValueError("Nonfinite observations or predictions cannot be scored.")
    if spec.task == "regression":
        return {
            "mae": finite(metrics.mean_absolute_error(y, prediction)),
            "rmse": finite(metrics.root_mean_squared_error(y, prediction)),
            "r2": finite(metrics.r2_score(y, prediction, force_finite=False))
            if len(y) > 1 and np.var(y) > 0
            else None,
        }
    both = len(np.unique(y)) == 2
    decisions = prediction >= spec.threshold
    tn, fp, fn, tp = metrics.confusion_matrix(y, decisions, labels=[0, 1]).ravel()
    return {
        "auroc": finite(metrics.roc_auc_score(y, prediction)) if both else None,
        "average_precision": finite(metrics.average_precision_score(y, prediction))
        if both
        else None,
        "brier": finite(metrics.brier_score_loss(y, prediction, pos_label=1)),
        "log_loss": finite(metrics.log_loss(y, prediction, labels=[0, 1])),
        "sensitivity": ratio(tp, tp + fn),
        "specificity": ratio(tn, tn + fp),
        "ppv": ratio(tp, tp + fp),
        "npv": ratio(tn, tn + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "accuracy": ratio(tp + tn, len(y)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def calibration_bins(y, prediction) -> list[dict]:
    y, prediction = np.asarray(y), np.asarray(prediction)
    bins = []
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        selected = (prediction >= low) & (
            (prediction <= high) if index == 9 else (prediction < high)
        )
        if selected.any():
            bins.append(
                {
                    "lower": low,
                    "upper": high,
                    "n": int(selected.sum()),
                    "mean_prediction": float(prediction[selected].mean()),
                    "observed_fraction": float(y[selected].mean()),
                }
            )
    return bins


def bootstrap_intervals(y, prediction, groups, spec: PredictionSpec, check_budget) -> dict:
    """Sample observations or complete subject clusters; never refit or select models."""
    y, prediction = np.asarray(y), np.asarray(prediction)
    point = score_metrics(y, prediction, spec)
    values = {key: [] for key in point if key not in {"tn", "fp", "fn", "tp"}}
    units = [np.array([i]) for i in range(len(y))]
    if groups is not None:
        lookup = {}
        for i, group in enumerate(groups):
            lookup.setdefault(group, []).append(i)
        units = [np.asarray(rows) for rows in lookup.values()]
    rng = np.random.default_rng((spec.seed + 1) % 2**32)
    draws = hashlib.sha256()
    for _ in range(spec.bootstrap_samples):
        check_budget()
        selected = rng.integers(0, len(units), size=len(units))
        draws.update(selected.astype("<i8").tobytes())
        positions = np.concatenate([units[i] for i in selected])
        scores = score_metrics(y[positions], prediction[positions], spec)
        for key in values:
            if scores[key] is not None:
                values[key].append(scores[key])
    tail = (1 - spec.confidence_level) / 2
    return {
        "method": "percentile bootstrap; fixed selected model; no retraining",
        "unit": "subject_cluster" if groups is not None else "observation",
        "units": len(units),
        "replicates_requested": spec.bootstrap_samples,
        "confidence_level": spec.confidence_level,
        "rng": "numpy.default_rng/PCG64",
        "seed": (spec.seed + 1) % 2**32,
        "draws_sha256": draws.hexdigest(),
        "intervals": {
            key: {
                "estimate": point[key],
                "lower": float(np.quantile(sample, tail)) if len(sample) >= 20 else None,
                "upper": float(np.quantile(sample, 1 - tail)) if len(sample) >= 20 else None,
                "estimable_replicates": len(sample),
                "nonestimable_replicates": spec.bootstrap_samples - len(sample),
            }
            for key, sample in values.items()
        },
        "limitations": "Conditional on this fitted model and validation sample. At least 20 estimable replicates are needed to display an interval; small bootstrap budgets give unstable bounds. Temporal drift and external transportability are not quantified.",
    }
