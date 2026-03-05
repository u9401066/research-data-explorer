"""CollinearityChecker — Domain Service.

Centralized S-007 collinearity detection.
Used by both check_readiness (Phase 5) and correlation_matrix (Phase 6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollinearPair:
    """A pair of variables with high correlation."""

    var1: str
    var2: str
    correlation: float


@dataclass(frozen=True)
class CollinearityReport:
    """Result of collinearity analysis."""

    pairs: tuple[CollinearPair, ...]
    threshold: float

    @property
    def has_collinearity(self) -> bool:
        return len(self.pairs) > 0

    def format_warnings(self, max_pairs: int = 5) -> list[str]:
        """Return formatted warning strings."""
        return [
            f"{p.var1} ↔ {p.var2} (r={p.correlation:.3f})"
            for p in self.pairs[:max_pairs]
        ]


def check_collinearity(
    data: Any,
    variables: list[str] | None = None,
    threshold: float = 0.8,
) -> CollinearityReport:
    """Check pairwise correlation for collinearity (S-007).

    Args:
        data: DataFrame
        variables: Numeric columns to check. If None, all numeric columns.
        threshold: Absolute correlation threshold (default 0.8).

    Returns:
        CollinearityReport with detected pairs.
    """
    df: pd.DataFrame = data

    if variables:
        numeric_cols = [
            v for v in variables
            if v in df.columns and pd.api.types.is_numeric_dtype(df[v])
        ]
    else:
        numeric_cols = df.select_dtypes(include="number").columns.tolist()

    if len(numeric_cols) < 2:
        return CollinearityReport(pairs=(), threshold=threshold)

    corr = df[numeric_cols].corr()
    pairs: list[CollinearPair] = []

    for i in range(len(numeric_cols)):
        for j in range(i + 1, len(numeric_cols)):
            r = float(corr.iloc[i, j])
            if abs(r) > threshold:
                pairs.append(CollinearPair(
                    var1=numeric_cols[i],
                    var2=numeric_cols[j],
                    correlation=r,
                ))

    # Sort by absolute correlation descending
    pairs.sort(key=lambda p: abs(p.correlation), reverse=True)

    return CollinearityReport(pairs=tuple(pairs), threshold=threshold)
