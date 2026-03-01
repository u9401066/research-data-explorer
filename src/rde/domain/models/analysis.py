"""AnalysisResult / StatisticalTest — Value Objects.

Immutable results from statistical analyses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TestCategory(Enum):
    """Category of statistical test."""

    NORMALITY = "normality"
    COMPARISON = "comparison"
    CORRELATION = "correlation"
    ASSOCIATION = "association"
    REGRESSION = "regression"
    NONPARAMETRIC = "nonparametric"


@dataclass(frozen=True)
class StatisticalTest:
    """A single statistical test result (Value Object)."""

    test_name: str  # e.g., "Mann-Whitney U", "Shapiro-Wilk"
    category: TestCategory
    statistic: float
    p_value: float
    effect_size: float | None = None
    effect_size_name: str | None = None  # e.g., "Cohen's d", "r"
    ci_lower: float | None = None
    ci_upper: float | None = None
    ci_level: float = 0.95
    degrees_of_freedom: float | None = None
    sample_sizes: tuple[int, ...] = ()
    variables_involved: tuple[str, ...] = ()
    interpretation: str = ""  # Plain-language explanation
    assumptions_met: dict[str, bool] = field(default_factory=dict)

    @property
    def is_significant(self) -> bool:
        return self.p_value < 0.05

    def format_result(self) -> str:
        """Format for user-friendly display.

        Example: "Mann-Whitney U, p = 0.003, r = 0.45"
        """
        parts = [self.test_name, f"p = {self.p_value:.4f}"]
        if self.effect_size is not None and self.effect_size_name:
            parts.append(f"{self.effect_size_name} = {self.effect_size:.3f}")
        return ", ".join(parts)


@dataclass(frozen=True)
class AnalysisResult:
    """Complete analysis result for a step (Value Object)."""

    dataset_id: str
    analysis_type: str  # e.g., "univariate", "bivariate", "table_one"
    created_at: datetime
    tests: tuple[StatisticalTest, ...]
    summary: str = ""  # Plain-language summary
    tables: dict[str, Any] = field(default_factory=dict)
    figures: tuple[str, ...] = ()  # Paths to generated figures
    warnings: tuple[str, ...] = ()

    @property
    def significant_tests(self) -> list[StatisticalTest]:
        return [t for t in self.tests if t.is_significant]
