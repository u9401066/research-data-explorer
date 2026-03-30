"""AutomlGateway — Adapter implementing AutomlGatewayPort.

Anti-Corruption Layer (ACL) for the automl-stat-mcp submodule.
Translates between RDE's domain model and automl-stat-mcp's REST APIs.

Services:
  - stats-service (port 8003): Statistical analysis, propensity, survival, ROC, power
  - automl-service (port 8001): AutoML training & dataset management
"""

from __future__ import annotations

import io
import logging
from typing import Any

import httpx
import pandas as pd

from rde.domain.ports import AutomlGatewayPort

logger = logging.getLogger(__name__)

# Default request headers required by automl-stat-mcp
_DEFAULT_HEADERS = {
    "X-User-Id": "rde-agent",
}


def _df_to_csv(df: pd.DataFrame) -> str:
    """Serialize DataFrame to CSV string."""
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _normalize_analysis_type(analysis_type: str) -> str:
    """Normalize analysis type names to the internal routing format."""
    return analysis_type.lower().replace("-", "_").replace(" ", "_")


def _string_or_none(value: Any) -> str | None:
    """Return a stripped string value when present."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str] | None:
    """Normalize a scalar/list payload field into a list of non-empty strings."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else None
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    text = str(value).strip()
    return [text] if text else None


