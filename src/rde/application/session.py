"""Session Registry — In-memory state for the current MCP server session.

Holds loaded datasets (DataFrame + Dataset entity), projects, profiles,
cleaning plans, analysis results, etc. so MCP tools can reference them by ID.

This is a singleton shared across all tool calls within one server process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from rde.application.decision_logger import DecisionLogger
from rde.application.pipeline import (
    PipelinePhase,
    PipelineState,
    PhaseResult,
    USER_CONFIRMATION_REQUIRED,
    REQUIRED_ARTIFACTS,
)
from rde.domain.models.cleaning import CleaningPlan
from rde.domain.models.dataset import Dataset
from rde.domain.models.profile import DataProfile
from rde.domain.models.project import PIPELINE_ORDER, Project, ProjectStatus
from rde.domain.models.quality import QualityReport
from rde.domain.models.analysis import AnalysisResult
from rde.infrastructure.persistence.artifact_store import ArtifactStore


@dataclass
class DatasetEntry:
    """A loaded dataset and its associated objects."""

    dataset: Dataset
    dataframe: pd.DataFrame
    profile: DataProfile | None = None
    quality_report: QualityReport | None = None
    cleaning_plan: CleaningPlan | None = None
    analysis_results: list[AnalysisResult] = field(default_factory=list)


class SessionRegistry:
    """In-memory registry for the current server session.

    Thread-safe enough for a single-process MCP server.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, DatasetEntry] = {}
        self._projects: dict[str, Project] = {}
        self._pipelines: dict[str, PipelineState] = {}
        self._loggers: dict[str, DecisionLogger] = {}
        self._active_project_id: str | None = None

    # ── Dataset ──────────────────────────────────────────────────────

    def register_dataset(self, dataset: Dataset, dataframe: pd.DataFrame) -> None:
        self._datasets[dataset.id] = DatasetEntry(dataset=dataset, dataframe=dataframe)

    def get_dataset_entry(self, dataset_id: str) -> DatasetEntry:
        if dataset_id not in self._datasets:
            raise KeyError(f"Dataset '{dataset_id}' not found in session.")
        return self._datasets[dataset_id]

    def list_datasets(self) -> list[str]:
        return list(self._datasets.keys())

    # ── Project ──────────────────────────────────────────────────────

    def register_project(self, project: Project) -> None:
        self._projects[project.id] = project
        self._active_project_id = project.id

    def get_project(self, project_id: str | None = None) -> Project:
        pid = project_id or self._active_project_id
        if pid is None:
            raise KeyError(
                "No active project. Start Phase 0 with init_project() before calling "
                "align_concept() or later pipeline tools."
            )
        if pid not in self._projects:
            project = self._load_project_from_repository(pid)
            if project is None:
                raise KeyError(f"Project '{pid}' not found.")
            return project
        return self._projects[pid]

    @property
    def active_project_id(self) -> str | None:
        return self._active_project_id

    # ── Pipeline ─────────────────────────────────────────────────────

    def get_pipeline(self, project_id: str) -> PipelineState:
        if project_id not in self._pipelines:
            self._pipelines[project_id] = PipelineState(project_id=project_id)
        return self._pipelines[project_id]

    def sync_project_from_artifacts(self, project_id: str | None = None) -> Project:
        """Merge artifact-backed phase progress into live project and pipeline state.

        MCP servers keep state in memory, while durable runners and recovery
        fallbacks may write artifacts from a different process. Phase gates must
        trust completed artifacts without weakening failed prerequisite checks.
        """

        project = self.get_project(project_id)
        changed = self._repair_project_from_artifacts(project)
        self._sync_pipeline_from_project(project)
        if changed:
            self._save_project_best_effort(project)
        return project

    def _load_project_from_repository(self, project_id: str) -> Project | None:
        from rde.infrastructure.persistence import (
            FileSystemProjectRepository,
            resolve_projects_base_dir,
        )

        repo = FileSystemProjectRepository(resolve_projects_base_dir())
        try:
            project = repo.load_project(project_id)
        except FileNotFoundError:
            return None

        if self._repair_project_from_artifacts(project):
            repo.save(project)

        self.register_project(project)
        self._rehydrate_pipeline(project)
        return project

    def _save_project_best_effort(self, project: Project) -> None:
        from rde.infrastructure.persistence import (
            FileSystemProjectRepository,
            resolve_projects_base_dir,
        )

        try:
            FileSystemProjectRepository(resolve_projects_base_dir()).save(project)
        except Exception:
            # Artifact-backed resume should not fail a live tool call merely
            # because repository metadata cannot be refreshed.
            pass

    def _repair_project_from_artifacts(self, project: Project) -> bool:
        """Backfill legacy project state from existing phase artifacts."""

        store = ArtifactStore(project.artifacts_dir)
        completed = set(project.completed_phases)

        if project.status in PIPELINE_ORDER:
            completed.add(project.status)

        for project_status in PIPELINE_ORDER:
            phase = PipelinePhase(project_status.value)
            required = REQUIRED_ARTIFACTS.get(phase, [])
            if not required:
                continue
            present, _ = store.check_artifacts(phase)
            if present:
                completed.add(project_status)

        repaired_completed = [status for status in PIPELINE_ORDER if status in completed]
        repaired_status = repaired_completed[-1] if repaired_completed else project.status
        repaired_plan_locked = self._effective_plan_locked(
            store,
            project_plan_locked=project.plan_locked,
        )

        changed = False
        current_completed = [status for status in PIPELINE_ORDER if status in project.completed_phases]
        if current_completed != repaired_completed:
            project.completed_phases = repaired_completed
            changed = True
        if project.status != repaired_status:
            project.status = repaired_status
            changed = True
        if project.plan_locked != repaired_plan_locked:
            project.plan_locked = repaired_plan_locked
            changed = True

        return changed

    def _rehydrate_pipeline(self, project: Project) -> None:
        if project.id in self._pipelines:
            return

        pipeline = PipelineState(project_id=project.id)
        self._pipelines[project.id] = pipeline
        self._sync_pipeline_from_project(project)

    def _sync_pipeline_from_project(self, project: Project) -> None:
        pipeline = self.get_pipeline(project.id)
        pipeline.is_quick_explore = project.config.get("mode") == "quick_explore"
        completed_statuses = set(project.completed_phases)
        store = ArtifactStore(project.artifacts_dir)

        completed_at = (
            project.created_at if isinstance(project.created_at, datetime) else datetime.now()
        )
        for project_status in PIPELINE_ORDER:
            if project_status not in completed_statuses:
                continue
            pipeline_phase = PipelinePhase(project_status.value)
            success = self._artifact_phase_success(
                store,
                pipeline_phase,
                project_plan_locked=project.plan_locked,
            )
            user_confirmed = self._artifact_phase_user_confirmed(
                store,
                pipeline_phase,
                project_plan_locked=project.plan_locked,
            )
            artifacts = {
                filename: str(store.get_path(pipeline_phase, filename))
                for filename in REQUIRED_ARTIFACTS.get(pipeline_phase, [])
                if store.exists(pipeline_phase, filename)
            }
            existing = pipeline.completed_phases.get(pipeline_phase)
            if existing is None:
                pipeline.mark_completed(
                    PhaseResult(
                        phase=pipeline_phase,
                        completed_at=completed_at,
                        success=success,
                        artifacts=artifacts,
                        user_confirmed=user_confirmed,
                    )
                )
            else:
                existing.success = success
                existing.artifacts.update(artifacts)
                existing.user_confirmed = user_confirmed

        if project.plan_locked:
            pipeline.plan_locked = True
            pipeline.plan_locked_at = pipeline.plan_locked_at or project.created_at

    def _analysis_plan_artifact_locked(self, store: ArtifactStore) -> bool:
        return self._effective_plan_locked(store, project_plan_locked=False)

    def _effective_plan_locked(
        self,
        store: ArtifactStore,
        *,
        project_plan_locked: bool,
    ) -> bool:
        plan = store.load(PipelinePhase.PLAN_REGISTRATION, "analysis_plan.yaml")
        if isinstance(plan, dict):
            if plan.get("locked") is True:
                return True
            if plan.get("locked") is False:
                return False
        return bool(project_plan_locked)

    def _artifact_phase_user_confirmed(
        self,
        store: ArtifactStore,
        phase: PipelinePhase,
        *,
        project_plan_locked: bool = False,
    ) -> bool:
        if phase not in USER_CONFIRMATION_REQUIRED:
            return False
        plan_locked = self._effective_plan_locked(
            store,
            project_plan_locked=project_plan_locked,
        )
        if phase == PipelinePhase.CONCEPT_ALIGNMENT:
            alignment = store.load(phase, "variable_roles.json")
            if isinstance(alignment, dict) and "confirmed" in alignment:
                return alignment.get("confirmed") is True
            return plan_locked
        if phase == PipelinePhase.CREATIVE_IDEATION:
            proposal = store.load(phase, "greedy_analysis_candidates.json")
            if isinstance(proposal, dict) and "confirmed" in proposal:
                return proposal.get("confirmed") is True
            return plan_locked
        if phase == PipelinePhase.PLAN_COMPLETENESS_REVIEW:
            review = store.load(phase, "analysis_plan_review.json")
            if isinstance(review, dict) and "confirmed" in review:
                return review.get("confirmed") is True
            return plan_locked
        if phase == PipelinePhase.PLAN_REGISTRATION:
            return plan_locked
        return True

    def _artifact_phase_success(
        self,
        store: ArtifactStore,
        phase: PipelinePhase,
        *,
        project_plan_locked: bool = False,
    ) -> bool:
        if phase == PipelinePhase.PRE_EXPLORE_CHECK:
            readiness = store.load(phase, "readiness_checklist.json")
            return isinstance(readiness, dict) and readiness.get("all_passed") is True
        if phase == PipelinePhase.PLAN_REGISTRATION:
            return self._effective_plan_locked(
                store,
                project_plan_locked=project_plan_locked,
            )
        return True

    # ── Decision Logger ──────────────────────────────────────────────

    def get_logger(self, project_id: str) -> DecisionLogger:
        if project_id not in self._loggers:
            project = self.get_project(project_id)
            logger = DecisionLogger(project.artifacts_dir)
            logger.snapshot_line_counts()
            self._loggers[project_id] = logger
        return self._loggers[project_id]


# ── Module-level singleton ───────────────────────────────────────────

_session: SessionRegistry | None = None


def get_session() -> SessionRegistry:
    """Get or create the global session registry singleton."""
    global _session
    if _session is None:
        _session = SessionRegistry()
    return _session
