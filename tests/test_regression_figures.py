from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rde.domain.models.project import Project
from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator
from rde.interface.mcp.tools.analysis_tools import _create_regression_effect_figure


def test_logistic_and_linear_intervals_honor_requested_confidence() -> None:
    pytest.importorskip("statsmodels")
    rng = np.random.default_rng(814)
    x = rng.normal(size=160)
    df = pd.DataFrame(
        {
            "x": x,
            "binary": rng.binomial(1, 1 / (1 + np.exp(-x))),
            "continuous": 1.2 * x + rng.normal(size=160),
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False
    for method, target, key in [
        ("logistic_regression", "binary", "odds_ratio_ci"),
        ("multiple_regression", "continuous", "coefficient_ci"),
    ]:
        results = [
            delegator.run_analysis(
                df,
                method,
                {
                    "target": target,
                    "covariates": ["x"],
                    "backend": "statsmodels",
                    "confidence_level": level,
                },
            )["result"]
            for level in [0.90, 0.99]
        ]
        assert results[0]["confidence_level"] == 0.90
        assert results[1]["confidence_level"] == 0.99
        low, high = [r[key]["x"] for r in results]
        assert high[0] < low[0] < low[1] < high[1]
        assert results[0]["coefficients"] == results[1]["coefficients"]


def test_model_figure_uses_coefficients_and_handles_unavailable_intervals(tmp_path: Path) -> None:
    from PIL import Image

    project = Project(id="figures", name="figures", data_dir=tmp_path, output_dir=tmp_path)
    first = _create_regression_effect_figure(
        project=project,
        analysis_type="logistic_regression",
        analysis_result={
            "target": "event",
            "nobs": 160,
            "confidence_level": 0.90,
            "odds_ratios": {"const": 0.3, "exposure": 0.5, "age": 1.03},
            "odds_ratio_ci": {"exposure": [0.3, 0.8], "age": None},
        },
    )
    assert first is not None and first["plot_type"] == "coefficient_plot"
    path = tmp_path / first["path"]
    first_bytes = path.read_bytes()
    with Image.open(path) as rendered:
        assert rendered.width > 600 and rendered.height > 300
    _create_regression_effect_figure(
        project=project,
        analysis_type="logistic_regression",
        analysis_result={
            "target": "event",
            "nobs": 160,
            "confidence_level": 0.90,
            "odds_ratios": {"const": 0.3, "exposure": 2.5, "severity": 1.4},
            "odds_ratio_ci": {"exposure": [1.4, 4.3], "severity": [1.1, 1.8]},
        },
    )
    assert (
        path.read_bytes() != first_bytes
    )  # A changed fitted model must not reuse an outcome-only plot.
