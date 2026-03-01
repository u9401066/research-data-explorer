"""Domain Events — Signals emitted when significant state changes occur.

Events cover the 11-Phase Auditable EDA Pipeline lifecycle,
from data intake through audit review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""

    event_type: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Phase 0-1: Project Setup & Data Intake ──────────────────────────


@dataclass(frozen=True)
class DatasetDiscovered(DomainEvent):
    """Emitted when a new data file is found in the rawdata folder."""

    event_type: str = "dataset.discovered"
    file_path: str = ""
    file_format: str = ""
    file_size_bytes: int = 0


@dataclass(frozen=True)
class DatasetLoaded(DomainEvent):
    """Emitted when a dataset is successfully loaded into memory."""

    event_type: str = "dataset.loaded"
    dataset_id: str = ""
    row_count: int = 0
    column_count: int = 0


# ── Phase 2: Schema Registry ────────────────────────────────────────


@dataclass(frozen=True)
class SchemaBuilt(DomainEvent):
    """Emitted when variable schema is finalized."""

    event_type: str = "schema.built"
    dataset_id: str = ""
    variable_count: int = 0
    type_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfilingCompleted(DomainEvent):
    """Emitted when dataset profiling finishes."""

    event_type: str = "profiling.completed"
    dataset_id: str = ""
    overall_missing_rate: float = 0.0
    warnings_count: int = 0


@dataclass(frozen=True)
class QualityAssessed(DomainEvent):
    """Emitted when quality assessment finishes."""

    event_type: str = "quality.assessed"
    dataset_id: str = ""
    overall_score: float = 0.0
    critical_issue_count: int = 0
    has_pii: bool = False


# ── Phase 3-4: Concept Alignment & Plan Registration ────────────────


@dataclass(frozen=True)
class ConceptAligned(DomainEvent):
    """Emitted when research concept is aligned with variables."""

    event_type: str = "concept.aligned"
    project_id: str = ""
    research_question: str = ""
    mapped_variables: int = 0


@dataclass(frozen=True)
class PlanRegistered(DomainEvent):
    """Emitted when analysis plan is registered (pre-registration)."""

    event_type: str = "plan.registered"
    project_id: str = ""
    planned_analyses: int = 0


@dataclass(frozen=True)
class PlanLocked(DomainEvent):
    """Emitted when analysis plan is locked (irreversible)."""

    event_type: str = "plan.locked"
    project_id: str = ""
    locked_at: str = ""  # ISO timestamp


# ── Phase 5-6: Pre-check & Execution ────────────────────────────────


@dataclass(frozen=True)
class PrecheckCompleted(DomainEvent):
    """Emitted when pre-exploration readiness check passes."""

    event_type: str = "precheck.completed"
    project_id: str = ""
    all_passed: bool = False
    warning_count: int = 0


@dataclass(frozen=True)
class CleaningApplied(DomainEvent):
    """Emitted when cleaning actions are applied."""

    event_type: str = "cleaning.applied"
    dataset_id: str = ""
    actions_applied: int = 0


@dataclass(frozen=True)
class AnalysisCompleted(DomainEvent):
    """Emitted when a statistical analysis step completes."""

    event_type: str = "analysis.completed"
    dataset_id: str = ""
    analysis_type: str = ""
    significant_count: int = 0


@dataclass(frozen=True)
class DecisionLogged(DomainEvent):
    """Emitted when a decision is recorded to the decision log."""

    event_type: str = "decision.logged"
    project_id: str = ""
    decision_type: str = ""
    rationale: str = ""


@dataclass(frozen=True)
class DeviationLogged(DomainEvent):
    """Emitted when a deviation from the plan is recorded."""

    event_type: str = "deviation.logged"
    project_id: str = ""
    original_plan: str = ""
    actual_action: str = ""
    reason: str = ""


# ── Phase 7-8: Collect & Report ──────────────────────────────────────


@dataclass(frozen=True)
class ReportGenerated(DomainEvent):
    """Emitted when the final EDA report is generated."""

    event_type: str = "report.generated"
    report_id: str = ""
    dataset_id: str = ""
    section_count: int = 0


# ── Phase 9-10: Audit & Improve ──────────────────────────────────────


@dataclass(frozen=True)
class AuditCompleted(DomainEvent):
    """Emitted when audit review is completed."""

    event_type: str = "audit.completed"
    project_id: str = ""
    audit_grade: str = ""  # A/B/C/D/F
    completeness_score: float = 0.0
    issues_found: int = 0


# ── Security & Constraint Events ─────────────────────────────────────


@dataclass(frozen=True)
class PIIDetected(DomainEvent):
    """Emitted when potential PII is found (Hook H-004)."""

    event_type: str = "security.pii_detected"
    dataset_id: str = ""
    variable_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConstraintViolation(DomainEvent):
    """Emitted when a hard constraint is violated."""

    event_type: str = "constraint.violation"
    constraint_id: str = ""
    description: str = ""
