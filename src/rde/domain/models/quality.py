"""QualityReport / QualityIssue — Value Objects.

Data quality assessment results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Severity(Enum):
    """Quality issue severity."""

    CRITICAL = "critical"  # Must fix before analysis
    WARNING = "warning"  # Should fix, may affect results
    INFO = "info"  # Worth noting


class IssueCategory(Enum):
    """Quality issue category."""

    COMPLETENESS = "completeness"  # Missing values
    CONSISTENCY = "consistency"  # Contradictory values
    VALIDITY = "validity"  # Out of range / invalid format
    UNIQUENESS = "uniqueness"  # Duplicates
    TIMELINESS = "timeliness"  # Outdated data
    PII = "pii"  # Privacy concern


@dataclass(frozen=True)
class QualityIssue:
    """A single quality issue found in the data (Value Object)."""

    category: IssueCategory
    severity: Severity
    variable_name: str | None  # None if dataset-level issue
    description: str
    affected_rows: int = 0
    suggestion: str = ""


@dataclass(frozen=True)
class QualityReport:
    """Complete quality assessment for a dataset (Value Object)."""

    dataset_id: str
    created_at: datetime
    issues: tuple[QualityIssue, ...]
    overall_score: float  # 0-100, higher is better
    completeness_score: float = 0.0
    consistency_score: float = 0.0
    validity_score: float = 0.0

    @property
    def critical_issues(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == Severity.CRITICAL]

    @property
    def has_pii(self) -> bool:
        return any(i.category == IssueCategory.PII for i in self.issues)

    @property
    def is_analysis_ready(self) -> bool:
        """No critical issues and overall score >= 60."""
        return len(self.critical_issues) == 0 and self.overall_score >= 60
