"""Analysis Delegator — Routes analysis to automl-stat-mcp or local engine.

Implements the Constitution Article IV §1 contract:
  - RDE orchestrates, checks hooks/constraints
  - automl-stat-mcp executes heavy statistical analysis
  - Fallback to ScipyStatisticalEngine when automl is unavailable

Usage in Phase 6 tools:
    delegator = get_analysis_delegator()
    result = delegator.run_analysis(df, config)
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Analysis types that should be delegated to automl-stat-mcp
AUTOML_PREFERRED = frozenset({
    "propensity_score",
    "survival_analysis",
    "kaplan_meier",
    "cox_regression",
    "roc_auc",
    "logistic_regression",
    "multiple_regression",
    "glm",
    "automl",
    "power_analysis_advanced",
})

# Analysis types handled locally
LOCAL_ONLY = frozenset({
    "t_test",
    "mann_whitney",
    "chi_square",
    "fisher_exact",
    "shapiro_wilk",
    "kolmogorov_smirnov",
    "correlation",
    "kruskal_wallis",
    "anova",
    "table_one",
    "descriptive",
})


class AnalysisDelegator:
    """Routes analysis requests to the best available engine."""

    def __init__(self) -> None:
        self._automl_available: bool | None = None

    def _check_automl(self) -> bool:
        """Lazily check if stats-service (port 8003) is available (cached)."""
        if self._automl_available is None:
            try:
                from rde.infrastructure.adapters.automl_gateway import AutomlGateway
                gw = AutomlGateway()
                self._automl_available = gw.is_available()
                gw.close()
                if self._automl_available:
                    logger.info("automl-stat-mcp stats-service detected at localhost:8003")
                else:
                    logger.info("automl-stat-mcp not available — using local engine")
            except Exception as exc:
                logger.warning("automl availability check failed: %s", exc)
                self._automl_available = False
        return self._automl_available

    def run_analysis(
        self,
        df: pd.DataFrame,
        analysis_type: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run analysis, delegating to automl if appropriate and available.

        Returns dict with at least: {"source": "automl"|"local", "result": ...}
        """
        normalized = analysis_type.lower().replace("-", "_").replace(" ", "_")

        # Local-only analyses — always use ScipyEngine
        if normalized in LOCAL_ONLY:
            return self._run_local(df, normalized, config)

        # automl-preferred — try automl first
        if normalized in AUTOML_PREFERRED and self._check_automl():
            try:
                return self._run_automl(df, normalized, config)
            except Exception as e:
                logger.warning(
                    "automl delegation failed for %s: %s — falling back to local",
                    analysis_type, e,
                )

        # Fallback to local
        return self._run_local(df, normalized, config)

    def _run_automl(
        self, df: pd.DataFrame, analysis_type: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """Delegate to automl-stat-mcp via the new REST API."""
        from rde.infrastructure.adapters.automl_gateway import AutomlGateway

        gw = AutomlGateway()
        try:
            result = gw.analyze_df(df, analysis_type, config)
            return {"source": "automl-stat-mcp", "result": result}
        finally:
            gw.close()

    def _run_local(
        self, df: pd.DataFrame, analysis_type: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run analysis using local ScipyStatisticalEngine."""
        from rde.infrastructure.adapters import ScipyStatisticalEngine

        engine = ScipyStatisticalEngine()

        if analysis_type == "table_one":
            result = engine.generate_table_one(
                df,
                config.get("group_var", ""),
                config.get("variables", []),
            )
        else:
            result = engine.run_test(
                df,
                analysis_type,
                config.get("variables", []),
                **{k: v for k, v in config.items() if k != "variables"},
            )

        return {"source": "local (ScipyStatisticalEngine)", "result": result}

    @property
    def automl_available(self) -> bool:
        """Check if automl-stat-mcp is available."""
        return self._check_automl()

    def get_capabilities(self) -> dict[str, str]:
        """Return available analysis capabilities and which engine handles them."""
        caps: dict[str, str] = {}
        for t in LOCAL_ONLY:
            caps[t] = "local"
        for t in AUTOML_PREFERRED:
            caps[t] = "automl" if self._check_automl() else "local (fallback)"
        return caps


# ── Singleton ────────────────────────────────────────────────────────

_delegator: AnalysisDelegator | None = None


def get_analysis_delegator() -> AnalysisDelegator:
    """Return the global AnalysisDelegator singleton."""
    global _delegator
    if _delegator is None:
        _delegator = AnalysisDelegator()
    return _delegator
