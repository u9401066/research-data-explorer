"""AnalyzeVariableUseCase — Pipeline Step 6.

Orchestrates univariate analysis with automatic normality testing,
applying soft constraints S-001, S-003, S-004, S-006.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from rde.domain.models.analysis import AnalysisResult, StatisticalTest, TestCategory
from rde.domain.models.dataset import Dataset
from rde.domain.models.variable import VariableType
from rde.domain.policies.soft_constraints import SoftConstraints
from rde.domain.ports import StatisticalEnginePort


@dataclass
class UnivariateProfile:
    """Profile of a single variable produced by the use case."""

    variable_name: str
    variable_type: str  # "continuous" or "categorical"
    count: int
    missing_count: int
    missing_rate: float
    n_unique: int
    # Numeric-only fields
    descriptive: dict[str, float] | None = None  # mean, std, min, q1, median, q3, max, skewness, kurtosis
    normality_test: StatisticalTest | None = None
    # Categorical-only fields
    top_values: list[tuple[str, int]] | None = None
    # Advisories
    advisories: list[str] | None = None
    viz_suggestion: str | None = None


class AnalyzeVariableUseCase:
    """Univariate analysis with soft constraint enforcement."""

    def __init__(self, engine: StatisticalEnginePort) -> None:
        self._engine = engine

    def execute(
        self,
        dataset: Dataset,
        raw_data: Any,
        variable_name: str,
    ) -> UnivariateProfile:
        """Analyze a single variable and return a structured profile."""
        df: pd.DataFrame = raw_data

        if variable_name not in df.columns:
            raise ValueError(f"Variable '{variable_name}' not found in dataset.")

        col = df[variable_name]
        n_total = len(col)
        missing_count = int(col.isna().sum())
        missing_rate = missing_count / max(n_total, 1)
        n_unique = int(col.nunique())

        advisories: list[str] = []
        descriptive = None
        normality_test = None
        top_values = None

        # Determine variable type from domain model
        var = next((v for v in dataset.variables if v.name == variable_name), None)
        var_type_enum = var.variable_type if var else None
        is_numeric = pd.api.types.is_numeric_dtype(col)

        if is_numeric:
            var_type = "continuous"
            desc = col.describe()
            skew_val = float(col.skew())
            kurt_val = float(col.kurtosis())

            descriptive = {
                "mean": float(desc["mean"]),
                "std": float(desc["std"]),
                "min": float(desc["min"]),
                "q1": float(desc["25%"]),
                "median": float(desc["50%"]),
                "q3": float(desc["75%"]),
                "max": float(desc["max"]),
                "skewness": skew_val,
                "kurtosis": kurt_val,
            }

            # S-001: Normality
            norm_result = self._engine.run_test(df, "Shapiro-Wilk", [variable_name])
            norm_p = norm_result.get("p_value")
            is_normal = norm_p > 0.05 if norm_p is not None else None

            if norm_p is not None:
                normality_test = StatisticalTest(
                    test_name="Shapiro-Wilk",
                    category=TestCategory.NORMALITY,
                    statistic=norm_result.get("statistic", 0),
                    p_value=norm_p,
                    variables_involved=(variable_name,),
                    interpretation=norm_result.get("interpretation", ""),
                )
                s001 = SoftConstraints.s001_normality_check(is_normal, norm_p)
                if not s001.passed:
                    advisories.append(f"[S-001] {s001.suggestion}")

            # S-004: Skewness transform
            s004 = SoftConstraints.s004_transform_suggestion(skew_val)
            if not s004.passed:
                advisories.append(f"[S-004] {s004.suggestion}")

            # S-006: Outlier strategy
            s006 = SoftConstraints.s006_outlier_strategy(skew_val, kurt_val)
            if not s006.passed:
                advisories.append(f"[S-006] {s006.suggestion}")
        else:
            var_type = "categorical"
            vc = col.value_counts().head(20)
            top_values = [(str(k), int(v)) for k, v in vc.items()]

        # S-003: Viz advisor
        viz_type = var_type_enum or (VariableType.CONTINUOUS if is_numeric else VariableType.CATEGORICAL)
        s003 = SoftConstraints.s003_visualization_advisor(viz_type)
        viz_suggestion = s003.suggestion

        return UnivariateProfile(
            variable_name=variable_name,
            variable_type=var_type,
            count=n_total - missing_count,
            missing_count=missing_count,
            missing_rate=missing_rate,
            n_unique=n_unique,
            descriptive=descriptive,
            normality_test=normality_test,
            top_values=top_values,
            advisories=advisories or None,
            viz_suggestion=viz_suggestion,
        )
