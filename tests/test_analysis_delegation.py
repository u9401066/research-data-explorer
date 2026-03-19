from __future__ import annotations

import pandas as pd

from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator
from rde.infrastructure.adapters.automl_gateway import (
    AutomlGateway,
    _prepare_direct_analysis_config,
)
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine


def test_scipy_engine_accepts_normalized_test_aliases() -> None:
    df = pd.DataFrame(
        {
            "value": [1.0, 2.0, 3.5, 4.5, 5.0, 6.0],
            "group": ["A", "A", "A", "B", "B", "B"],
        }
    )

    result = ScipyStatisticalEngine().run_test(df, "mann_whitney", ["value", "group"])

    assert result["test_name"] == "Mann-Whitney U"
    assert "p_value" in result


def test_delegator_returns_descriptive_error_when_local_fallback_cannot_run() -> None:
    df = pd.DataFrame({"outcome": [0, 1, 0, 1], "age": [60, 55, 70, 50]})
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "logistic_regression",
        {"variables": ["outcome", "age"], "target": "outcome"},
    )

    assert result["source"] == "local (ScipyStatisticalEngine)"
    assert "does not support 'logistic_regression'" in result["result"]["error"]
    assert "docker compose up -d" in result["result"]["suggestion"]


def test_automl_gateway_routes_logistic_regression_with_analysis_type(monkeypatch) -> None:
    gateway = AutomlGateway()
    calls: dict[str, object] = {}

    def fake_direct(csv_content: str, config: dict[str, object]) -> dict[str, object]:
        calls["csv_content"] = csv_content
        calls["config"] = config
        return {"ok": True}

    monkeypatch.setattr(gateway, "direct_analyze", fake_direct)

    try:
        df = pd.DataFrame({"y": [0, 1], "x": [1.2, 3.4]})
        result = gateway.analyze_df(df, "logistic_regression", {"target": "y", "covariates": ["x"]})
    finally:
        gateway.close()

    assert result == {"ok": True}
    assert calls["config"] == {
        "analysis_type": "logistic_regression",
        "target": "y",
        "target_column": "y",
        "covariates": ["x"],
    }
    assert "y,x" in str(calls["csv_content"])


def test_automl_gateway_maps_power_analysis_advanced_to_power_endpoint(monkeypatch) -> None:
    gateway = AutomlGateway()
    calls: dict[str, object] = {}

    def fake_power(csv_content: str, config: dict[str, object]) -> dict[str, object]:
        calls["csv_content"] = csv_content
        calls["config"] = config
        return {"power": 0.8}

    monkeypatch.setattr(gateway, "run_power", fake_power)

    try:
        df = pd.DataFrame({"effect_size": [0.5], "alpha": [0.05]})
        result = gateway.analyze_df(
            df, "power_analysis_advanced", {"test_type": "ttest", "effect_size": 0.5}
        )
    finally:
        gateway.close()

    assert result == {"power": 0.8}
    assert calls["config"] == {"test_type": "ttest", "effect_size": 0.5}


def test_prepare_direct_analysis_config_maps_target_column() -> None:
    payload = _prepare_direct_analysis_config({"target": "outcome", "covariates": ["age"]}, "glm")

    assert payload["analysis_type"] == "glm"
    assert payload["target"] == "outcome"
    assert payload["target_column"] == "outcome"
