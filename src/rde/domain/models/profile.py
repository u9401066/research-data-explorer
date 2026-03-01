"""DataProfile / VariableProfile — Value Objects.

Immutable profiling results produced by the profiling step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class VariableProfile:
    """Profiling summary for a single variable (Value Object)."""

    variable_name: str
    count: int
    missing_count: int
    missing_rate: float
    unique_count: int
    dtype: str

    # Numeric stats (None for non-numeric)
    mean: float | None = None
    std: float | None = None
    min_val: float | None = None
    max_val: float | None = None
    median: float | None = None
    q1: float | None = None
    q3: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None

    # Categorical stats (None for non-categorical)
    top_values: tuple[tuple[str, int], ...] | None = None
    mode: str | None = None

    # Normality (filled after analysis)
    is_normal: bool | None = None
    normality_p_value: float | None = None


@dataclass(frozen=True)
class DataProfile:
    """Complete profiling result for a dataset (Value Object)."""

    dataset_id: str
    created_at: datetime
    row_count: int
    column_count: int
    variable_profiles: tuple[VariableProfile, ...]
    duplicate_row_count: int = 0
    memory_usage_bytes: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)
    engine: str = "ydata-profiling"  # Which engine produced this

    @property
    def overall_missing_rate(self) -> float:
        if not self.variable_profiles:
            return 0.0
        total_cells = self.row_count * self.column_count
        if total_cells == 0:
            return 0.0
        total_missing = sum(vp.missing_count for vp in self.variable_profiles)
        return total_missing / total_cells

    def variables_with_high_missing(self, threshold: float = 0.3) -> list[str]:
        """Return variable names with missing rate above threshold."""
        return [
            vp.variable_name
            for vp in self.variable_profiles
            if vp.missing_rate > threshold
        ]
