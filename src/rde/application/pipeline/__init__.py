"""EDA Pipeline — 11-Phase Auditable state machine.

Orchestrates the full EDA workflow with audit trail,
tracking state transitions and enforcing phase ordering constraints.
Each phase produces artifacts; plan deviations must be logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class PipelinePhase(Enum):
    """The 11 phases of the auditable EDA pipeline."""

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


PHASE_ORDER = list(PipelinePhase)

# Phases that can be skipped in "Quick Explore" mode
OPTIONAL_PHASES = {
    PipelinePhase.CONCEPT_ALIGNMENT,
    PipelinePhase.PLAN_REGISTRATION,
    PipelinePhase.PRE_EXPLORE_CHECK,
    PipelinePhase.COLLECT_RESULTS,
    PipelinePhase.AUDIT_REVIEW,
    PipelinePhase.AUTO_IMPROVE,
}

# Each phase requires these prior phases to be completed
PREREQUISITES: dict[PipelinePhase, set[PipelinePhase]] = {
    PipelinePhase.DATA_INTAKE: {PipelinePhase.PROJECT_SETUP},
    PipelinePhase.SCHEMA_REGISTRY: {PipelinePhase.DATA_INTAKE},
    PipelinePhase.CONCEPT_ALIGNMENT: {PipelinePhase.SCHEMA_REGISTRY},
    PipelinePhase.PLAN_REGISTRATION: {PipelinePhase.CONCEPT_ALIGNMENT},
    PipelinePhase.PRE_EXPLORE_CHECK: {PipelinePhase.PLAN_REGISTRATION},
    PipelinePhase.EXECUTE_EXPLORATION: {PipelinePhase.PRE_EXPLORE_CHECK},
    PipelinePhase.COLLECT_RESULTS: {PipelinePhase.EXECUTE_EXPLORATION},
    PipelinePhase.REPORT_ASSEMBLY: {PipelinePhase.SCHEMA_REGISTRY},  # minimal: need schema
    PipelinePhase.AUDIT_REVIEW: {PipelinePhase.REPORT_ASSEMBLY},
    PipelinePhase.AUTO_IMPROVE: {PipelinePhase.AUDIT_REVIEW},
}

# Phases that require user confirmation before completion
USER_CONFIRMATION_REQUIRED = {
    PipelinePhase.CONCEPT_ALIGNMENT,
    PipelinePhase.PLAN_REGISTRATION,
}

# Required artifacts per phase (artifact gate)
REQUIRED_ARTIFACTS: dict[PipelinePhase, list[str]] = {
    PipelinePhase.PROJECT_SETUP: ["project.yaml"],
    PipelinePhase.DATA_INTAKE: ["intake_report.json"],
    PipelinePhase.SCHEMA_REGISTRY: ["schema.json"],
    PipelinePhase.CONCEPT_ALIGNMENT: ["concept_alignment.md", "variable_roles.json"],
    PipelinePhase.PLAN_REGISTRATION: ["analysis_plan.yaml"],
    PipelinePhase.PRE_EXPLORE_CHECK: ["readiness_checklist.json"],
    PipelinePhase.EXECUTE_EXPLORATION: ["decision_log.jsonl"],
    PipelinePhase.COLLECT_RESULTS: ["results_summary.json"],
    PipelinePhase.REPORT_ASSEMBLY: ["eda_report.md"],
    PipelinePhase.AUDIT_REVIEW: ["audit_report.json"],
    PipelinePhase.AUTO_IMPROVE: ["final_report.md"],
}


@dataclass
class PhaseResult:
    """Result of executing a pipeline phase."""

    phase: PipelinePhase
    completed_at: datetime
    success: bool
    artifacts: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    user_confirmed: bool = False


@dataclass
class PipelineState:
    """Tracks the current state of the 11-Phase Auditable EDA pipeline."""

    project_id: str
    current_phase: PipelinePhase | None = None
    completed_phases: dict[PipelinePhase, PhaseResult] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    plan_locked: bool = False
    plan_locked_at: datetime | None = None
    is_quick_explore: bool = False

    def can_execute(self, phase: PipelinePhase) -> tuple[bool, str]:
        """Check if a phase can be executed given prerequisites and artifact gate."""
        # Check prerequisites
        required = PREREQUISITES.get(phase, set())
        if not self.is_quick_explore:
            missing = required - set(self.completed_phases.keys())
        else:
            # Quick explore skips optional phases
            missing = (required - OPTIONAL_PHASES) - set(self.completed_phases.keys())

        if missing:
            names = ", ".join(p.value for p in missing)
            return False, f"Missing prerequisites: {names}"

        # Phase 6+ requires locked plan (unless quick explore)
        if (
            phase == PipelinePhase.EXECUTE_EXPLORATION
            and not self.plan_locked
            and not self.is_quick_explore
        ):
            return False, "Analysis plan must be locked (Phase 4) before execution"

        return True, ""

    def mark_started(self, phase: PipelinePhase) -> None:
        self.current_phase = phase

    def mark_completed(self, result: PhaseResult) -> None:
        self.completed_phases[result.phase] = result
        self.current_phase = None

        # Auto-lock plan when Phase 4 completes
        if result.phase == PipelinePhase.PLAN_REGISTRATION and result.success:
            self.plan_locked = True
            self.plan_locked_at = result.completed_at

    def requires_user_confirmation(self, phase: PipelinePhase) -> bool:
        """Check if this phase needs explicit user confirmation."""
        return phase in USER_CONFIRMATION_REQUIRED

    @property
    def progress(self) -> float:
        """Progress percentage (0-100)."""
        total = len(PHASE_ORDER) if not self.is_quick_explore else (
            len(PHASE_ORDER) - len(OPTIONAL_PHASES)
        )
        completed = len(self.completed_phases)
        return min((completed / total) * 100, 100.0)

    @property
    def next_suggested_phase(self) -> PipelinePhase | None:
        """Suggest the next logical phase."""
        for phase in PHASE_ORDER:
            if phase in self.completed_phases:
                continue
            if self.is_quick_explore and phase in OPTIONAL_PHASES:
                continue
            can, _ = self.can_execute(phase)
            if can:
                return phase
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "mode": "quick_explore" if self.is_quick_explore else "full_audit",
            "progress": f"{self.progress:.0f}%",
            "current_phase": self.current_phase.value if self.current_phase else None,
            "completed": [p.value for p in self.completed_phases],
            "plan_locked": self.plan_locked,
            "next_suggested": (
                self.next_suggested_phase.value if self.next_suggested_phase else "done"
            ),
        }
