"""Variable — Entity within a Dataset.

Represents a single column/variable with its type classification
and descriptive metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VariableType(Enum):
    """Statistical variable type classification."""

    CONTINUOUS = "continuous"
    CATEGORICAL = "categorical"
    ORDINAL = "ordinal"
    BINARY = "binary"
    DATETIME = "datetime"
    TEXT = "text"
    ID = "id"  # Identifier column, not for analysis
    UNKNOWN = "unknown"


class VariableRole(Enum):
    """Analytical role hint."""

    OUTCOME = "outcome"
    PREDICTOR = "predictor"
    COVARIATE = "covariate"
    GROUP = "group"  # Grouping variable for comparisons
    ID = "id"
    UNASSIGNED = "unassigned"


@dataclass
class Variable:
    """A column in the dataset.

    Attributes:
        name: Column name as it appears in the data.
        dtype: Raw pandas/polars dtype string.
        variable_type: Statistical type (inferred or user-set).
        role: Analytical role (user-assigned).
        n_missing: Count of missing values.
        n_unique: Count of unique values.
        is_pii_suspect: Whether PII detection flagged this variable.
    """

    name: str
    dtype: str
    variable_type: VariableType = VariableType.UNKNOWN
    role: VariableRole = VariableRole.UNASSIGNED
    n_missing: int = 0
    n_unique: int = 0
    is_pii_suspect: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def missing_rate(self) -> float:
        total = self.extra.get("total_count", 0)
        if total == 0:
            return 0.0
        return self.n_missing / total

    def is_analyzable(self) -> bool:
        """Variables marked as ID or with unknown type are not analyzable."""
        return self.variable_type not in (VariableType.ID, VariableType.UNKNOWN)
