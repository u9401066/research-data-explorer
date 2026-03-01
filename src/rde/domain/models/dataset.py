"""Dataset — Aggregate Root.

Represents a loaded dataset with its metadata and state.
The central entity around which all EDA operations revolve.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from rde.domain.models.variable import Variable


class DatasetStatus(Enum):
    """Lifecycle states of a Dataset."""

    DISCOVERED = "discovered"  # File found, not yet loaded
    LOADED = "loaded"  # Data loaded into memory
    PROFILED = "profiled"  # Profiling completed
    QUALITY_ASSESSED = "quality_assessed"
    CLEANED = "cleaned"
    ANALYZED = "analyzed"


@dataclass
class DatasetMetadata:
    """Immutable metadata about the source file (Value Object)."""

    file_path: Path
    file_format: str  # csv, xlsx, parquet, sas7bdat, sav
    file_size_bytes: int
    encoding: str | None = None
    sheet_name: str | None = None  # For Excel files


@dataclass
class Dataset:
    """Aggregate Root — A dataset being explored.

    Invariants:
    - file_format must be in ALLOWED_FORMATS
    - file_size_bytes must not exceed MAX_FILE_SIZE
    - variables list must be consistent with actual data shape
    """

    ALLOWED_FORMATS = {"csv", "xlsx", "xls", "parquet", "sas7bdat", "sav", "dta", "tsv"}
    MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB (H-001)

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: DatasetMetadata | None = None
    status: DatasetStatus = DatasetStatus.DISCOVERED
    variables: list[Variable] = field(default_factory=list)
    row_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    tags: dict[str, Any] = field(default_factory=dict)

    # --- Domain Logic ---

    def validate_loadable(self) -> list[str]:
        """Check if this dataset can be loaded (Hard Constraints H-001, H-002)."""
        errors: list[str] = []
        if self.metadata is None:
            errors.append("Metadata not set — cannot validate.")
            return errors
        if self.metadata.file_format not in self.ALLOWED_FORMATS:
            errors.append(
                f"Format '{self.metadata.file_format}' not allowed. "
                f"Allowed: {', '.join(sorted(self.ALLOWED_FORMATS))}"
            )
        if self.metadata.file_size_bytes > self.MAX_FILE_SIZE:
            size_mb = self.metadata.file_size_bytes / (1024 * 1024)
            errors.append(
                f"File size {size_mb:.1f}MB exceeds limit of "
                f"{self.MAX_FILE_SIZE / (1024 * 1024):.0f}MB."
            )
        return errors

    def mark_loaded(self, variables: list[Variable], row_count: int) -> None:
        self.variables = variables
        self.row_count = row_count
        self.status = DatasetStatus.LOADED

    def mark_profiled(self) -> None:
        self.status = DatasetStatus.PROFILED

    def mark_quality_assessed(self) -> None:
        self.status = DatasetStatus.QUALITY_ASSESSED

    def mark_cleaned(self) -> None:
        self.status = DatasetStatus.CLEANED

    def mark_analyzed(self) -> None:
        self.status = DatasetStatus.ANALYZED

    def meets_min_sample_size(self, min_n: int = 10) -> bool:
        """Hard Constraint H-003: minimum sample size."""
        return self.row_count >= min_n
