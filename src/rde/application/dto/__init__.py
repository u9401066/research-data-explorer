"""Application DTOs — Data Transfer Objects.

Flat structures for crossing layer boundaries.
No domain logic — pure data carriers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileInfo:
    """Lightweight file information returned by scan."""

    file_name: str
    file_path: str
    file_format: str
    file_size_bytes: int
    is_loadable: bool
    rejection_reason: str = ""


@dataclass
class DatasetSummary:
    """Summary view of a loaded dataset."""

    dataset_id: str
    file_name: str
    row_count: int
    column_count: int
    status: str
    variables: list[VariableSummary] = field(default_factory=list)


@dataclass
class VariableSummary:
    """Summary view of a variable."""

    name: str
    dtype: str
    variable_type: str
    missing_rate: float
    n_unique: int
    is_pii_suspect: bool = False


@dataclass
class AnalysisRequest:
    """Request to perform a statistical analysis."""

    dataset_id: str
    analysis_type: str  # "univariate", "bivariate", "table_one", "correlation"
    variables: list[str] = field(default_factory=list)
    group_variable: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class CleaningPreview:
    """Preview of suggested cleaning actions for user confirmation."""

    dataset_id: str
    actions: list[CleaningActionPreview] = field(default_factory=list)


@dataclass
class CleaningActionPreview:
    """A single cleaning action preview."""

    index: int
    action_type: str
    target_variable: str | None
    description: str
    rationale: str
    impact: str = ""  # e.g., "Affects 42 rows"


@dataclass
class ReportExportRequest:
    """Request to export a report."""

    report_id: str
    format: str = "markdown"  # markdown, html, pdf
    include_figures: bool = True
    for_paper_assistant: bool = False
