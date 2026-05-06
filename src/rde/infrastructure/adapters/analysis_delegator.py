"""Analysis Delegator — Routes analysis to automl-stat-mcp or local engine.

Implements the Constitution Article IV §1 contract:
  - RDE orchestrates, checks hooks/constraints
  - automl-stat-mcp executes heavy statistical analysis
  - Fallback to ScipyStatisticalEngine and local-lite statsmodels/scipy when automl is unavailable

Usage in Phase 6 tools:
    delegator = get_analysis_delegator()
    result = delegator.run_analysis(df, config)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
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
        "automl",
    }
)

LOCAL_ADVANCED_LITE = frozenset(
    {
        "propensity_score",
        "survival_analysis",
        "kaplan_meier",
        "cox_regression",
        "roc_auc",
        "logistic_regression",
        "multiple_regression",
        "glm",
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

        if analysis_type in LOCAL_ADVANCED_LITE:
            return self._run_local_advanced_lite(df, analysis_type, config)

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

    def _run_local_advanced_lite(
        self,
        df: pd.DataFrame,
        analysis_type: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run no-Docker advanced analyses needed for complete non-coder reports."""
        if analysis_type == "logistic_regression":
            return {
                "source": "local-lite (statsmodels)",
                "result": self._run_logistic_regression(df, config),
            }
        if analysis_type in {"multiple_regression", "glm"}:
            return {
                "source": "local-lite (statsmodels)",
                "result": self._run_regression_or_glm(df, analysis_type, config),
            }
        if analysis_type == "roc_auc":
            return {
                "source": "local-lite (scipy)",
                "result": self._run_roc_auc(df, config),
            }
        if analysis_type == "power_analysis_advanced":
            return {
                "source": "local-lite (statsmodels)",
                "result": self._run_power_analysis(config),
            }
        if analysis_type == "propensity_score":
            return {
                "source": "local-lite (statsmodels)",
                "result": self._run_propensity_score(df, config),
            }
        if analysis_type in {"survival_analysis", "kaplan_meier"}:
            return {
                "source": "local-lite (kaplan-meier)",
                "result": self._run_kaplan_meier(df, config),
            }
        if analysis_type == "cox_regression":
            return {
                "source": "local-lite (statsmodels)",
                "result": self._run_cox_regression(df, config),
            }
        return {
            "source": "local (ScipyStatisticalEngine)",
            "result": {
                "error": f"Local analysis engine does not support '{analysis_type}'.",
                "suggestion": "Use a supported local analysis type or configure an optional advanced engine endpoint.",
            },
        }

    def _resolve_target(self, config: dict[str, Any]) -> str | None:
        return (
            config.get("target")
            or config.get("target_variable")
            or config.get("target_column")
            or config.get("outcome_column")
        )

    def _resolve_covariates(self, df: pd.DataFrame, config: dict[str, Any]) -> list[str]:
        covariates = config.get("covariates") or []
        if isinstance(covariates, str):
            covariates = [covariates]
        if not covariates:
            excluded = {
                self._resolve_target(config),
                config.get("group_var"),
                config.get("time_variable"),
                config.get("score_variable"),
            }
            covariates = [
                value for value in config.get("variables", []) if value and value not in excluded
            ]
        return [str(column) for column in covariates if str(column) in df.columns]

    def _prepare_model_frame(
        self,
        df: pd.DataFrame,
        target: str | None,
        covariates: list[str],
    ) -> tuple[pd.DataFrame | None, pd.Series | None, pd.DataFrame | None, dict[str, Any] | None]:
        if not target or target not in df.columns:
            return None, None, None, {
                "error": "Advanced local analysis requires a valid target variable.",
                "suggestion": "Provide target_variable with an existing schema column.",
            }
        if not covariates:
            return None, None, None, {
                "error": "Advanced local analysis requires at least one covariate.",
                "suggestion": "Provide covariates such as age, severity, or baseline risk variables.",
            }
        columns = [target, *covariates]
        working = df[columns].copy().dropna()
        if working.empty or len(working) < 3:
            return None, None, None, {
                "error": "Not enough complete rows for local advanced analysis.",
                "suggestion": "Check missingness or reduce the covariate list.",
            }
        y = working[target]
        x = working[covariates].apply(pd.to_numeric, errors="coerce")
        model_frame = pd.concat([y, x], axis=1).dropna()
        if len(model_frame) < 3:
            return None, None, None, {
                "error": "Not enough numeric complete rows for local advanced analysis.",
                "suggestion": "Use numeric covariates or encode categorical covariates first.",
            }
        return model_frame, model_frame[target], model_frame[covariates], None

    def _binary_target(self, y: pd.Series) -> pd.Series | None:
        if pd.api.types.is_numeric_dtype(y):
            numeric = pd.to_numeric(y, errors="coerce")
            values = sorted(v for v in numeric.dropna().unique().tolist())
            if len(values) == 2:
                return numeric.map({values[0]: 0, values[1]: 1}).astype(float)
            if set(values).issubset({0, 1}):
                return numeric.astype(float)
            return None
        categories = y.astype(str).str.strip()
        values = sorted(v for v in categories.dropna().unique().tolist() if v)
        if len(values) != 2:
            return None
        return categories.map({values[0]: 0, values[1]: 1}).astype(float)

    def _run_logistic_regression(self, df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
        import warnings

        import statsmodels.api as sm

        target = self._resolve_target(config)
        covariates = self._resolve_covariates(df, config)
        model_frame, y_raw, x_raw, error = self._prepare_model_frame(df, target, covariates)
        if error:
            return error
        assert model_frame is not None
        assert y_raw is not None
        assert x_raw is not None

        y = self._binary_target(y_raw)
        if y is None:
            return {
                "error": "Logistic regression requires a binary target variable.",
                "suggestion": "Use a 0/1 outcome or choose multiple_regression for continuous outcomes.",
            }
        x = sm.add_constant(x_raw, has_constant="add")
        regularized = False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                fitted = sm.Logit(y, x).fit(disp=False, maxiter=200)
            except Exception as exc:
                try:
                    fitted = sm.Logit(y, x).fit_regularized(
                        disp=False,
                        alpha=float(config.get("regularization_alpha", 1.0)),
                        maxiter=200,
                    )
                    regularized = True
                except Exception as second_exc:
                    return {
                        "error": (
                            f"Local logistic regression failed: {exc}; "
                            f"regularized fallback failed: {second_exc}"
                        ),
                        "suggestion": (
                            "Reduce collinearity, simplify covariates, or use the optional "
                            "advanced engine."
                        ),
                    }

        params = {name: float(value) for name, value in fitted.params.items()}
        raw_pvalues = getattr(fitted, "pvalues", None)
        if raw_pvalues is not None:
            p_values = {name: float(value) for name, value in raw_pvalues.items()}
        else:
            p_values = {name: None for name in params}
        odds_ratios = {name: float(np.exp(value)) for name, value in fitted.params.items()}
        pseudo_r2 = float(getattr(fitted, "prsquared", np.nan))
        return {
            "analysis_type": "logistic_regression",
            "engine": "statsmodels.Logit",
            "target": str(target),
            "covariates": covariates,
            "nobs": int(fitted.nobs),
            "coefficients": params,
            "odds_ratios": odds_ratios,
            "p_values": p_values,
            "pseudo_r2": pseudo_r2,
            "regularized_fallback": regularized,
            "interpretation": (
                "Local logistic regression estimates adjusted associations for a binary outcome. "
                "Odds ratios above 1 indicate higher odds after adjustment; review p-values and confidence intervals before drawing conclusions."
            ),
        }

    def _run_regression_or_glm(
        self,
        df: pd.DataFrame,
        analysis_type: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        import statsmodels.api as sm

        target = self._resolve_target(config)
        covariates = self._resolve_covariates(df, config)
        model_frame, y_raw, x_raw, error = self._prepare_model_frame(df, target, covariates)
        if error:
            return error
        assert y_raw is not None
        assert x_raw is not None

        y = pd.to_numeric(y_raw, errors="coerce")
        x = sm.add_constant(x_raw, has_constant="add")
        if analysis_type == "glm":
            binary_y = self._binary_target(y_raw)
            family = sm.families.Binomial() if binary_y is not None else sm.families.Gaussian()
            y_model = binary_y if binary_y is not None else y
            fitted = sm.GLM(y_model, x, family=family).fit()
            engine = f"statsmodels.GLM({family.__class__.__name__})"
            fit_quality = {"aic": float(fitted.aic)}
        else:
            fitted = sm.OLS(y, x).fit()
            engine = "statsmodels.OLS"
            fit_quality = {
                "r_squared": float(fitted.rsquared),
                "adj_r_squared": float(fitted.rsquared_adj),
            }

        return {
            "analysis_type": analysis_type,
            "engine": engine,
            "target": str(target),
            "covariates": covariates,
            "nobs": int(fitted.nobs),
            "coefficients": {name: float(value) for name, value in fitted.params.items()},
            "p_values": {name: float(value) for name, value in fitted.pvalues.items()},
            **fit_quality,
            "interpretation": (
                "Local adjusted model estimates outcome association after included covariates. "
                "Use coefficient direction, magnitude, and p-values together with the study design."
            ),
        }

    def _run_roc_auc(self, df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve_target(config)
        score = config.get("score_variable") or config.get("score_column")
        if not target or target not in df.columns:
            return {
                "error": "ROC/AUC requires a valid binary target variable.",
                "suggestion": "Provide target_variable with an existing 0/1 outcome column.",
            }
        if not score or score not in df.columns:
            return {
                "error": "ROC/AUC requires a valid score variable.",
                "suggestion": "Provide score_variable or run a model that produces predicted scores.",
            }
        working = df[[target, score]].copy().dropna()
        y = self._binary_target(working[target])
        if y is None:
            return {
                "error": "ROC/AUC requires a binary target variable.",
                "suggestion": "Use a 0/1 outcome for ROC/AUC.",
            }
        scores = pd.to_numeric(working[score], errors="coerce")
        valid = pd.concat([y.rename("target"), scores.rename("score")], axis=1).dropna()
        positives = valid[valid["target"] == 1]
        negatives = valid[valid["target"] == 0]
        if positives.empty or negatives.empty:
            return {
                "error": "ROC/AUC requires both positive and negative outcome classes.",
                "suggestion": "Check outcome coding and class balance.",
            }
        ranks = valid["score"].rank(method="average")
        pos_rank_sum = float(ranks[valid["target"] == 1].sum())
        n_pos = len(positives)
        n_neg = len(negatives)
        auc = (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
        return {
            "analysis_type": "roc_auc",
            "engine": "rank-based AUC",
            "target": str(target),
            "score_variable": str(score),
            "auc": float(auc),
            "n_positive": int(n_pos),
            "n_negative": int(n_neg),
            "interpretation": (
                "AUC estimates discrimination: 0.5 is no better than chance, 1.0 is perfect separation."
            ),
        }

    def _run_power_analysis(self, config: dict[str, Any]) -> dict[str, Any]:
        from statsmodels.stats.power import FTestAnovaPower, GofChisquarePower, TTestIndPower

        test_type = str(config.get("test_type") or "ttest").lower().replace("-", "_")
        effect_size = float(config.get("effect_size", 0.5))
        alpha = float(config.get("alpha", 0.05))
        power_target = config.get("power")
        nobs1 = config.get("nobs1") or config.get("n")
        ratio = float(config.get("ratio", 1.0))

        if test_type in {"ttest", "t_test", "two_sample_ttest"}:
            analyzer = TTestIndPower()
            if nobs1 is not None:
                power = analyzer.power(effect_size=effect_size, nobs1=float(nobs1), alpha=alpha, ratio=ratio)
                solved_nobs1 = float(nobs1)
            else:
                target_power = float(power_target or 0.8)
                solved_nobs1 = float(
                    analyzer.solve_power(
                        effect_size=effect_size,
                        power=target_power,
                        alpha=alpha,
                        ratio=ratio,
                    )
                )
                power = target_power
        elif test_type == "anova":
            analyzer = FTestAnovaPower()
            k_groups = int(config.get("k_groups", config.get("groups", 3)))
            if nobs1 is not None:
                solved_nobs1 = float(nobs1)
                power = analyzer.power(effect_size=effect_size, nobs=float(nobs1), alpha=alpha, k_groups=k_groups)
            else:
                target_power = float(power_target or 0.8)
                solved_nobs1 = float(
                    analyzer.solve_power(
                        effect_size=effect_size,
                        power=target_power,
                        alpha=alpha,
                        k_groups=k_groups,
                    )
                )
                power = target_power
        elif test_type in {"chisquare", "chi_square"}:
            analyzer = GofChisquarePower()
            n_bins = int(config.get("n_bins", 2))
            if nobs1 is not None:
                solved_nobs1 = float(nobs1)
                power = analyzer.power(effect_size=effect_size, nobs=float(nobs1), alpha=alpha, n_bins=n_bins)
            else:
                target_power = float(power_target or 0.8)
                solved_nobs1 = float(
                    analyzer.solve_power(
                        effect_size=effect_size,
                        power=target_power,
                        alpha=alpha,
                        n_bins=n_bins,
                    )
                )
                power = target_power
        else:
            return {
                "error": f"Local power analysis does not support '{test_type}'.",
                "suggestion": "Use test_type='ttest', 'anova', or 'chisquare', or configure the optional advanced engine.",
            }

        return {
            "analysis_type": "power_analysis",
            "engine": "statsmodels.stats.power",
            "test_type": test_type,
            "effect_size": effect_size,
            "alpha": alpha,
            "nobs1": solved_nobs1,
            "power": float(power),
            "interpretation": (
                "Power analysis is approximate and should be reported with effect-size assumptions."
            ),
        }

    def _run_propensity_score(self, df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
        treatment = (
            config.get("treatment_column")
            or config.get("group_var")
            or config.get("group_variable")
        )
        local_config = dict(config)
        local_config["target"] = treatment
        result = self._run_logistic_regression(df, local_config)
        if result.get("error"):
            result["analysis_type"] = "propensity_score"
            return result
        return {
            "analysis_type": "propensity_score",
            "engine": "statsmodels.Logit",
            "treatment_variable": str(treatment),
            "covariates": result.get("covariates", []),
            "propensity_model": result,
            "interpretation": (
                "Local propensity analysis estimates treatment probability from covariates. "
                "It is a lightweight scoring fallback, not a full matching or weighting workflow."
            ),
        }

    def _run_kaplan_meier(self, df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
        time_col = config.get("time_variable") or config.get("time_column")
        event_col = self._resolve_target(config) or config.get("event_column")
        if not time_col or time_col not in df.columns or not event_col or event_col not in df.columns:
            return {
                "error": "Kaplan-Meier summary requires valid time and event variables.",
                "suggestion": "Provide time_variable and target_variable/event column.",
            }
        working = df[[time_col, event_col]].copy().dropna()
        working["_time"] = pd.to_numeric(working[time_col], errors="coerce")
        working["_event"] = pd.to_numeric(working[event_col], errors="coerce")
        working = working.dropna(subset=["_time", "_event"]).sort_values("_time")
        if working.empty:
            return {
                "error": "No numeric complete rows available for Kaplan-Meier summary.",
                "suggestion": "Check survival time and event coding.",
            }
        survival = 1.0
        table: list[dict[str, Any]] = []
        for time in sorted(working.loc[working["_event"] > 0, "_time"].unique()):
            at_risk = int((working["_time"] >= time).sum())
            events = int(((working["_time"] == time) & (working["_event"] > 0)).sum())
            censored = int(((working["_time"] == time) & (working["_event"] <= 0)).sum())
            if at_risk > 0:
                survival *= 1.0 - events / at_risk
            table.append(
                {
                    "time": float(time),
                    "at_risk": at_risk,
                    "events": events,
                    "censored": censored,
                    "survival_probability": float(survival),
                }
            )
        return {
            "analysis_type": "kaplan_meier",
            "engine": "local Kaplan-Meier summary",
            "time_variable": str(time_col),
            "event_variable": str(event_col),
            "nobs": int(len(working)),
            "events": int((working["_event"] > 0).sum()),
            "survival_table": table,
            "interpretation": (
                "Local Kaplan-Meier summary estimates unadjusted survival over observed event times."
            ),
        }

    def _run_cox_regression(self, df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
        from statsmodels.duration.hazard_regression import PHReg

        time_col = config.get("time_variable") or config.get("time_column")
        event_col = self._resolve_target(config) or config.get("event_column")
        covariates = self._resolve_covariates(df, config)
        if not time_col or time_col not in df.columns or not event_col or event_col not in df.columns:
            return {
                "error": "Cox regression requires valid time and event variables.",
                "suggestion": "Provide time_variable, target_variable/event column, and covariates.",
            }
        if not covariates:
            return self._run_kaplan_meier(df, config)
        columns = [time_col, event_col, *covariates]
        working = df[columns].copy().dropna()
        durations = pd.to_numeric(working[time_col], errors="coerce")
        events = pd.to_numeric(working[event_col], errors="coerce")
        exog = working[covariates].apply(pd.to_numeric, errors="coerce")
        model_frame = pd.concat([durations.rename("_time"), events.rename("_event"), exog], axis=1).dropna()
        if len(model_frame) < 5:
            return {
                "error": "Not enough complete rows for local Cox regression.",
                "suggestion": "Use Kaplan-Meier summary or reduce covariates.",
            }
        try:
            fitted = PHReg(
                model_frame["_time"],
                model_frame[covariates],
                status=model_frame["_event"],
            ).fit(disp=False)
        except Exception as exc:
            return {
                "error": f"Local Cox regression failed: {exc}",
                "suggestion": "Use Kaplan-Meier summary or configure the optional advanced engine.",
            }
        params = {name: float(value) for name, value in zip(covariates, fitted.params, strict=False)}
        hazard_ratios = {name: float(np.exp(value)) for name, value in params.items()}
        p_values = {name: float(value) for name, value in zip(covariates, fitted.pvalues, strict=False)}
        return {
            "analysis_type": "cox_regression",
            "engine": "statsmodels.PHReg",
            "time_variable": str(time_col),
            "event_variable": str(event_col),
            "covariates": covariates,
            "nobs": int(len(model_frame)),
            "coefficients": params,
            "hazard_ratios": hazard_ratios,
            "p_values": p_values,
            "interpretation": (
                "Local Cox regression estimates adjusted hazard ratios. Check proportional hazards assumptions before formal publication."
            ),
        }

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
        automl_available = self._check_automl()
        for t in AUTOML_PREFERRED:
            if automl_available:
                caps[t] = "automl"
            elif t in LOCAL_ADVANCED_LITE:
                caps[t] = "local-lite"
            else:
                caps[t] = "automl required"
        return caps


# ── Singleton ────────────────────────────────────────────────────────

_delegator: AnalysisDelegator | None = None


def get_analysis_delegator() -> AnalysisDelegator:
    """Return the global AnalysisDelegator singleton."""
    global _delegator
    if _delegator is None:
        _delegator = AnalysisDelegator()
    return _delegator
