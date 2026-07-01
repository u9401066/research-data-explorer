from __future__ import annotations

# mypy: disable-error-code=import-untyped

import builtins
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


def test_delegator_runs_local_logistic_regression_without_automl() -> None:
    df = pd.DataFrame(
        {
            "outcome": [0, 0, 0, 0, 1, 1, 1, 1],
            "age": [35, 42, 48, 55, 58, 63, 69, 74],
            "severity": [1, 2, 2, 3, 2, 3, 4, 4],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "logistic_regression",
        {"target": "outcome", "covariates": ["age", "severity"]},
    )

    assert result["source"] == "local-lite (statsmodels)"
    assert result["result"]["analysis_type"] == "logistic_regression"
    assert result["result"]["engine"] == "statsmodels.Logit"
    assert result["result"]["nobs"] == 8
    assert "odds_ratios" in result["result"]
    assert "interpretation" in result["result"]


def test_delegator_encodes_categorical_covariates_for_local_logistic_regression() -> None:
    df = pd.DataFrame(
        {
            "outcome": [0, 0, 0, 0, 1, 1, 1, 1, 0, 1],
            "age": [35, 42, 48, 55, 58, 63, 69, 74, 46, 67],
            "sex": ["F", "F", "M", "F", "M", "M", "F", "M", "F", "M"],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "logistic_regression",
        {"target": "outcome", "covariates": ["age", "sex"]},
    )

    payload = result["result"]
    assert result["source"] == "local-lite (statsmodels)"
    assert payload["analysis_type"] == "logistic_regression"
    assert payload["source_covariates"] == ["age", "sex"]
    assert payload["encoded_covariates"]["sex"]
    assert any(name.startswith("sex_") for name in payload["covariates"])
    assert any(name.startswith("sex_") for name in payload["odds_ratios"])


def test_delegator_uses_fast_logit_for_high_cardinality_without_statsmodels(
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "statsmodels" or name.startswith("statsmodels."):
            raise AssertionError(
                "high-cardinality local-lite logistic should not import statsmodels"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    df = pd.DataFrame(
        {
            "outcome": [0, 1] * 40,
            "trial": list(range(80)),
            "operator": [f"op_{index % 20}" for index in range(80)],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "logistic_regression",
        {"target": "outcome", "covariates": ["trial", "operator"]},
    )

    assert result["source"] == "local-lite (numpy)"
    assert result["result"]["engine"] == "local-lite.LogisticRidge"
    assert result["result"]["nobs"] == 80
    assert "operator_op_1" in result["result"]["odds_ratios"]


def test_delegator_auto_prefers_statsmodels_for_moderate_rows_with_inference() -> None:
    """Regression for the ridge-fallback footgun.

    A moderate-sized adjusted model (>200 rows, few covariates) must use the
    inference-grade statsmodels engine — not the silent numpy ridge fallback that
    previously stripped p-values/CIs for any dataset above 200 rows.
    """
    import numpy as np

    rng = np.random.default_rng(42)
    n = 400
    age = rng.normal(60.0, 10.0, n)
    sex = rng.integers(0, 2, n).astype(float)
    logits = -1.5 + 0.03 * (age - 60.0) + 0.6 * sex
    outcome = (rng.random(n) < 1.0 / (1.0 + np.exp(-logits))).astype(int)
    df = pd.DataFrame({"outcome": outcome, "age": age, "sex": sex})

    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "logistic_regression",
        {"target": "outcome", "covariates": ["age", "sex"]},
    )

    payload = result["result"]
    assert result["source"] == "local-lite (statsmodels)"
    assert payload["engine"] == "statsmodels.Logit"
    assert payload["regularized_fallback"] is False
    # #1: proper inference is restored — real p-values (not None).
    assert all(value is not None for value in payload["p_values"].values())
    # #2: odds-ratio 95% CI is now emitted for the statsmodels path.
    assert "odds_ratio_ci" in payload
    age_ci = payload["odds_ratio_ci"]["age"]
    assert age_ci is not None
    lower, upper = age_ci
    assert lower < upper


def test_delegator_uses_fast_linear_model_for_high_cardinality_without_statsmodels(
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "statsmodels" or name.startswith("statsmodels."):
            raise AssertionError(
                "high-cardinality local-lite regression should not import statsmodels"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    df = pd.DataFrame(
        {
            "duration": [float(index % 17 + index * 0.2) for index in range(80)],
            "trial": list(range(80)),
            "operator": [f"op_{index % 20}" for index in range(80)],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "multiple_regression",
        {"target": "duration", "covariates": ["trial", "operator"]},
    )

    assert result["source"] == "local-lite (numpy)"
    assert result["result"]["engine"] == "local-lite.LinearRidge"
    assert result["result"]["nobs"] == 80
    assert "operator_op_1" in result["result"]["coefficients"]


def test_delegator_runs_local_roc_auc_without_automl() -> None:
    df = pd.DataFrame(
        {
            "outcome": [0, 0, 1, 1, 0, 1],
            "score": [0.1, 0.3, 0.8, 0.9, 0.2, 0.7],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "roc_auc",
        {"target": "outcome", "score_variable": "score"},
    )

    assert result["source"] == "local-lite (scipy)"
    assert result["result"]["analysis_type"] == "roc_auc"
    assert result["result"]["auc"] == 1.0
    assert "interpretation" in result["result"]


def test_delegator_uses_logistic_probability_when_roc_score_is_missing() -> None:
    df = pd.DataFrame(
        {
            "outcome": [0, 0, 0, 0, 1, 1, 1, 1, 0, 1],
            "age": [45, 52, 49, 58, 61, 66, 72, 69, 54, 63],
            "severity": [1, 2, 2, 3, 3, 4, 5, 4, 2, 3],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "roc_auc",
        {"target": "outcome", "covariates": ["age", "severity"]},
    )

    assert result["source"] == "local-lite (scipy)"
    assert result["result"]["analysis_type"] == "roc_auc"
    assert result["result"]["score_variable"] == "predicted_probability"
    assert result["result"]["score_source"] == "local logistic predicted probability"
    assert 0.5 <= result["result"]["auc"] <= 1.0


def test_delegator_runs_local_power_analysis_without_automl() -> None:
    df = pd.DataFrame({"placeholder": [1]})
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "power_analysis_advanced",
        {"test_type": "ttest", "effect_size": 0.5, "nobs1": 64, "alpha": 0.05},
    )

    assert result["source"] == "local-lite (statsmodels)"
    assert result["result"]["analysis_type"] == "power_analysis"
    assert result["result"]["test_type"] == "ttest"
    assert 0 < result["result"]["power"] < 1


def test_delegator_propensity_score_local_lite_returns_score_diagnostics() -> None:
    df = pd.DataFrame(
        {
            "treatment": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "age": [50, 51, 49, 54, 60, 59, 58, 62, 47, 52, 55, 56],
            "bmi": [25.0, 27.0, 24.0, 30.0, 31.0, 29.0, 28.0, 32.0, 23.0, 26.0, 27.0, 28.0],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "propensity_score",
        {"group_var": "treatment", "covariates": ["age", "bmi"]},
    )

    ps_result = result["result"]
    assert result["source"] == "local-lite (statsmodels)"
    assert ps_result["analysis_type"] == "propensity_score"
    assert ps_result["propensity_score_summary"]["count"] == 12
    assert (
        0
        <= ps_result["propensity_score_summary"]["min"]
        <= ps_result["propensity_score_summary"]["max"]
        <= 1
    )
    assert ps_result["propensity_scores_sample"][0]["propensity_score"] >= 0
    assert len(ps_result["propensity_scores"]) == 12
    assert ps_result["propensity_scores_truncated"] is False
    assert ps_result["common_support"]["treated_min"] <= ps_result["common_support"]["treated_max"]
    assert "age" in ps_result["balance_diagnostics"]
    assert "standardized_mean_difference" in ps_result["balance_diagnostics"]["age"]
    assert "age" in ps_result["weighted_balance_diagnostics"]
    assert "age" in ps_result["matched_balance_diagnostics"]
    assert ps_result["iptw_weight_summary"]["count"] == 12
    assert ps_result["matching_summary"]["matched_pairs"] > 0
    assert ps_result["matched_pairs"]


def test_delegator_propensity_score_encodes_categorical_covariates() -> None:
    df = pd.DataFrame(
        {
            "treatment": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "age": [50, 51, 49, 54, 60, 59, 58, 62, 47, 52, 55, 56],
            "sex": ["F", "M", "F", "M", "F", "M", "F", "M", "F", "M", "F", "M"],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "propensity_score",
        {"group_var": "treatment", "covariates": ["age", "sex"]},
    )

    ps_result = result["result"]
    assert result["source"] == "local-lite (statsmodels)"
    assert ps_result["covariates"] == ["age", "sex"]
    assert "sex" in ps_result["encoded_covariate_map"]
    assert any(name.startswith("sex_") for name in ps_result["encoded_covariates"])
    assert any(name.startswith("sex_") for name in ps_result["balance_diagnostics"])


def test_delegator_kaplan_meier_local_lite_returns_stratified_summary() -> None:
    df = pd.DataFrame(
        {
            "time": [3, 5, 8, 10, 4, 6, 9, 12],
            "event": [1, 1, 0, 1, 1, 0, 1, 0],
            "treatment": [
                "control",
                "control",
                "control",
                "control",
                "treated",
                "treated",
                "treated",
                "treated",
            ],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "kaplan_meier",
        {"time_variable": "time", "target": "event", "group_variable": "treatment"},
    )

    km_result = result["result"]
    assert result["source"] == "local-lite (kaplan-meier)"
    assert km_result["analysis_type"] == "kaplan_meier"
    assert km_result["median_survival"] == 9.0
    assert km_result["group_variable"] == "treatment"
    assert set(km_result["strata"]) == {"control", "treated"}
    assert km_result["strata"]["control"]["nobs"] == 4
    assert km_result["strata"]["treated"]["events"] == 2
    assert "median_survival" in km_result["strata"]["treated"]


def test_delegator_survival_analysis_with_covariates_uses_local_cox() -> None:
    df = pd.DataFrame(
        {
            "time": [5, 8, 12, 4, 10, 14, 6, 9, 13, 7, 11, 15],
            "event": [1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "age": [60, 55, 58, 70, 65, 62, 59, 68, 64, 61, 66, 63],
        }
    )
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    result = delegator.run_analysis(
        df,
        "survival_analysis",
        {"time_variable": "time", "target": "event", "covariates": ["age"]},
    )

    assert result["source"] == "local-lite (statsmodels)"
    assert result["result"]["analysis_type"] == "cox_regression"
    assert result["result"]["nobs"] == 12
    assert "age" in result["result"]["hazard_ratios"]


def test_delegator_capabilities_distinguish_local_lite_from_automl_required() -> None:
    delegator = AnalysisDelegator()
    delegator._automl_available = False

    capabilities = delegator.get_capabilities()

    assert capabilities["logistic_regression"] == "local-lite"
    assert capabilities["roc_auc"] == "local-lite"
    assert capabilities["automl"] == "automl required"


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
