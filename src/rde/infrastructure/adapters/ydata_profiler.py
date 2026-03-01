"""YDataProfiler — Adapter implementing ProfilerPort.

Wraps ydata-profiling (13.4K★) as the primary EDA profiling engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rde.domain.models.profile import DataProfile, VariableProfile
from rde.domain.ports import ProfilerPort


class YDataProfiler(ProfilerPort):
    """Profiling adapter using ydata-profiling."""

    def __init__(self, minimal: bool = False) -> None:
        self._minimal = minimal

    def profile(self, data: Any, dataset_id: str) -> DataProfile:
        """Generate DataProfile using ydata-profiling."""
        try:
            from ydata_profiling import ProfileReport
        except ImportError:
            raise ImportError(
                "ydata-profiling is required. Install with: pip install ydata-profiling"
            )

        report = ProfileReport(data, minimal=self._minimal, title=f"Profile: {dataset_id}")
        desc = report.get_description()

        variable_profiles = []
        variables_desc = desc.variables if hasattr(desc, "variables") else {}

        for col_name, col_stats in variables_desc.items():
            vp = VariableProfile(
                variable_name=col_name,
                count=int(col_stats.get("count", 0)),
                missing_count=int(col_stats.get("n_missing", 0)),
                missing_rate=float(col_stats.get("p_missing", 0)),
                unique_count=int(col_stats.get("n_distinct", 0)),
                dtype=str(col_stats.get("type", "unknown")),
                mean=col_stats.get("mean"),
                std=col_stats.get("std"),
                min_val=col_stats.get("min"),
                max_val=col_stats.get("max"),
                median=col_stats.get("50%"),
                q1=col_stats.get("25%"),
                q3=col_stats.get("75%"),
                skewness=col_stats.get("skewness"),
                kurtosis=col_stats.get("kurtosis"),
            )
            variable_profiles.append(vp)

        table_stats = desc.table if hasattr(desc, "table") else {}

        return DataProfile(
            dataset_id=dataset_id,
            created_at=datetime.now(),
            row_count=int(table_stats.get("n", len(data))),
            column_count=int(table_stats.get("n_var", len(data.columns))),
            variable_profiles=tuple(variable_profiles),
            duplicate_row_count=int(table_stats.get("n_duplicates", 0)),
            memory_usage_bytes=int(data.memory_usage(deep=True).sum()),
            engine="ydata-profiling",
        )
