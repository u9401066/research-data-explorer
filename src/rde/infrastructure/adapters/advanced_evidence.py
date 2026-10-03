"""Save local model evidence at execution time; never fit a model when rendering it."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np


def finite_evidence(value: Any) -> dict:
    """Use strict JSON, retaining the location and kind of every nonfinite value."""
    unavailable = []

    def clean(item, path):
        if isinstance(item, np.generic):
            item = item.item()
        if isinstance(item, dict):
            return {str(k): clean(v, [*path, str(k)]) for k, v in item.items()}
        if isinstance(item, (list, tuple, np.ndarray)):
            return [clean(v, [*path, i]) for i, v in enumerate(item)]
        if isinstance(item, float) and not math.isfinite(item):
            unavailable.append({"path": path, "value": str(item)})
            return None
        return item

    result = clean(value, [])
    result["nonfinite_values"] = unavailable
    result["sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    return result


def model_evidence(fit: dict, *, confidence_level: float) -> dict:
    """Capture all fitted rows, coding, design, diagnostics and uncertainty, not a preview."""
    x = fit["x_raw"]
    y = fit["y"]
    fitted = fit.get("fitted")
    lite = bool(fit.get("lite"))
    predictions = fit["predictions"]
    params = fit["params"] if lite else fitted.params
    names = [str(name) for name in params.index]
    covariance = None
    intervals = None
    inference_error = None
    if not lite:
        try:
            covariance = fitted.cov_params().to_numpy().tolist()
            intervals = fitted.conf_int(alpha=1 - confidence_level).to_numpy().tolist()
        except (ValueError, AttributeError, np.linalg.LinAlgError) as exc:
            inference_error = str(exc)
    design = np.column_stack([np.ones(len(x)), x.to_numpy(dtype=float)])
    if lite:
        scaling = fit["scaling"]
        design[:, 1:] = (design[:, 1:] - np.array(scaling["means"])) / np.array(
            scaling["standard_deviations"]
        )
    else:
        scaling = None
    rows = [
        {
            "row_position": int(index),
            "outcome": float(y.loc[index]),
            "design": design[pos].tolist(),
            "fitted": float(predictions.loc[index]),
            "response_residual": float(y.loc[index] - predictions.loc[index]),
        }
        for pos, index in enumerate(x.index)
    ]
    mle = getattr(fitted, "mle_retvals", {}) if fitted is not None else {}
    return finite_evidence(
        {
            "schema": "advanced-model-evidence-v1",
            "row_position_base": 0,
            "case_set": x.attrs.get("case_set", {}),
            "predictor_coding": x.attrs.get("predictor_coding", []),
            "outcome_coding": y.attrs.get("coding"),
            "design_columns": names,
            "scaling": scaling,
            "rows": rows,
            "parameters": [float(params[name]) for name in params.index],
            "covariance": covariance,
            "coefficient_intervals": intervals,
            "confidence_level": confidence_level,
            "inference_error": inference_error,
            "inference_scope": (
                "regularized fit; conventional unpenalized inference is not established"
                if fit.get("regularized")
                else "unadjusted model-based intervals; not validated prediction"
            ),
            "regularized": bool(fit.get("regularized")),
            "algorithm": fit.get("algorithm"),
            "design_rank": int(np.linalg.matrix_rank(design)),
            "design_columns_count": len(names),
            "df_resid": float(fitted.df_resid) if fitted is not None else None,
            "converged": bool(mle["converged"]) if "converged" in mle else None,
            "iterations": mle.get("iterations"),
            "warnings": fit.get("warnings", []),
        }
    )


def exp_with_status(value: float) -> tuple[float | None, str]:
    """Do not cap wide log intervals or disguise overflow as a finite bound."""
    value = float(value)
    if not math.isfinite(value):
        return None, "nonfinite_log_value"
    try:
        number = math.exp(value)
    except OverflowError:
        return None, "overflow"
    if number == 0:
        return 0.0, "underflow"
    return number, "finite"


def display_evidence(value: Any) -> Any:
    """A readable report points to complete saved rows instead of embedding them."""
    row_keys = {
        "rows",
        "propensity_scores",
        "propensity_scores_sample",
        "matched_pairs",
        "included_row_positions",
    }
    if isinstance(value, dict):
        return {
            key: {"saved_count": len(item), "location": "complete numerical JSON artifact"}
            if key in row_keys and isinstance(item, list)
            else display_evidence(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [display_evidence(item) for item in value]
    return value
