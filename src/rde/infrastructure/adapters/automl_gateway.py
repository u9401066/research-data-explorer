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


def _prepare_direct_analysis_config(config: dict[str, Any], analysis_type: str) -> dict[str, Any]:
    """Map RDE config into stats-service /direct/analyze contract."""
    payload = dict(config)
    if "target" in payload and "target_column" not in payload:
        payload["target_column"] = payload["target"]
    payload["analysis_type"] = analysis_type
    return payload


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
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /direct/analyze — direct CSV statistical analysis."""
        payload = {"csv_content": csv_content, **config}
        r = self._stats.post("/direct/analyze", json=payload)
        r.raise_for_status()
        return r.json()

    # ── Propensity Score (stats-service) ────────────────────────

    def run_propensity(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /propensity/* — propensity score analysis."""
        config = dict(config)
        endpoint = config.pop("endpoint", "full")
        payload = {"csv_content": csv_content, **config}
        r = self._stats.post(f"/propensity/{endpoint}", json=payload)
        r.raise_for_status()
        return r.json()

    # ── Survival Analysis (stats-service) ───────────────────────

    def run_survival(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /survival/* — survival analysis."""
        config = dict(config)
        endpoint = config.pop("endpoint", "kaplan-meier")
        payload = {"csv_content": csv_content, **config}
        r = self._stats.post(f"/survival/{endpoint}", json=payload)
        r.raise_for_status()
        return r.json()

    # ── ROC/AUC (stats-service) ─────────────────────────────────

    def run_roc(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /roc/* — ROC curve analysis."""
        config = dict(config)
        endpoint = config.pop("endpoint", "compute")
        payload = {"csv_content": csv_content, **config}
        r = self._stats.post(f"/roc/{endpoint}", json=payload)
        r.raise_for_status()
        return r.json()

    # ── Power Analysis (stats-service) ──────────────────────────

    def run_power(
        self, csv_content: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /power/* — power analysis for various tests."""
        config = dict(config)
        test_type = config.pop("test_type", "ttest")
        payload = {**config}
        r = self._stats.post(f"/power/{test_type}", json=payload)
        r.raise_for_status()
        return r.json()

    # ── AutoML Training (automl-service) ────────────────────────

    def submit_automl(
        self, csv_content: str, config: dict[str, Any],
    ) -> str:
        """POST /train/automl — submit AutoML training job."""
        # First upload dataset
        upload_r = self._automl.post(
            "/datasets/upload",
            json={"csv_content": csv_content, "name": config.get("name", "rde_data")},
        )
        upload_r.raise_for_status()
        dataset_id = upload_r.json().get("dataset_id", "")

        # Then submit training
        train_payload = {"dataset_id": dataset_id, **config}
        r = self._automl.post("/train/automl", json=train_payload)
        r.raise_for_status()
        return r.json().get("job_id", "")

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
        self, df: pd.DataFrame, analysis_type: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """High-level: route DataFrame-based analysis to the right endpoint."""
        csv = _df_to_csv(df)
        normalized = _normalize_analysis_type(analysis_type)
        dispatch = {
            "propensity_score": self.run_propensity,
            "survival_analysis": self.run_survival,
            "kaplan_meier": lambda c, cfg: self.run_survival(c, {**cfg, "endpoint": "kaplan-meier"}),
            "cox_regression": lambda c, cfg: self.run_survival(c, {**cfg, "endpoint": "cox"}),
            "roc_auc": self.run_roc,
            "logistic_regression": lambda c, cfg: self.direct_analyze(c, _prepare_direct_analysis_config(cfg, "logistic_regression")),
            "multiple_regression": lambda c, cfg: self.direct_analyze(c, _prepare_direct_analysis_config(cfg, "multiple_regression")),
            "glm": lambda c, cfg: self.direct_analyze(c, _prepare_direct_analysis_config(cfg, "glm")),
            "power_analysis": self.run_power,
            "power_analysis_advanced": self.run_power,
            "automl": lambda c, cfg: {"job_id": self.submit_automl(c, cfg)},
        }
        handler = dispatch.get(normalized)
        if handler is None:
            return self.direct_analyze(csv, _prepare_direct_analysis_config(config, normalized))
        return handler(csv, config)

    # ── Cleanup ─────────────────────────────────────────────────

    def close(self) -> None:
        self._stats.close()
        self._automl.close()
