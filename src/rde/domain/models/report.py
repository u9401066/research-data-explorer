"""EDAReport / ReportSection — Aggregate Root.

The final structured report produced by the EDA pipeline.
This is the primary output artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ReportFormat(Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    DOCX = "docx"
    PDF = "pdf"


REQUIRED_SECTIONS = [
    "data_overview",
    "data_quality",
    "variable_profiles",
    "key_findings",
    "statistical_analyses",
    "recommendations",
]


@dataclass
class ReportSection:
    """A section of the EDA report."""

    section_id: str  # e.g., "data_overview"
    title: str
    content: str
    figures: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    order: int = 0


@dataclass
class EDAReport:
    """Aggregate Root — The final EDA report.

    Invariants (Hook H-005):
    - Must contain all REQUIRED_SECTIONS before export.
    - Must not contain sensitive paths (Hook H-006).
    """

    id: str
    dataset_id: str
    project_id: str
    title: str
    created_at: datetime = field(default_factory=datetime.now)
    sections: list[ReportSection] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- Domain Logic ---

    def validate_integrity(self) -> list[str]:
        """Hook H-005: all required sections must be present."""
        present = {s.section_id for s in self.sections}
        missing = [sid for sid in REQUIRED_SECTIONS if sid not in present]
        errors = []
        if missing:
            errors.append(f"Missing required sections: {', '.join(missing)}")
        return errors

    def add_section(self, section: ReportSection) -> None:
        self.sections.append(section)
        self.sections.sort(key=lambda s: s.order)

    def is_exportable(self) -> bool:
        return len(self.validate_integrity()) == 0

    def to_handoff_metadata(self) -> dict[str, Any]:
        """Metadata for med-paper-assistant handoff."""
        return {
            "source": "research-data-explorer",
            "report_id": self.id,
            "dataset_id": self.dataset_id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "section_count": len(self.sections),
            "has_figures": any(s.figures for s in self.sections),
            "has_tables": any(s.tables for s in self.sections),
        }
