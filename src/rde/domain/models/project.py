"""Project — Aggregate Root.

An EDA project that tracks the overall exploration session,
mapping to the 11-Phase Auditable EDA Pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ProjectStatus(Enum):
    """Project lifecycle states (maps to 11-Phase pipeline)."""

    CREATED = "created"
    PROJECT_SETUP = "phase_00_project_setup"
    DATA_INTAKE = "phase_01_data_intake"
    SCHEMA_REGISTRY = "phase_02_schema_registry"
    CONCEPT_ALIGNMENT = "phase_03_concept_alignment"
    PLAN_REGISTRATION = "phase_04_plan_registration"
    PRE_EXPLORE_CHECK = "phase_05_pre_explore_check"
    EXECUTE_EXPLORATION = "phase_06_execute_exploration"
    COLLECT_RESULTS = "phase_07_collect_results"
    REPORT_ASSEMBLY = "phase_08_report_assembly"
    AUDIT_REVIEW = "phase_09_audit_review"
    AUTO_IMPROVE = "phase_10_auto_improve"
    COMPLETED = "completed"


# Pipeline phase ordering (excluding terminal states)
PIPELINE_ORDER = [s for s in ProjectStatus if s not in (ProjectStatus.CREATED, ProjectStatus.COMPLETED)]


@dataclass
class Project:
    """Aggregate Root — An EDA exploration project.

    Tracks which pipeline phases have been completed and
    holds references to datasets, reports, and audit artifacts.
    """

    id: str
    name: str
    data_dir: Path
    output_dir: Path
    created_at: datetime = field(default_factory=datetime.now)
    status: ProjectStatus = ProjectStatus.CREATED
    research_question: str = ""
    dataset_ids: list[str] = field(default_factory=list)
    report_ids: list[str] = field(default_factory=list)
    completed_phases: list[ProjectStatus] = field(default_factory=list)
    plan_locked: bool = False
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def artifacts_dir(self) -> Path:
        """Directory for pipeline phase artifacts."""
        return self.output_dir / "artifacts"

    @property
    def decision_log_path(self) -> Path:
        return self.output_dir / "decision_log.jsonl"

    @property
    def deviation_log_path(self) -> Path:
        return self.output_dir / "deviation_log.jsonl"

    def advance_to(self, phase: ProjectStatus) -> None:
        """Advance the project to a pipeline phase."""
        if self.status == ProjectStatus.COMPLETED:
            return
        self.status = phase
        if phase not in self.completed_phases:
            self.completed_phases.append(phase)
        # Auto-lock plan when Phase 4 completes
        if phase == ProjectStatus.PLAN_REGISTRATION:
            self.plan_locked = True

    def phase_artifact_dir(self, phase: ProjectStatus) -> Path:
        """Get the artifact directory for a specific phase."""
        return self.artifacts_dir / phase.value

    def current_phase_index(self) -> int:
        if self.status in (ProjectStatus.CREATED, ProjectStatus.COMPLETED):
            return -1
        return PIPELINE_ORDER.index(self.status)

    def progress_percentage(self) -> float:
        return (len(self.completed_phases) / len(PIPELINE_ORDER)) * 100
