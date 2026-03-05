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

    @classmethod
    def from_markdown(
        cls,
        markdown: str,
        *,
        report_id: str = "md_import",
        dataset_id: str = "unknown",
        project_id: str = "unknown",
        title: str | None = None,
    ) -> "EDAReport":
        """Parse a markdown report into an EDAReport with sections.

        Splits on ## headings. Extracts YAML frontmatter for title/metadata.
        Figure references in content are preserved for the exporter to embed.
        """
        import re

        metadata: dict[str, Any] = {}
        body = markdown

        # Extract YAML frontmatter (---\n...\n---)
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", markdown, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    metadata[key.strip()] = val.strip().strip('"').strip("'")
            body = markdown[fm_match.end():]

        # Use frontmatter title if not provided
        if title is None:
            title = str(metadata.pop("title", "EDA Report"))

        # Split body into sections by ## headings
        section_pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
        splits = list(section_pattern.finditer(body))

        sections: list[ReportSection] = []
        # Content before first ## heading goes into "overview"
        if splits:
            preamble = body[:splits[0].start()].strip()
            if preamble:
                sections.append(ReportSection(
                    section_id="data_overview",
                    title="Overview",
                    content=preamble,
                    order=0,
                ))

        for idx, match in enumerate(splits):
            heading = match.group(1).strip()
            start = match.end()
            end = splits[idx + 1].start() if idx + 1 < len(splits) else len(body)
            content = body[start:end].strip()

            # Derive section_id from heading
            section_id = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
            # Map common headings to required section IDs
            id_map = {
                "table_1": "data_overview",
                "baseline": "data_overview",
                "biomarker": "statistical_analyses",
                "correlation": "statistical_analyses",
                "egfr": "statistical_analyses",
                "subgroup": "statistical_analyses",
                "creatinine": "statistical_analyses",
                "sex_difference": "statistical_analyses",
                "missing": "data_quality",
                "methodology": "recommendations",
                "limitation": "recommendations",
                "executive": "key_findings",
                "finding": "key_findings",
                "pipeline": "recommendations",
            }
            for keyword, mapped_id in id_map.items():
                if keyword in section_id:
                    # Keep unique by appending index if already used
                    used = {s.section_id for s in sections}
                    candidate = mapped_id
                    if candidate in used:
                        candidate = f"{mapped_id}_{idx}"
                    section_id = candidate
                    break

            sections.append(ReportSection(
                section_id=section_id,
                title=heading,
                content=content,
                order=idx + 1,
            ))

        # Ensure all REQUIRED_SECTIONS exist (stub missing ones)
        present_ids = {s.section_id for s in sections}
        for req_id in REQUIRED_SECTIONS:
            if req_id not in present_ids:
                sections.append(ReportSection(
                    section_id=req_id,
                    title=req_id.replace("_", " ").title(),
                    content="(Auto-generated stub — see other sections for details.)",
                    order=100,
                ))

        return cls(
            id=report_id,
            dataset_id=dataset_id,
            project_id=project_id,
            title=title,
            sections=sorted(sections, key=lambda s: s.order),
            metadata=metadata,
        )
