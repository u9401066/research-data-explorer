from __future__ import annotations

# mypy: disable-error-code=import-untyped

from typing import Any

import pandas as pd

from rde.infrastructure.adapters.analysis_delegator import AnalysisDelegator
from rde.infrastructure.adapters.automl_gateway import (
    AutomlGateway,
    _prepare_direct_analysis_config,
)
from rde.infrastructure.adapters.scipy_engine import ScipyStatisticalEngine


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payloads = list(payloads or [])

    def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        self.calls.append({"path": path, "json": json or {}, "headers": headers or {}})
        payload = self._payloads.pop(0) if self._payloads else {"path": path, "ok": True}
        return _FakeResponse(payload)

    def close(self) -> None:
        return None


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
        "user_id": "rde-agent",
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
    assert payload["user_id"] == "rde-agent"


def test_automl_gateway_routes_propensity_to_submit_endpoint() -> None:
    gateway = AutomlGateway()
    fake_stats = _FakeClient(
        [
            {
                "job_id": "prop-1",
                "job_type": "propensity_full",
                "status": "pending",
                "message": "submitted",
            }
        ]
    )
    gateway._stats = fake_stats

    try:
        df = pd.DataFrame(
            {
                "treatment": [1, 0, 1, 0],
                "outcome": [1, 0, 1, 0],
                "age": [60, 55, 62, 57],
                "bmi": [27.1, 24.8, 29.0, 22.5],
            }
        )
        result = gateway.analyze_df(
            df,
            "propensity_score",
            {
                "group_var": "treatment",
                "target": "outcome",
                "covariates": ["age", "bmi"],
                "user_id": "user-1",
            },
        )
    finally:
        gateway.close()

    assert result["job_id"] == "prop-1"
    assert fake_stats.calls[0]["path"] == "/propensity/full/submit"
    assert fake_stats.calls[0]["json"]["user_id"] == "user-1"
    assert fake_stats.calls[0]["json"]["treatment_column"] == "treatment"
    assert fake_stats.calls[0]["json"]["outcome_column"] == "outcome"
    assert fake_stats.calls[0]["json"]["covariates"] == ["age", "bmi"]
    assert "treatment,outcome,age,bmi" in fake_stats.calls[0]["json"]["csv_content"]


def test_automl_gateway_routes_survival_to_submit_endpoint() -> None:
    gateway = AutomlGateway()
    fake_stats = _FakeClient(
        [{"job_id": "surv-1", "job_type": "cox", "status": "pending", "message": "submitted"}]
    )
    gateway._stats = fake_stats

    try:
        df = pd.DataFrame(
            {
                "time": [5, 8, 3, 10],
                "event": [1, 0, 1, 0],
                "age": [64, 59, 67, 55],
                "bmi": [27.1, 24.8, 29.0, 22.5],
            }
        )
        result = gateway.analyze_df(
            df,
            "cox_regression",
            {
                "time_variable": "time",
                "target": "event",
                "covariates": ["age", "bmi"],
                "user_id": "user-2",
            },
        )
    finally:
        gateway.close()

    assert result["job_id"] == "surv-1"
    assert fake_stats.calls[0]["path"] == "/survival/cox/submit"
    assert fake_stats.calls[0]["json"]["user_id"] == "user-2"
    assert fake_stats.calls[0]["json"]["time_column"] == "time"
    assert fake_stats.calls[0]["json"]["event_column"] == "event"
    assert fake_stats.calls[0]["json"]["covariates"] == ["age", "bmi"]


def test_automl_gateway_routes_roc_to_submit_endpoint() -> None:
    gateway = AutomlGateway()
    fake_stats = _FakeClient(
        [
            {
                "job_id": "roc-1",
                "job_type": "roc_compute",
                "status": "pending",
                "message": "submitted",
            }
        ]
    )
    gateway._stats = fake_stats

    try:
        df = pd.DataFrame(
            {
                "outcome": [1, 0, 1, 0],
                "score": [0.91, 0.20, 0.82, 0.11],
            }
        )
        result = gateway.analyze_df(
            df,
            "roc_auc",
            {
                "target": "outcome",
                "score_variable": "score",
                "user_id": "user-3",
            },
        )
    finally:
        gateway.close()

    assert result["job_id"] == "roc-1"
    assert fake_stats.calls[0]["path"] == "/roc/compute/submit"
    assert fake_stats.calls[0]["json"]["user_id"] == "user-3"
    assert fake_stats.calls[0]["json"]["true_column"] == "outcome"
    assert fake_stats.calls[0]["json"]["score_column"] == "score"


def test_automl_gateway_uploads_dataset_and_infers_problem_type() -> None:
    gateway = AutomlGateway()
    fake_automl = _FakeClient(
        [
            {"dataset_id": "dataset-123", "name": "rde_data"},
            {
                "job_id": "automl-1",
                "job_type": "automl",
                "status": "pending",
                "progress": 0.0,
                "status_message": "Queued for processing",
                "created_at": "2026-03-28T12:00:00Z",
            },
        ]
    )
    gateway._automl = fake_automl

    try:
        df = pd.DataFrame(
            {
                "target": ["setosa", "versicolor", "virginica", "setosa"],
                "sepal_length": [5.1, 6.2, 6.5, 5.0],
            }
        )
        result = gateway.analyze_df(
            df,
            "automl",
            {
                "target": "target",
                "user_id": "user-4",
            },
        )
    finally:
        gateway.close()

    assert result["job_id"] == "automl-1"
    assert fake_automl.calls[0]["path"] == "/datasets/upload"
    assert fake_automl.calls[0]["headers"] == {"X-User-Id": "user-4"}
    assert fake_automl.calls[1]["path"] == "/train/automl"
    assert fake_automl.calls[1]["headers"] == {"X-User-Id": "user-4"}
    assert fake_automl.calls[1]["json"]["dataset_id"] == "dataset-123"
    assert fake_automl.calls[1]["json"]["target_column"] == "target"
    assert fake_automl.calls[1]["json"]["problem_type"] == "multiclass"
    assert fake_automl.calls[1]["json"]["time_limit"] == 300
    assert fake_automl.calls[1]["json"]["presets"] == "medium_quality"


def test_delegator_runs_learning_curve_cusum_locally() -> None:
    df = pd.DataFrame(
        {
            "Operator_ID": ["A", "A", "A", "B", "B", "B"],
            "Trial": [1, 2, 3, 1, 2, 3],
            "成功_0不成功_1成功": [1, 0, 1, 0, 1, 1],
        }
    )
    delegator = AnalysisDelegator()

    result = delegator.run_analysis(
        df,
        "learning_curve_cusum",
        {
            "target": "成功_0不成功_1成功",
            "group_var": "Operator_ID",
            "trial_var": "Trial",
        },
    )

    assert result["source"] == "local (ScipyStatisticalEngine)"
    assert result["result"]["analysis_type"] == "learning_curve_cusum"
    assert result["result"]["operator_variable"] == "Operator_ID"
    assert result["result"]["trial_variable"] == "Trial"
    assert result["result"]["operators_analyzed"] == 2
    assert len(result["result"]["operators"]) == 2
