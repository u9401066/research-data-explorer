"""Raw data ingestion models.

Captures normalization actions performed before schema inference so the
pipeline can remain auditable even when messy raw files need repair.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SemanticAliasAssignment:
    """Canonical semantic alias inferred for a normalized column."""

    normalized_name: str
    semantic_alias: str
    matched_pattern: str


@dataclass(frozen=True)
class SuspiciousContentFinding:
    """A suspicious raw-cell payload detected during normalization."""

    category: str
    severity: str
    cell_reference: str
    sample_value: str
    action_taken: str


@dataclass(frozen=True)
class SheetAssessment:
    """Assessment result for one Excel sheet during raw-structure gating."""

    sheet_name: str
    classification: str
    score: float
    row_count: int
    column_count: int
    non_empty_ratio: float
    reasons: tuple[str, ...]
    selected: bool = False


@dataclass(frozen=True)
class ColumnNormalization:
    """A column rename performed during raw-data normalization."""

    original_name: str
    normalized_name: str


@dataclass
class RawDataNormalizationReport:
    """Auditable summary of raw-data normalization applied at load time."""

    encoding_used: str | None = None
    header_row_index: int = 0
    header_row_span: int = 1
    selected_sheet_name: str | None = None
    sheet_selection_mode: str | None = None
    skipped_leading_rows: int = 0
    removed_empty_rows: int = 0
    removed_empty_columns: int = 0
    suspicious_formula_cells: int = 0
    standardized_columns: list[ColumnNormalization] = field(default_factory=list)
    sheet_assessments: list[SheetAssessment] = field(default_factory=list)
    semantic_aliases: list[SemanticAliasAssignment] = field(default_factory=list)
    suspicious_findings: list[SuspiciousContentFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any(
            [
                self.skipped_leading_rows > 0,
                self.header_row_span > 1,
                bool(self.selected_sheet_name),
                len(self.sheet_assessments) > 1,
                self.removed_empty_rows > 0,
                self.removed_empty_columns > 0,
                self.suspicious_formula_cells > 0,
                bool(self.standardized_columns),
                bool(self.semantic_aliases),
                bool(self.suspicious_findings),
                bool(self.warnings),
            ]
        )

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def add_sheet_assessment(
        self,
        *,
        sheet_name: str,
        classification: str,
        score: float,
        row_count: int,
        column_count: int,
        non_empty_ratio: float,
        reasons: tuple[str, ...],
        selected: bool = False,
    ) -> None:
        self.sheet_assessments = [
            item for item in self.sheet_assessments if item.sheet_name != sheet_name
        ]
        self.sheet_assessments.append(
            SheetAssessment(
                sheet_name=sheet_name,
                classification=classification,
                score=score,
                row_count=row_count,
                column_count=column_count,
                non_empty_ratio=non_empty_ratio,
                reasons=reasons,
                selected=selected,
            )
        )

    def add_alias(self, normalized_name: str, semantic_alias: str, matched_pattern: str) -> None:
        if any(item.normalized_name == normalized_name for item in self.semantic_aliases):
            return
        self.semantic_aliases.append(
            SemanticAliasAssignment(
                normalized_name=normalized_name,
                semantic_alias=semantic_alias,
                matched_pattern=matched_pattern,
            )
        )

    def add_suspicious_finding(
        self,
        *,
        category: str,
        severity: str,
        cell_reference: str,
        sample_value: str,
        action_taken: str,
        max_examples: int = 20,
    ) -> None:
        self.suspicious_formula_cells += 1
        if len(self.suspicious_findings) >= max_examples:
            return
        self.suspicious_findings.append(
            SuspiciousContentFinding(
                category=category,
                severity=severity,
                cell_reference=cell_reference,
                sample_value=sample_value,
                action_taken=action_taken,
            )
        )

    @property
    def suspicious_counts_by_severity(self) -> dict[str, int]:
        counts = {"info": 0, "warning": 0, "critical": 0}
        for item in self.suspicious_findings:
            if item.severity not in counts:
                counts[item.severity] = 0
            counts[item.severity] += 1
        return counts

    @property
    def highest_suspicious_severity(self) -> str | None:
        order = {"info": 0, "warning": 1, "critical": 2}
        if not self.suspicious_findings:
            return None
        return max(self.suspicious_findings, key=lambda item: order.get(item.severity, -1)).severity

    def as_dict(self) -> dict[str, object]:
        return {
            "encoding_used": self.encoding_used,
            "header_row_index": self.header_row_index,
            "header_row_span": self.header_row_span,
            "selected_sheet_name": self.selected_sheet_name,
            "sheet_selection_mode": self.sheet_selection_mode,
            "skipped_leading_rows": self.skipped_leading_rows,
            "removed_empty_rows": self.removed_empty_rows,
            "removed_empty_columns": self.removed_empty_columns,
            "suspicious_formula_cells": self.suspicious_formula_cells,
            "sheet_assessments": [
                {
                    "sheet_name": item.sheet_name,
                    "classification": item.classification,
                    "score": item.score,
                    "row_count": item.row_count,
                    "column_count": item.column_count,
                    "non_empty_ratio": item.non_empty_ratio,
                    "reasons": list(item.reasons),
                    "selected": item.selected,
                }
                for item in self.sheet_assessments
            ],
            "standardized_columns": [
                {
                    "original_name": item.original_name,
                    "normalized_name": item.normalized_name,
                }
                for item in self.standardized_columns
            ],
            "semantic_aliases": [
                {
                    "normalized_name": item.normalized_name,
                    "semantic_alias": item.semantic_alias,
                    "matched_pattern": item.matched_pattern,
                }
                for item in self.semantic_aliases
            ],
            "suspicious_findings": [
                {
                    "category": item.category,
                    "severity": item.severity,
                    "cell_reference": item.cell_reference,
                    "sample_value": item.sample_value,
                    "action_taken": item.action_taken,
                }
                for item in self.suspicious_findings
            ],
            "suspicious_counts_by_severity": self.suspicious_counts_by_severity,
            "highest_suspicious_severity": self.highest_suspicious_severity,
            "warnings": list(self.warnings),
        }
