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
AUTOML_PREFERRED = frozenset(
    {
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
    }
)

# Analysis types handled locally
LOCAL_ONLY = frozenset(
    {
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
        "learning_curve_cusum",
    }
)

LOCAL_FALLBACK_UNSUPPORTED = frozenset(
    {
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
    }
)


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
                    analysis_type,
                    e,
                )

        # Fallback to local
        return self._run_local(df, normalized, config)

    def _run_automl(
        self,
        df: pd.DataFrame,
        analysis_type: str,
        config: dict[str, Any],
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
        self,
        df: pd.DataFrame,
        analysis_type: str,
        config: dict[str, Any],
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
        elif analysis_type == "descriptive":
            variables = [v for v in config.get("variables", []) if v in df.columns]
            if not variables:
                result = {
                    "error": "Descriptive analysis requires at least one valid variable.",
                    "suggestion": "Provide config['variables'] with existing column names.",
                }
            else:
                summary: dict[str, Any] = {}
                for column in variables:
                    series = df[column].dropna()
                    if series.empty:
                        summary[column] = {"n": 0, "missing": int(df[column].isna().sum())}
                    elif pd.api.types.is_numeric_dtype(series):
                        summary[column] = {
                            "n": int(series.count()),
                            "missing": int(df[column].isna().sum()),
                            "mean": float(series.mean()),
                            "std": float(series.std()),
                            "median": float(series.median()),
                            "min": float(series.min()),
                            "max": float(series.max()),
                        }
                    else:
                        summary[column] = {
                            "n": int(series.count()),
                            "missing": int(df[column].isna().sum()),
                            "n_unique": int(series.nunique()),
                            "top": str(series.mode().iloc[0]) if not series.mode().empty else None,
                        }
                result = {"analysis_type": "descriptive", "summary": summary}
        elif analysis_type == "learning_curve_cusum":
            result = self._run_learning_curve_cusum(df, config)
        elif analysis_type in LOCAL_FALLBACK_UNSUPPORTED:
            result = {
                "error": f"Local ScipyStatisticalEngine does not support '{analysis_type}'.",
                "suggestion": "Start automl-stat-mcp via `cd vendor/automl-stat-mcp && docker compose up -d` to run this analysis.",
            }
        else:
            result = engine.run_test(
                df,
                analysis_type,
                config.get("variables", []),
                **{k: v for k, v in config.items() if k != "variables"},
            )

        return {"source": "local (ScipyStatisticalEngine)", "result": result}

    def _run_learning_curve_cusum(
        self,
        df: pd.DataFrame,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a descriptive operator-level learning-curve CUSUM analysis."""
        success_var = config.get("target")
        operator_var = config.get("group_var")
        covariates = config.get("covariates", []) or []
        trial_var = config.get("trial_var") or (covariates[0] if covariates else None)

        missing = [
            name
            for name, value in {
                "target_variable": success_var,
                "group_variable": operator_var,
                "trial_variable": trial_var,
            }.items()
            if not value
        ]
        if missing:
            return {
                "error": "learning_curve_cusum requires target, operator, and trial variables.",
                "suggestion": f"Provide {', '.join(missing)} via run_advanced_analysis().",
            }

        required_columns = [str(success_var), str(operator_var), str(trial_var)]
        missing_columns = [column for column in required_columns if column not in df.columns]
        if missing_columns:
            return {
                "error": f"Columns not found for learning_curve_cusum: {', '.join(missing_columns)}",
                "suggestion": "Check the schema and provide existing column names.",
            }

        working = df[required_columns].copy().dropna()
        if working.empty:
            return {
                "error": "No complete rows available for learning_curve_cusum.",
                "suggestion": "Ensure operator, trial, and success columns all contain data.",
            }

        working["_success"] = pd.to_numeric(working[str(success_var)], errors="coerce")
        working["_trial"] = pd.to_numeric(working[str(trial_var)], errors="coerce")
        working = working.dropna(subset=["_success", "_trial"])
        if working.empty:
            return {
                "error": "learning_curve_cusum requires numeric trial order and binary success values.",
                "suggestion": "Convert Trial to numeric and ensure success is encoded as 0/1.",
            }

        working["_success"] = working["_success"].astype(int)
        success_values = set(working["_success"].unique().tolist())
        if not success_values.issubset({0, 1}):
            return {
                "error": "learning_curve_cusum requires a binary success variable encoded as 0/1.",
                "suggestion": f"Observed values: {sorted(success_values)}",
            }

        working = working.sort_values([str(operator_var), "_trial"]).reset_index(drop=True)
        cohort_success_rate = float(working["_success"].mean())
        target_success_rate = float(config.get("target_success_rate", cohort_success_rate))
        working["_cusum_increment"] = working["_success"] - target_success_rate
        working["_cusum"] = working.groupby(str(operator_var))["_cusum_increment"].cumsum()

        operators: list[dict[str, Any]] = []
        improving = 0
        for operator_id, operator_df in working.groupby(str(operator_var), sort=False):
            operator_df = operator_df.sort_values("_trial")
            success_rate = float(operator_df["_success"].mean())
            final_cusum = float(operator_df["_cusum"].iloc[-1])
            peak_idx = operator_df["_cusum"].idxmax()
            trough_idx = operator_df["_cusum"].idxmin()
            peak_trial = int(operator_df.loc[peak_idx, "_trial"])
            trough_trial = int(operator_df.loc[trough_idx, "_trial"])
            direction = "above_target" if final_cusum >= 0 else "below_target"
            if final_cusum >= 0:
                improving += 1
            operators.append(
                {
                    "operator_id": str(operator_id),
                    "n_trials": int(len(operator_df)),
                    "success_rate": success_rate,
                    "final_cusum": final_cusum,
                    "peak_cusum": float(operator_df["_cusum"].max()),
                    "peak_trial": peak_trial,
                    "trough_cusum": float(operator_df["_cusum"].min()),
                    "trough_trial": trough_trial,
                    "direction": direction,
                    "series": [
                        {
                            "trial": int(row["_trial"]),
                            "success": int(row["_success"]),
                            "cusum": float(row["_cusum"]),
                        }
                        for _, row in operator_df.iterrows()
                    ],
                }
            )

        operators.sort(key=lambda item: (item["final_cusum"], item["success_rate"]), reverse=True)
        interpretation = (
            f"{improving}/{len(operators)} 位施打者的最終 CUSUM 高於 cohort target，"
            f"代表其累積成功表現高於目標成功率 {target_success_rate:.1%}。"
        )

        return {
            "analysis_type": "learning_curve_cusum",
            "success_variable": str(success_var),
            "operator_variable": str(operator_var),
            "trial_variable": str(trial_var),
            "target_success_rate": target_success_rate,
            "cohort_success_rate": cohort_success_rate,
            "operators_analyzed": len(operators),
            "total_trials": int(len(working)),
            "operators_above_target": improving,
            "interpretation": interpretation,
            "operators": operators,
        }

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