def _first_text_value(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty text value from a config payload."""
    for key in keys:
        value = _string_or_none(payload.get(key))
        if value is not None:
            return value
    return None


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop empty fields while preserving valid falsey values like 0 and False."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict, set)) and not value:
            continue
        cleaned[key] = value
    return cleaned


def _extract_user_id(config: dict[str, Any]) -> str:
    """Resolve the effective vendor user ID."""
    return _string_or_none(config.get("user_id")) or _DEFAULT_HEADERS["X-User-Id"]


def _normalize_propensity_endpoint(endpoint: str) -> str:
    """Map propensity aliases to vendor endpoint names."""
    normalized = _normalize_analysis_type(endpoint)
    alias_map = {
        "estimate": "estimate",
        "match": "match",
        "effect": "effect",
        "balance": "balance",
        "full": "full",
    }
    return alias_map.get(normalized, endpoint)


def _normalize_survival_endpoint(endpoint: str) -> str:
    """Map survival aliases to vendor endpoint names."""
    normalized = _normalize_analysis_type(endpoint)
    alias_map = {
        "kaplan_meier": "kaplan-meier",
        "kaplan-meier": "kaplan-meier",
        "cox_regression": "cox",
        "cox": "cox",
        "compare": "compare",
        "summary": "summary",
    }
    return alias_map.get(normalized, endpoint)


def _normalize_roc_endpoint(endpoint: str) -> str:
    """Map ROC aliases to vendor endpoint names."""
    normalized = _normalize_analysis_type(endpoint)
    alias_map = {
        "compute": "compute",
        "compare": "compare",
        "threshold": "threshold",
        "calibration": "calibration",
        "full_eval": "full-eval",
        "full-eval": "full-eval",
    }
    return alias_map.get(normalized, endpoint)


def _normalize_power_test_type(test_type: str) -> str:
    """Map local aliases to vendor power-analysis route names."""
    normalized = _normalize_analysis_type(test_type)
    alias_map = {
        "t_test": "ttest",
        "ttest": "ttest",
        "proportion": "proportion",
        "proportion_test": "proportion",
        "anova": "anova",
        "chi_square": "chisquare",
        "chi_square_test": "chisquare",
        "chisquare": "chisquare",
        "survival": "survival",
    }
    return alias_map.get(normalized, test_type)


def _prepare_direct_analysis_config(config: dict[str, Any], analysis_type: str) -> dict[str, Any]:
    """Map RDE config into stats-service /direct/analyze contract."""
    payload = dict(config)
    if "target" in payload and "target_column" not in payload:
        payload["target_column"] = payload["target"]
    payload["analysis_type"] = analysis_type
    payload["user_id"] = _extract_user_id(payload)
    return _clean_payload(payload)


def _prepare_propensity_config(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Translate RDE config into vendor propensity request fields."""
    payload = dict(config)
    treatment_column = _first_text_value(
        payload, ("treatment_column", "group_var", "group_variable")
    )
    outcome_column = _first_text_value(
        payload,
        ("outcome_column", "target", "target_column", "target_variable"),
    )
    score_column = _first_text_value(payload, ("score_column",))
    endpoint = _string_or_none(payload.get("endpoint"))
    if endpoint is None:
        endpoint = "full" if outcome_column else ("match" if score_column else "estimate")

    prepared = {
        "user_id": _extract_user_id(payload),
        "treatment_column": treatment_column,
        "outcome_column": outcome_column,
        "covariates": _string_list(payload.get("covariates")),
        "score_column": score_column,
        "method": _string_or_none(payload.get("method")),
        "regularization": payload.get("regularization"),
        "caliper": payload.get("caliper"),
        "caliper_scale": _string_or_none(payload.get("caliper_scale")),
        "replacement": payload.get("replacement"),
        "ratio": payload.get("ratio"),
        "estimand": _string_or_none(payload.get("estimand")),
        "weights_column": _first_text_value(payload, ("weights_column",)),
        "matched_column": _first_text_value(payload, ("matched_column",)),
        "threshold": payload.get("threshold"),
    }
    return _normalize_propensity_endpoint(endpoint), _clean_payload(prepared)


def _prepare_survival_config(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Translate RDE config into vendor survival request fields."""
    payload = dict(config)
    covariates = _string_list(payload.get("covariates"))
    endpoint = _string_or_none(payload.get("endpoint"))
    if endpoint is None:
        endpoint = "cox" if covariates else "kaplan-meier"

    prepared = {
        "user_id": _extract_user_id(payload),
        "time_column": _first_text_value(payload, ("time_column", "time_variable")),
        "event_column": _first_text_value(
            payload,
            ("event_column", "event_variable", "target", "target_column", "target_variable"),
        ),
        "group_column": _first_text_value(payload, ("group_column", "group_var", "group_variable")),
        "covariates": covariates,
        "strata": _string_list(payload.get("strata")),
        "ties": _string_or_none(payload.get("ties")),
        "penalizer": payload.get("penalizer"),
        "confidence_level": payload.get("confidence_level"),
        "time_points": payload.get("time_points"),
        "test": _string_or_none(payload.get("test") or payload.get("method")),
        "generate_visualizations": payload.get("generate_visualizations"),
    }
    return _normalize_survival_endpoint(endpoint), _clean_payload(prepared)


def _prepare_roc_config(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Translate RDE config into vendor ROC request fields."""
    payload = dict(config)
    endpoint = _string_or_none(payload.get("endpoint"))
    score_columns = _string_list(payload.get("score_columns"))
    if score_columns is None and endpoint == "compare":
        score_columns = _string_list(payload.get("covariates"))
    if endpoint is None:
        endpoint = "compare" if score_columns and len(score_columns) > 1 else "compute"
    score_column = _first_text_value(payload, ("score_column", "score_variable"))
    if score_columns is None and endpoint == "compare" and score_column is not None:
        score_columns = [score_column]

    prepared = {
        "user_id": _extract_user_id(payload),
        "true_column": _first_text_value(
            payload,
            ("true_column", "target", "target_column", "target_variable"),
        ),
        "score_column": score_column,
        "score_columns": score_columns,
        "model_names": _string_list(payload.get("model_names")),
        "method": _string_or_none(payload.get("method")),
        "pos_label": payload.get("pos_label"),
        "n_bootstrap": payload.get("n_bootstrap"),
        "confidence_level": payload.get("confidence_level"),
        "threshold": payload.get("threshold"),
        "include_calibration": payload.get("include_calibration"),
        "include_precision_recall": payload.get("include_precision_recall"),
        "generate_visualizations": payload.get("generate_visualizations"),
        "n_bins": payload.get("n_bins"),
        "strategy": _string_or_none(payload.get("strategy")),
    }
    return _normalize_roc_endpoint(endpoint), _clean_payload(prepared)


def _prepare_power_config(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Translate RDE config into vendor power-analysis request fields."""
    payload = dict(config)
    test_type = _normalize_power_test_type(_string_or_none(payload.get("test_type")) or "ttest")
    allowed_fields = {
        "effect_size",
        "mean1",
        "mean2",
        "std",
        "alpha",
        "power",
        "n",
        "ratio",
        "alternative",
        "p1",
        "p2",
        "means",
        "k",
        "contingency_table",
        "df",
        "hazard_ratio",
        "n_events",
        "dropout_rate",
        "accrual_time",
        "followup_time",
    }
    prepared = {key: value for key, value in payload.items() if key in allowed_fields}
    return test_type, _clean_payload(prepared)


def _infer_problem_type(target: pd.Series) -> str:
    """Infer AutoML problem type from the target column."""
    observed = target.dropna()
    if observed.empty:
        return "binary"
    unique_count = int(observed.nunique())
    if pd.api.types.is_numeric_dtype(observed):
        if unique_count <= 2:
            return "binary"
        if pd.api.types.is_integer_dtype(observed) and unique_count <= 20:
            return "multiclass"
        return "regression"
    return "binary" if unique_count <= 2 else "multiclass"


def _prepare_automl_training_config(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Translate RDE config into vendor AutoML upload/train fields."""
    payload = dict(config)
    target_column = _first_text_value(
        payload,
        ("target_column", "target", "target_variable"),
    )
    if target_column is None:
        raise ValueError("AutoML requires target_column or target.")
    if target_column not in df.columns:
        raise ValueError(f"Target column '{target_column}' not found in dataset.")

    prepared = {
        "user_id": _extract_user_id(payload),
        "name": _string_or_none(payload.get("name") or payload.get("project_name")) or "rde_data",
        "description": _string_or_none(payload.get("description")) or "Uploaded via RDE",
        "target_column": target_column,
        "problem_type": _string_or_none(payload.get("problem_type"))
        or _infer_problem_type(df[target_column]),
        "time_limit": payload.get("time_limit", 300),
        "presets": _string_or_none(payload.get("presets")) or "medium_quality",
        "metric": _string_or_none(payload.get("metric")),
    }
    return _clean_payload(prepared)


class AutomlGateway(AutomlGatewayPort):
    """Gateway to automl-stat-mcp Docker services.

    Communicates via HTTP to:
    - stats-service at localhost:8003 (statistical analysis)
    - automl-service at localhost:8001 (AutoML training)
    """

    def __init__(
        self,
        stats_url: str = "http://localhost:8003",
        automl_url: str = "http://localhost:8001",
        timeout: int = 120,
    ) -> None:
        self._stats_url = stats_url
        self._automl_url = automl_url
        self._stats = httpx.Client(
            base_url=stats_url,
            timeout=timeout,
            headers=_DEFAULT_HEADERS,
        )
        self._automl = httpx.Client(
            base_url=automl_url,
            timeout=timeout,
            headers=_DEFAULT_HEADERS,
        )

    # ── Health ──────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if stats-service is running."""
        try:
            r = self._stats.get("/health")
            return r.status_code == 200
        except httpx.ConnectError:
            return False

    def is_automl_available(self) -> bool:
        """Check if automl-service is running."""
        try:
            r = self._automl.get("/health")
            return r.status_code == 200
        except httpx.ConnectError:
            return False

    # ── Direct Analysis (stats-service) ─────────────────────────

    def direct_analyze(
        self,
        csv_content: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /direct/analyze — direct CSV statistical analysis."""
        payload = {
            "csv_content": csv_content,
            **_prepare_direct_analysis_config(
                config, str(config.get("analysis_type", "direct_analyze"))
            ),
        }
        r = self._stats.post("/direct/analyze", json=payload)
        r.raise_for_status()
        return r.json()

    # ── Propensity Score (stats-service) ────────────────────────

    def run_propensity(
        self,
        csv_content: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /propensity/* — propensity score analysis."""
        endpoint, payload = _prepare_propensity_config(config)
        r = self._stats.post(
            f"/propensity/{endpoint}/submit", json={"csv_content": csv_content, **payload}
        )
        r.raise_for_status()
        return r.json()

    # ── Survival Analysis (stats-service) ───────────────────────

    def run_survival(
        self,
        csv_content: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /survival/* — survival analysis."""
        endpoint, payload = _prepare_survival_config(config)
        r = self._stats.post(
            f"/survival/{endpoint}/submit", json={"csv_content": csv_content, **payload}
        )
        r.raise_for_status()
        return r.json()

    # ── ROC/AUC (stats-service) ─────────────────────────────────

    def run_roc(
        self,
        csv_content: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /roc/* — ROC curve analysis."""
        endpoint, payload = _prepare_roc_config(config)
        r = self._stats.post(
            f"/roc/{endpoint}/submit", json={"csv_content": csv_content, **payload}
        )
        r.raise_for_status()
        return r.json()

    # ── Power Analysis (stats-service) ──────────────────────────

    def run_power(
        self,
        csv_content: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /power/* — power analysis for various tests."""
        test_type, payload = _prepare_power_config(config)
        r = self._stats.post(f"/power/{test_type}", json=payload)
        r.raise_for_status()
        return r.json()

    # ── AutoML Training (automl-service) ────────────────────────

    def submit_automl(
        self,
        csv_content: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /train/automl — upload a dataset and submit an AutoML training job."""
        payload = dict(config)
        user_id = _extract_user_id(payload)
        dataset_name = _string_or_none(payload.pop("name", None)) or "rde_data"
        dataset_description = (
            _string_or_none(payload.pop("description", None)) or "Uploaded via RDE"
        )

        # First upload dataset
        upload_r = self._automl.post(
            "/datasets/upload",
            headers={"X-User-Id": user_id},
            json={
                "csv_content": csv_content,
                "name": dataset_name,
                "description": dataset_description,
            },
        )
        upload_r.raise_for_status()
        dataset_id = upload_r.json().get("dataset_id", "")

        # Then submit training
        train_payload = {
            "dataset_id": dataset_id,
            "target_column": payload.pop("target_column"),
            "problem_type": payload.pop("problem_type"),
            "time_limit": payload.pop("time_limit", 300),
            "presets": payload.pop("presets", "medium_quality"),
        }
        metric = payload.pop("metric", None)
        if metric is not None:
            train_payload["metric"] = metric

        r = self._automl.post(
            "/train/automl",
            headers={"X-User-Id": user_id},
            json=train_payload,
        )
        r.raise_for_status()
        return r.json()

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        """GET /jobs/{job_id} — check job status (tries both services)."""
        for client in (self._stats, self._automl):
            try:
                r = client.get(f"/jobs/{job_id}")
                if r.status_code == 200:
                    return r.json()
            except httpx.ConnectError:
                continue
        return {"status": "unknown", "error": "Neither service responded"}

    # ── Convenience: DataFrame input ────────────────────────────

    def analyze_df(
        self,
        df: pd.DataFrame,
        analysis_type: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """High-level: route DataFrame-based analysis to the right endpoint."""
        csv = _df_to_csv(df)
        normalized = _normalize_analysis_type(analysis_type)
        dispatch = {
            "propensity_score": self.run_propensity,
            "survival_analysis": self.run_survival,
            "kaplan_meier": lambda c, cfg: self.run_survival(
                c, {**cfg, "endpoint": "kaplan-meier"}
            ),
            "cox_regression": lambda c, cfg: self.run_survival(c, {**cfg, "endpoint": "cox"}),
            "roc_auc": self.run_roc,
            "logistic_regression": lambda c, cfg: self.direct_analyze(
                c, _prepare_direct_analysis_config(cfg, "logistic_regression")
            ),
            "multiple_regression": lambda c, cfg: self.direct_analyze(
                c, _prepare_direct_analysis_config(cfg, "multiple_regression")
            ),
            "glm": lambda c, cfg: self.direct_analyze(
                c, _prepare_direct_analysis_config(cfg, "glm")
            ),
            "power_analysis": self.run_power,
            "power_analysis_advanced": self.run_power,
            "automl": lambda c, cfg: self.submit_automl(c, cfg),
        }
        handler = dispatch.get(normalized)
        if handler is None:
            return self.direct_analyze(csv, _prepare_direct_analysis_config(config, normalized))
        if normalized == "automl":
            return handler(csv, _prepare_automl_training_config(df, config))
        return handler(csv, config)

    # ── Cleanup ─────────────────────────────────────────────────

    def close(self) -> None:
        self._stats.close()
        self._automl.close()
